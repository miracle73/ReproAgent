from reproagent.manifest.schema import HostEnv, LLMInfo, PipelineInfo, RunManifest, dump_manifest
from reproagent.runner.execute import RunResult
from reproagent.runner.replay import replay_run


def test_replay_uses_manifest_only(tmp_path):
    manifest = RunManifest(
        run_id="r1",
        created_utc="2025-01-01T00:00:00Z",
        pipeline=PipelineInfo(name="nf-core/sarek", revision="3.5.1"),
        profile="test,docker",
        params={"genome": "GRCh38"},
        llm=LLMInfo(model="mock"),
        host_env=HostEnv(),
    )
    path = dump_manifest(manifest, tmp_path / "manifest.json")
    calls = []

    def mocked(**kwargs):
        calls.append(kwargs)
        return RunResult(exit_code=0, outdir=str(kwargs["outdir"]))

    first = replay_run(path, tmp_path / "one", mocked)
    second = replay_run(path, tmp_path / "two", mocked)
    assert first.exit_code == second.exit_code == 0
    assert calls[0]["revision"] == calls[1]["revision"] == "3.5.1"
    assert calls[0]["profile"] == calls[1]["profile"] == "test,docker"
