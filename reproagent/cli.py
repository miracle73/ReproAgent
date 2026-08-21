"""Command-line interface."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import typer

from reproagent.agent.graph import agent_graph
from reproagent.diff.compare import compare_trees, to_markdown
from reproagent.manifest.capture import build_manifest, write_manifest
from reproagent.manifest.schema import (
    AgentDecisionTrace,
    InputFile,
    LLMInfo,
    new_run_id,
    utc_now_iso,
)
from reproagent.runner.replay import replay_run

app = typer.Typer(no_args_is_help=True)


def _logging() -> None:
    logging.basicConfig(level=logging.INFO, format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}')


@app.command()
def run(request: str, outdir: Path = typer.Option(...), input_path: list[Path] = typer.Option([], "--input"), model: str = typer.Option("rule-based-v1"), temperature: float = typer.Option(0.0)) -> None:
    """Select and run a pipeline, then write its provenance manifest."""
    _logging()
    state = agent_graph.invoke({"request": request, "outdir": str(outdir), "input_paths": [str(p) for p in input_path]})
    plan = state["plan"]
    inspections = state["inspections"]
    manifest = build_manifest(new_run_id(), utc_now_iso(), plan["pipeline"], plan["revision"], "test,docker", plan["params"], outdir, LLMInfo(model=model, temperature=temperature, prompt=request), AgentDecisionTrace(candidates_considered=plan["candidates"], choice=plan["pipeline"], reason=plan["reason"], steps=state["decisions"]), inputs=[InputFile(**{k: v for k, v in row.items() if k in InputFile.model_fields}) for row in inspections])
    path = write_manifest(manifest, outdir)
    typer.echo(json.dumps({"exit_code": state["result"]["exit_code"], "manifest": str(path)}))
    if state["result"]["exit_code"]:
        raise typer.Exit(state["result"]["exit_code"])


@app.command()
def replay(manifest: Path, outdir: Path = typer.Option(...)) -> None:
    _logging()
    typer.echo(replay_run(manifest, outdir).model_dump_json(indent=2))


@app.command("diff")
def diff_command(a: Path, b: Path, report: Path | None = typer.Option(None), json_report: Path | None = typer.Option(None, "--json")) -> None:
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
