import json
import subprocess

import pytest

from reproagent.agent import graph, tools
from reproagent.diff.compare import sha256_file
from reproagent.manifest.schema import (
    ConfigFile,
    ContainerInfo,
    HostEnv,
    InputFile,
    LLMInfo,
    PipelineInfo,
    RunManifest,
    dump_manifest,
)
from reproagent.runner.execute import RunResult, run_nextflow
from reproagent.runner.replay import replay_run


def _manifest_with_bundle(tmp_path, outdir_param, config_sha="auto"):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    sample = inputs / "sample.csv"
    sample.write_text("patient,sex,status,sample,lane,fastq_1\n")
    configs = tmp_path / "configs"
    configs.mkdir()
    host_config = configs / "host.config"
    host_config.write_text("process {\n  resourceLimits = [ cpus: 4, memory: '4.GB' ]\n}\n")
    if config_sha == "auto":
        config_sha = sha256_file(host_config)
    manifest = RunManifest(
        run_id="r1",
        created_utc="2025-01-01T00:00:00Z",
        pipeline=PipelineInfo(name="nf-core/sarek", revision="3.5.1", commit_sha="a" * 40),
        profile="test,docker",
        params={"input": "inputs/sample.csv", "outdir": outdir_param},
        containers=[
            ContainerInfo(
                process="NFCORE_SAREK:STRELKA",
                image="quay.io/biocontainers/strelka",
                digest="sha256:" + "b" * 64,
            )
        ],
        inputs=[InputFile(path="inputs/sample.csv", sha256=None)],
        configs=[ConfigFile(path="configs/host.config", sha256=config_sha)],
        llm=LLMInfo(model="mock"),
        host_env=HostEnv(),
    )
    return dump_manifest(manifest, tmp_path / "manifest.json")


def test_replay_never_writes_into_original_outdir(tmp_path):
    original = tmp_path / "r1"
    original.mkdir()
    path = _manifest_with_bundle(tmp_path, str(original))
    seen = {}

    def mocked(**kwargs):
        # The params file and generated config live in a temp dir that is
        # removed once replay_run returns, so snapshot them during the call.
        seen["params"] = pathlib_read(kwargs["params_file"])
        seen["outdir"] = kwargs["outdir"]
        return RunResult(exit_code=0, outdir=str(kwargs["outdir"]))

    replay_outdir = tmp_path / "r1_replay"
    replay_run(path, replay_outdir, mocked)
    params = json.loads(seen["params"])
    assert params["outdir"] == str(replay_outdir)
    assert params["input"] == str((tmp_path / "inputs" / "sample.csv").resolve())
    assert str(original) not in seen["params"]


def test_replay_replays_bundled_config_alongside_container_pins(tmp_path):
    path = _manifest_with_bundle(tmp_path, str(tmp_path / "r1"))
    seen = {}

    def mocked(**kwargs):
        configs = kwargs["config_file"]
        seen["count"] = len(configs)
        seen["bundled"] = configs[1]
        seen["pins"] = pathlib_read(configs[0])
        return RunResult(exit_code=0, outdir=str(kwargs["outdir"]))

    replay_run(path, tmp_path / "r1_replay", mocked)
    assert seen["count"] == 2
    assert seen["bundled"] == str((tmp_path / "configs" / "host.config").resolve())
    assert "quay.io/biocontainers/strelka@sha256:" + "b" * 64 in seen["pins"]


def test_replay_rejects_changed_bundled_config(tmp_path):
    path = _manifest_with_bundle(tmp_path, str(tmp_path / "r1"), config_sha="c" * 64)
    (tmp_path / "configs" / "host.config").write_text("process { resourceLimits = [ ] }\n")
    with pytest.raises(ValueError, match="configs are missing or fail checksum"):
        replay_run(path, tmp_path / "out", lambda **_: None)


def pathlib_read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def test_run_nextflow_emits_repeated_config_flags(tmp_path, monkeypatch):
    captured = {}

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            captured["cmd"] = cmd
            self.stdout = iter(())

        def wait(self):
            return 0

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    run_nextflow(
        "nf-core/sarek",
        "3.5.1",
        tmp_path / "params.json",
        tmp_path / "out",
        config_file=[tmp_path / "a.config", tmp_path / "b.config"],
    )
    cmd = captured["cmd"]
    assert cmd.count("-c") == 2
    assert cmd[cmd.index("-c") + 1].endswith("a.config")
    assert cmd[cmd.index("-c") + 3].endswith("b.config")


def test_agent_execute_forwards_bundled_configs(monkeypatch, tmp_path):
    seen = {}

    def fake_execute(plan, outdir, params_file, config_paths=()):
        seen["config_paths"] = list(config_paths)
        return RunResult(exit_code=0, outdir=str(outdir))

    monkeypatch.setattr(tools, "execute", fake_execute)
    plan = tools.RunPlan(pipeline="nf-core/sarek", revision="3.5.1", reason="r")
    state = {
        "outdir": str(tmp_path),
        "plan": plan.model_dump(),
        "decisions": [],
        "config_paths": [str(tmp_path / "configs" / "host.config")],
    }
    graph._execute(state)
    assert seen["config_paths"] == [str(tmp_path / "configs" / "host.config")]