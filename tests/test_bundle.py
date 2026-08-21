import pytest

from reproagent.diff.compare import sha256_file
from reproagent.manifest.schema import (
    HostEnv,
    InputFile,
    LLMInfo,
    PipelineInfo,
    RunManifest,
    dump_manifest,
)
from reproagent.runner.replay import replay_run


def test_replay_rejects_changed_bundled_input(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    sample = inputs / "sample.fq"
    sample.write_text("@r\nA\n+\n!\n")
    manifest = RunManifest(
        run_id="r",
        created_utc="2025-01-01T00:00:00Z",
        pipeline=PipelineInfo(name="nf-core/rnaseq", revision="1"),
        profile="test,docker",
        inputs=[InputFile(path="inputs/sample.fq", sha256=sha256_file(sample))],
        llm=LLMInfo(model="mock"),
        host_env=HostEnv(),
    )
    path = dump_manifest(manifest, tmp_path / "manifest.json")
    sample.write_text("changed")
    with pytest.raises(ValueError, match="checksum"):
        replay_run(path, tmp_path / "out", lambda **_: None)
