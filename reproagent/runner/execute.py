"""Shell out to nextflow with streamed logs; scrape container digests."""

from __future__ import annotations

import csv
import logging
import re
import subprocess
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("reproagent.execute")

DEFAULT_PROFILE = "test,docker"


@dataclass
class RunResult:
    exit_code: int
    log_tail: list[str] = field(default_factory=list)
    outdir: str = ""


def _run_capture(cmd: list[str], pattern: str) -> str | None:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("could not probe %s: %s", cmd[0], exc)
        return None
    m = re.search(pattern, proc.stdout + proc.stderr)
    if not m:
        log.warning("%s output did not match %r", cmd[0], pattern)
        return None
    return m.group(1)


def nextflow_version() -> str | None:
    return _run_capture(["nextflow", "-version"], r"nextflow version (\S+)")


def docker_version() -> str | None:
    return _run_capture(["docker", "version", "--format", "{{.Server.Version}}"], r"(\S+)")


def resolve_revision(repo: str, revision: str) -> str | None:
    """Resolve an nf-core release tag to its immutable Git commit."""
    url = f"https://github.com/{repo}.git"
    return _run_capture(
        ["git", "ls-remote", url, f"refs/tags/{revision}^{{}}"], r"^([0-9a-f]{40})"
    ) or _run_capture(["git", "ls-remote", url, f"refs/tags/{revision}"], r"^([0-9a-f]{40})")


def docker_digest(image: str) -> str | None:
    value = _run_capture(
        ["docker", "image", "inspect", image, "--format", '{{join .RepoDigests "\\n"}}'],
        r"@((?:sha256:)[0-9a-f]{64})",
    )
    if not value:
        log.warning("could not resolve container digest for %s", image)
    return value


def run_nextflow(
    repo: str,
    revision: str | None,
    params_file: str | Path | None,
    outdir: str | Path,
    profile: str = DEFAULT_PROFILE,
    work_dir: str | Path | None = None,
    config_file: str | Path | None = None,
    extra_args: tuple[str, ...] = (),
) -> RunResult:
    cmd = ["nextflow", "run", repo]
    if revision:
        cmd += ["-revision", revision]
    if params_file:
        cmd += ["-params-file", str(params_file)]
    if config_file:
        cmd += ["-c", str(config_file)]
    cmd += ["-profile", profile, "--outdir", str(outdir)]
    provenance = Path(outdir) / "provenance"
    provenance.mkdir(parents=True, exist_ok=True)
    cmd += [
        "-with-trace",
        str(provenance / "trace.txt"),
        "-with-report",
        str(provenance / "report.html"),
        "-with-timeline",
        str(provenance / "timeline.html"),
        "-with-dag",
        str(provenance / "dag.html"),
    ]
    if work_dir:
        cmd += ["-work-dir", str(work_dir)]
    cmd += list(extra_args)

    log.info("launching: %s", " ".join(cmd))
    tail: deque[str] = deque(maxlen=200)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    except OSError as exc:
        log.error("failed to start nextflow: %s", exc)
        return RunResult(exit_code=127, log_tail=[f"spawn error: {exc}"], outdir=str(outdir))
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip()
        tail.append(line)
        log.info("nextflow: %s", line)
    code = proc.wait()
    log.info("nextflow finished with exit code %s", code)
    return RunResult(exit_code=code, log_tail=list(tail), outdir=str(outdir))


def parse_containers(outdir: str | Path) -> list[dict[str, str | None]]:
    outdir = Path(outdir)
    rows: list[dict[str, str | None]] = []
    seen: set[tuple[str | None, str | None]] = set()
    for trace in sorted(outdir.rglob("*trace*.txt")):
        try:
            with trace.open(newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh, delimiter="\t"):
                    img, proc_name = row.get("container"), row.get("process")
                    key = (proc_name, img)
                    if not img or key in seen:
                        continue
                    seen.add(key)
                    image, tag, digest = img, None, None
                    if "@sha256:" in img:
                        image, digest = img.split("@sha256:", 1)
                        digest = f"sha256:{digest}"
                    elif ":" in image:
                        image, tag = image.rsplit(":", 1)
                    if not digest:
                        digest = docker_digest(img)
                    rows.append(
                        {"process": proc_name, "image": image, "tag": tag, "digest": digest}
                    )
        except OSError as exc:
            log.warning("unreadable trace %s: %s", trace, exc)
    if not rows:
        log.warning("no container info found under %s; writing null digests", outdir)
    else:
        n_digests = sum(1 for r in rows if r["digest"])
        if not n_digests:
            log.warning("container images found but no sha256 digests; tags recorded instead")
    return rows
