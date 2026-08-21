"""Pydantic manifest model. Every provenance field is nullable on purpose:

null means 'could not be captured' and is always accompanied by a warning at
capture time. Missing data is a finding, never silently invented.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

log = logging.getLogger("reproagent.manifest")

SCHEMA_VERSION = "1.0.0"


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_run_id() -> str:
    return uuid.uuid4().hex


class InputFile(BaseModel):
    path: str
    original_path: str | None = None
    sha256: str | None = None
    size_bytes: int | None = None
    read_count: int | None = None


class ReferenceGenome(BaseModel):
    id: str | None = None
    sha256: str | None = None


class ContainerInfo(BaseModel):
    process: str | None = None
    image: str | None = None
    tag: str | None = None
    digest: str | None = None


class PipelineInfo(BaseModel):
    name: str
    revision: str | None = None
    commit_sha: str | None = None


class AgentDecisionTrace(BaseModel):
    candidates_considered: list[str] = Field(default_factory=list)
    choice: str | None = None
    reason: str | None = None
    steps: list[dict[str, Any]] = Field(default_factory=list)


class LLMInfo(BaseModel):
    model: str
    version: str | None = None
    temperature: float | None = None
    prompt: str | None = None


class HostEnv(BaseModel):
    nextflow_version: str | None = None
    docker_version: str | None = None
    os: str | None = None
    cpu_count: int | None = None


class RunManifest(BaseModel):
    schema_version: str = SCHEMA_VERSION
    run_id: str
    created_utc: str
    pipeline: PipelineInfo
    profile: str
    containers: list[ContainerInfo] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)
    reference_genome: ReferenceGenome = Field(default_factory=ReferenceGenome)
    inputs: list[InputFile] = Field(default_factory=list)
    random_seeds: dict[str, int] | None = None
    agent_trace: AgentDecisionTrace = Field(default_factory=AgentDecisionTrace)
    llm: LLMInfo
    host_env: HostEnv


def validate_manifest(data: dict[str, Any]) -> RunManifest:
    m = RunManifest.model_validate(data)
    if m.schema_version != SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version {m.schema_version!r}")
    return m


def dump_manifest(manifest: RunManifest, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    revalidated = RunManifest.model_validate(manifest.model_dump(mode="json"))
    p.write_text(revalidated.model_dump_json(indent=2), encoding="utf-8")
    return p


def load_manifest(path: str | Path) -> RunManifest:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    try:
        return validate_manifest(raw)
    except (ValidationError, ValueError) as exc:
        log.error("manifest failed validation: %s", exc)
        raise
