"""Command-line interface."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

import typer

from reproagent.agent.graph import agent_graph
from reproagent.agent.tools import SYSTEM_PROMPT
from reproagent.diff.compare import compare_trees, to_markdown
from reproagent.manifest.capture import build_manifest, write_manifest
from reproagent.manifest.schema import (
    AgentDecisionTrace,
    InputFile,
    LLMInfo,
    new_run_id,
    utc_now_iso,
)
from reproagent.runner.execute import resolve_revision
from reproagent.runner.replay import replay_run

app = typer.Typer(no_args_is_help=True)


def _logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
    )


@app.command()
def run(
    request: str,
    outdir: Path = typer.Option(...),
    input_path: list[Path] = typer.Option([], "--input"),
    model: str = typer.Option("rule-based-v1"),
    temperature: float = typer.Option(0.0),
) -> None:
    """Select and run a pipeline, then write its provenance manifest."""
    _logging()
    outdir.mkdir(parents=True, exist_ok=True)
    bundled: list[tuple[Path, Path]] = []
    for source in input_path:
        if not source.is_file():
            raise typer.BadParameter(f"input does not exist: {source}")
        target = outdir / "inputs" / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        bundled.append((source, target))
    state = agent_graph.invoke(
        {
            "request": request,
            "outdir": str(outdir),
            "input_paths": [str(p.resolve()) for _, p in bundled],
            "model": model,
            "temperature": temperature,
        }
    )
    plan = state["plan"]
    inspections = state["inspections"]
    manifest_params = json.loads(json.dumps(plan["params"]))
    manifest_inputs = []
    for (source, target), row in zip(bundled, inspections, strict=True):
        relative = target.relative_to(outdir).as_posix()
        manifest_inputs.append(
            InputFile(
                path=relative,
                original_path=str(source.resolve()),
                sha256=row["sha256"],
                size_bytes=row["size_bytes"],
                read_count=row["read_count"],
            )
        )
        absolute = str(target.resolve())
        if manifest_params.get("input") == absolute:
            manifest_params["input"] = relative
        elif isinstance(manifest_params.get("input"), list):
            manifest_params["input"] = [
                relative if value == absolute else value for value in manifest_params["input"]
            ]
    commit_sha = resolve_revision(plan["pipeline"], plan["revision"])
    manifest = build_manifest(
        new_run_id(),
        utc_now_iso(),
        plan["pipeline"],
        plan["revision"],
        "test,docker",
        manifest_params,
        outdir,
        LLMInfo(model=model, temperature=temperature, prompt=f"{SYSTEM_PROMPT}\n\nUser: {request}"),
        AgentDecisionTrace(
            candidates_considered=plan["candidates"],
            choice=plan["pipeline"],
            reason=plan["reason"],
            steps=state["decisions"],
        ),
        inputs=manifest_inputs,
        commit_sha=commit_sha,
    )
    path = write_manifest(manifest, outdir)
    typer.echo(json.dumps({"exit_code": state["result"]["exit_code"], "manifest": str(path)}))
    if state["result"]["exit_code"]:
        raise typer.Exit(state["result"]["exit_code"])


@app.command()
def replay(manifest: Path, outdir: Path = typer.Option(...)) -> None:
    _logging()
    typer.echo(replay_run(manifest, outdir).model_dump_json(indent=2))


@app.command("diff")
def diff_command(
    a: Path,
    b: Path,
    report: Path | None = typer.Option(None),
    json_report: Path | None = typer.Option(None, "--json"),
) -> None:
    _logging()
    result = compare_trees(a, b)
    markdown = to_markdown(result)
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(markdown, encoding="utf-8")
        json_path = json_report or report.with_suffix(".json")
        json_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    typer.echo(markdown)


@app.command()
def report(a: Path, b: Path, output: Path = typer.Option(...)) -> None:
    """Write paired Markdown and JSON diff reports."""
    diff_command(a, b, output, output.with_suffix(".json"))


if __name__ == "__main__":
    app()
