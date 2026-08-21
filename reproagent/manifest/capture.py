"""Collect provenance during a run. Never invent values; warn + null instead."""

from __future__ import annotations

import logging
import os
import platform
from pathlib import Path
from typing import Any

from reproagent.diff.compare import sha256_file
from reproagent.manifest.schema import (
    AgentDecisionTrace,
    ContainerInfo,
    HostEnv,
    InputFile,
    LLMInfo,
    PipelineInfo,
    ReferenceGenome,
    RunManifest,
    dump_manifest,
)
from reproagent.runner import execute as runner

log = logging.getLogger("reproagent.capture")


def gather_host_env() -> HostEnv:
    return HostEnv(
        nextflow_version=runner.nextflow_version(),
        docker_version=runner.docker_version(),
        os=platform.platform(),
        cpu_count=os.cpu_count(),
    )


def collect_inputs(paths: list[str | Path]) -> list[InputFile]:
    inputs = []
    for raw in paths:
        p = Path(raw)
        if not p.is_file():
            log.warning("input path does not exist, recording nulls: %s", p)
            inputs.append(InputFile(path=str(p)))
            continue
        sha = None
        try:
            sha = sha256_file(p)
        except OSError as exc:
            log.warning("could not checksum %s: %s", p, exc)
        inputs.append(InputFile(path=str(p), sha256=sha, size_bytes=p.stat().st_size))
    return inputs


def build_manifest(
    run_id: str,
    created_utc: str,
    pipeline_name: str,
    revision: str | None,
    profile: str,
    params: dict[str, Any],
    outdir: str | Path,
    llm: LLMInfo,
    agent_trace: AgentDecisionTrace,
    inputs: list[InputFile] | None = None,
    reference_genome: ReferenceGenome | None = None,
    random_seeds: dict[str, int] | None = None,
    host_env: HostEnv | None = None,
    containers: list[ContainerInfo] | None = None,
    commit_sha: str | None = None,
) -> RunManifest:
    containers = containers or [ContainerInfo(**row) for row in runner.parse_containers(outdir)]
    host_env = host_env or gather_host_env()
    for field_name, value in [
        ("pipeline revision", revision),
        ("nextflow version", host_env.nextflow_version),
        ("docker version", host_env.docker_version),
        ("container digests", any(c.digest for c in containers)),
    ]:
        if not value:
            log.warning("provenance gap recorded as null/empty: %s", field_name)
    return RunManifest(
        schema_version="1.0.0",
        run_id=run_id,
        created_utc=created_utc,
        pipeline=PipelineInfo(name=pipeline_name, revision=revision, commit_sha=commit_sha),
        profile=profile,
        containers=containers,
        params=params,
        reference_genome=reference_genome or ReferenceGenome(),
        inputs=inputs or [],
        random_seeds=random_seeds,
        agent_trace=agent_trace,
        llm=llm,
        host_env=host_env,
    )


def write_manifest(manifest: RunManifest, outdir: str | Path) -> Path:
    return dump_manifest(manifest, Path(outdir) / "manifest.json")
