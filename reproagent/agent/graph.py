"""LangGraph state machine: registry -> inspect -> plan -> execute -> manifest."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from reproagent.agent import tools

log = logging.getLogger("reproagent.agent")


class AgentState(TypedDict, total=False):
    request: str
    outdir: str
    input_paths: list[str]
    registry: dict[str, Any]
    inspections: list[dict[str, Any]]
    plan: dict[str, Any]
    result: dict[str, Any]
    decisions: list[dict[str, Any]]
    model: str
    temperature: float


def _registry(s: AgentState) -> dict[str, Any]:
    registry = tools.list_pipelines()
    return {"registry": registry, "decisions": [{"tool": "list_pipelines", "output": registry}]}


def _inspect(s: AgentState) -> dict[str, Any]:
    paths = s.get("input_paths") or re.findall(
        r"(?:[A-Za-z]:)?[^\s'\"]+\.(?:fastq|fq)(?:\.gz)?", s["request"], re.I
    )
    values = [tools.inspect_input(p) for p in paths]
    return {
        "input_paths": paths,
        "inspections": values,
        "decisions": s["decisions"] + [{"tool": "inspect_input", "output": values}],
    }


def _plan(s: AgentState) -> dict[str, Any]:
    plan = tools.plan_run(s["request"], s.get("model", "rule-based-v1"), s.get("temperature", 0.0))
    if s.get("input_paths"):
        plan.params["input"] = (
            s["input_paths"][0] if len(s["input_paths"]) == 1 else s["input_paths"]
        )
    return {
        "plan": plan.model_dump(),
        "decisions": s["decisions"] + [{"tool": "plan_run", "output": plan.model_dump()}],
    }


def _execute(s: AgentState) -> dict[str, Any]:
    out = Path(s["outdir"])
    out.mkdir(parents=True, exist_ok=True)
    plan = tools.RunPlan.model_validate(s["plan"])
    plan.params["outdir"] = str(out)
    params_file = out / "params.json"
    params_file.write_text(json.dumps(plan.params, indent=2), encoding="utf-8")
    result = tools.execute(plan, out, params_file)
    payload = {"exit_code": result.exit_code, "outdir": result.outdir, "log_tail": result.log_tail}
    return {
        "plan": plan.model_dump(),
        "result": payload,
        "decisions": s["decisions"] + [{"tool": "execute", "output": payload}],
    }


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("list_pipelines", _registry)
    graph.add_node("inspect_input", _inspect)
    graph.add_node("plan_run", _plan)
    graph.add_node("execute", _execute)
    graph.add_edge(START, "list_pipelines")
    graph.add_edge("list_pipelines", "inspect_input")
    graph.add_edge("inspect_input", "plan_run")
    graph.add_edge("plan_run", "execute")
    graph.add_edge("execute", END)
    return graph.compile()


agent_graph = build_graph()
