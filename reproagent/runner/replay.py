"""Reconstruct a run from a manifest alone. No agent involvement.

Everything the replay needs comes from manifest.json: pinned revision,
resolved params, profile, input checksums.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import BaseModel

from reproagent.manifest.schema import InputFile, RunManifest, load_manifest
from reproagent.runner import execute as runner

log = logging.getLogger("reproagent.replay")


class ReplayResult(BaseModel):
    run_id: str
    replay_of: str
    exit_code: int
    outdir: str
    command: str


def verify_inputs(manifest: RunManifest, base_dir: Path | None = None) -> bool:
    ok = True
    for item in manifest.inputs:
        p = Path(item.path)
        if not p.is_absolute() and base_dir:
            p = base_dir / p
        if not p.is_file():
            log.warning("input missing at replay time: %s", item.path)
            ok = False
            continue
        if item.sha256 and not _checksum_matches(item, p):
            log.warning("input checksum mismatch: %s", item.path)
            ok = False
    return ok


def _checksum_matches(item: InputFile, path: Path | None = None) -> bool:
    from reproagent.diff.compare import sha256_file

    return sha256_file(path or Path(item.path)) == (item.sha256 or "")


def replay_run(
    manifest_path: str | Path,
    outdir: str | Path,
    runner_fn=runner.run_nextflow,
) -> ReplayResult:
    manifest = load_manifest(manifest_path)
    log.info(
        "replaying run %s (pipeline=%s revision=%s)",
        manifest.run_id,
        manifest.pipeline.name,
        manifest.pipeline.revision,
    )

    manifest_dir = Path(manifest_path).resolve().parent
    inputs_ok = verify_inputs(manifest, manifest_dir)
    if not inputs_ok:
        raise ValueError("manifest bundle inputs are missing or fail checksum validation")

    with TemporaryDirectory(prefix="reproagent-replay-") as tmp:
        params_file = Path(tmp) / "params.json"
        params = json.loads(json.dumps(manifest.params))
        replacements = {
            item.path: str((manifest_dir / item.path).resolve())
            for item in manifest.inputs
            if not Path(item.path).is_absolute()
        }

        def relocate(value):
            if isinstance(value, str):
                return replacements.get(value, value)
            if isinstance(value, list):
                return [relocate(v) for v in value]
            if isinstance(value, dict):
                return {k: relocate(v) for k, v in value.items()}
            return value

        params_file.write_text(json.dumps(relocate(params), indent=2), encoding="utf-8")
        config_file = Path(tmp) / "pinned-containers.config"
        pins = []
        for container in manifest.containers:
            if container.process and container.image and container.digest:
                process = container.process.replace("'", "\\'")
                image = f"{container.image}@{container.digest}".replace("'", "\\'")
                pins.append(f"  withName: '{process}' {{ container = '{image}' }}")
        config_file.write_text("process {\n" + "\n".join(pins) + "\n}\n", encoding="utf-8")
        if not pins:
            log.warning("manifest has no usable container digests; replay cannot pin containers")
        result = runner_fn(
            repo=manifest.pipeline.name,
            revision=manifest.pipeline.commit_sha or manifest.pipeline.revision,
            params_file=params_file,
            outdir=outdir,
            profile=manifest.profile,
            config_file=config_file,
        )
    cmd = (
        f"nextflow run {manifest.pipeline.name}"
        + (f" -revision {manifest.pipeline.revision}" if manifest.pipeline.revision else "")
        + f" -profile {manifest.profile}"
    )
    return ReplayResult(
        run_id=manifest.run_id + "-replay",
        replay_of=manifest.run_id,
        exit_code=result.exit_code,
        outdir=str(outdir),
        command=cmd,
    )
