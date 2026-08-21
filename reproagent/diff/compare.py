"""Walk two output trees and classify every file.

Statuses: identical | differs | only-in-A | only-in-B.
Likely causes for 'differs': timestamp-embedded | thread-scheduling
nondeterminism | version drift | agent-chose-differently.
Heuristics are explicitly labelled as such; cause is null when unknown.
"""

from __future__ import annotations

import difflib
import hashlib
import logging
import re
from pathlib import Path

from pydantic import BaseModel, Field

log = logging.getLogger("reproagent.diff")

SNIPPET_LINES = 20
_AGENT_CONTROL_FILES = {"manifest.json", "replay-manifest.json", "params.json", "agent_trace.json"}
_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")
_VER_RE = re.compile(r"(?<![A-Za-z])v?\d+\.\d+(?:\.\d+)?(?![.\d])")


class FileDiff(BaseModel):
    path: str
    status: str
    cause: str | None = None
    snippet: str | None = None


class TreeDiff(BaseModel):
    root_a: str
    root_b: str
    files: list[FileDiff] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_text_maybe(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def classify_cause(name: str, text_a: str | None, text_b: str | None) -> str | None:
    if name in _AGENT_CONTROL_FILES:
        return "agent-chose-differently"
    if text_a is None or text_b is None:
        return None
    if sorted(text_a.splitlines()) == sorted(text_b.splitlines()):
        return "thread-scheduling nondeterminism"
    ta = "\n".join(_TS_RE.findall(text_a))
    tb = "\n".join(_TS_RE.findall(text_b))
    if ta or tb:
        return "timestamp-embedded"
    va, vb = sorted(_VER_RE.findall(text_a)), sorted(_VER_RE.findall(text_b))
    if va != vb and set(va) & set(vb):
        return "version drift"
    return None


def _snippet(a: Path, b: Path) -> str | None:
    ta, tb = read_text_maybe(a), read_text_maybe(b)
    if ta is None or tb is None:
        return None
    lines = list(
        difflib.unified_diff(ta.splitlines(), tb.splitlines(), fromfile="a/" + a.name, tofile="b/" + b.name, lineterm="")
    )
    return "\n".join(lines[:SNIPPET_LINES]) if lines else None


def compare_trees(root_a: str | Path, root_b: str | Path) -> TreeDiff:
    ra, rb = Path(root_a), Path(root_b)
    if not ra.is_dir() or not rb.is_dir():
        raise NotADirectoryError(f"both roots must exist: {ra}, {rb}")
    rels = {p.relative_to(ra).as_posix() for p in ra.rglob("*") if p.is_file()}
    rels |= {p.relative_to(rb).as_posix() for p in rb.rglob("*") if p.is_file()}
    out: list[FileDiff] = []
    for rel in sorted(rels):
        pa, pb = ra / rel, rb / rel
        name = Path(rel).name
        if not pa.is_file():
            out.append(FileDiff(path=rel, status="only-in-B"))
        elif not pb.is_file():
            out.append(FileDiff(path=rel, status="only-in-A"))
        elif sha256_file(pa) == sha256_file(pb):
            out.append(FileDiff(path=rel, status="identical"))
        else:
            ta, tb = read_text_maybe(pa), read_text_maybe(pb)
            out.append(
                FileDiff(
                    path=rel,
                    status="differs",
                    cause=classify_cause(name, ta, tb),
                    snippet=_snippet(pa, pb),
                )
            )
    summary = {"identical": 0, "differs": 0, "only-in-A": 0, "only-in-B": 0}
    for f in out:
        summary[f.status] += 1
    log.info("tree diff complete: %s vs %s -> %s", ra, rb, summary)
    return TreeDiff(root_a=str(ra), root_b=str(rb), files=out, summary=summary)


def to_markdown(report: TreeDiff) -> str:
    lines = [
        "# ReproAgent diff report",
        "",
        f"- A: `{report.root_a}`",
        f"- B: `{report.root_b}`",
        f"- Summary: {report.summary}",
        "",
        "| file | status | likely cause |",
        "|---|---|---|",
    ]
    for f in report.files:
        lines.append(f"| `{f.path}` | {f.status} | {f.cause or ''} |")
    for f in report.files:
        if f.snippet:
            lines += ["", f"## `{f.path}`", "", "```diff", f.snippet, "```"]
    return "\n".join(lines) + "\n"
