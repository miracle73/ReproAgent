from reproagent.manifest.schema import (
    HostEnv,
    LLMInfo,
    PipelineInfo,
    RunManifest,
    dump_manifest,
    load_manifest,
)


def test_schema_roundtrip(tmp_path):
    original = RunManifest(run_id="r1", created_utc="2025-01-01T00:00:00Z", pipeline=PipelineInfo(name="nf-core/rnaseq", revision="1"), profile="test,docker", llm=LLMInfo(model="mock"), host_env=HostEnv())
    assert load_manifest(dump_manifest(original, tmp_path / "manifest.json")) == original
