"""Deterministic tools exposed to the agent."""

from __future__ import annotations

import gzip
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from reproagent.diff.compare import sha256_file
from reproagent.runner.execute import RunResult, run_nextflow

log = logging.getLogger("reproagent.tools")

PIPELINES = {
    "nf-core/rnaseq": {"description": "RNA sequencing expression analysis", "revision": "3.18.0"},
    "nf-core/sarek": {"description": "Germline and somatic variant calling", "revision": "3.5.1"},
    "nf-core/fetchngs": {"description": "Download public sequencing data", "revision": "1.12.0"},
}


class RunPlan(BaseModel):
    pipeline: str
    revision: str
    params: dict[str, Any] = Field(default_factory=dict)
    reason: str
    candidates: list[str] = Field(default_factory=list)


def list_pipelines() -> dict[str, dict[str, str]]:
    return PIPELINES.copy()


def inspect_input(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    result: dict[str, Any] = {"path": str(p), "file_type": None, "size_bytes": None, "sha256": None, "read_count": None}
    if not p.is_file():
        log.warning("cannot inspect missing input: %s", p)
        return result
    result.update(file_type="fastq" if p.name.lower().endswith((".fastq", ".fq", ".fastq.gz", ".fq.gz")) else p.suffix.lstrip(".") or "unknown", size_bytes=p.stat().st_size, sha256=sha256_file(p))
    if result["file_type"] == "fastq":
        opener = gzip.open if p.suffix.lower() == ".gz" else open
        try:
            with opener(p, "rt", encoding="utf-8", errors="replace") as fh:
                result["read_count"] = sum(1 for _ in fh) // 4
        except OSError as exc:
            log.warning("could not count FASTQ reads in %s: %s", p, exc)
    return result


def plan_run(request: str) -> RunPlan:
    lowered = request.lower()
    if any(word in lowered for word in ("variant", "sarek", "somatic", "germline")):
        choice, reason = "nf-core/sarek", "request asks for variant analysis"
    elif any(word in lowered for word in ("fetch", "download", "accession")):
        choice, reason = "nf-core/fetchngs", "request asks to retrieve sequencing data"
    else:
        choice, reason = "nf-core/rnaseq", "request most closely matches RNA-seq analysis"
    entry = PIPELINES[choice]
    return RunPlan(pipeline=choice, revision=entry["revision"], params={}, reason=reason, candidates=list(PIPELINES))


def execute(plan: RunPlan, outdir: str | Path, params_file: str | Path) -> RunResult:
    return run_nextflow(plan.pipeline, plan.revision, params_file, outdir)
