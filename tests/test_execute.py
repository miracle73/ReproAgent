import subprocess

import pytest

from reproagent.runner import execute

# Real `nextflow -version` banner: the word is letter-spaced and the version
# sits on its own line, so an anchored "nextflow version X" match never fires.
NEXTFLOW_BANNER = """
  N E X T F L O W
  version 24.04.4 build 5917
  created 01-08-2024 07:05 UTC (08:05 BST)
  cite doi:10.1038/nbt.3820
  http://nextflow.io
"""

LEGACY_BANNER = "NEXTFLOW version 23.04.0 build 5747\n"


def _fake_run(monkeypatch, stdout):
    def fake(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(execute.subprocess, "run", fake)


def test_nextflow_version_parses_letter_spaced_banner(monkeypatch):
    _fake_run(monkeypatch, NEXTFLOW_BANNER)
    assert execute.nextflow_version() == "24.04.4"


def test_nextflow_version_parses_single_line_banner(monkeypatch):
    _fake_run(monkeypatch, LEGACY_BANNER)
    assert execute.nextflow_version() == "23.04.0"


def test_nextflow_version_is_null_when_absent(monkeypatch):
    def boom(cmd, **kwargs):
        raise FileNotFoundError("nextflow")

    monkeypatch.setattr(execute.subprocess, "run", boom)
    assert execute.nextflow_version() is None


def _fake_ls_remote(monkeypatch, stdout):
    calls = []

    def fake(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(execute.subprocess, "run", fake)
    return calls


def test_resolve_revision_prefers_peeled_annotated_tag(monkeypatch):
    sha_tag = "1" * 40
    sha_peeled = "2" * 40
    calls = _fake_ls_remote(
        monkeypatch,
        f"{sha_tag}\trefs/tags/3.5.1\n{sha_peeled}\trefs/tags/3.5.1^{{}}\n",
    )
    assert execute.resolve_revision("nf-core/sarek", "3.5.1") == sha_peeled
    assert len(calls) == 1


def test_resolve_revision_falls_back_to_lightweight_tag(monkeypatch):
    sha_tag = "3" * 40
    _fake_ls_remote(monkeypatch, f"{sha_tag}\trefs/tags/3.5.1\n")
    assert execute.resolve_revision("nf-core/sarek", "3.5.1") == sha_tag


def test_resolve_revision_null_when_tag_absent(monkeypatch):
    _fake_ls_remote(monkeypatch, "")
    assert execute.resolve_revision("nf-core/sarek", "99.99.9") is None


@pytest.mark.parametrize(
    ("tag_line", "expected_tag", "expected_digest"),
    [
        ("NF_CORE_SAREK:STRELKA\tquay.io/biocontainers/strelka:2.4.10--h9ee0642_1", "2.4.10--h9ee0642_1", None),
        (
            "NF_CORE_SAREK:STRELKA\tquay.io/biocontainers/strelka@sha256:" + "a" * 64,
            None,
            "sha256:" + "a" * 64,
        ),
    ],
)
def test_parse_containers_splits_image_reference(
    tmp_path, monkeypatch, tag_line, expected_tag, expected_digest
):
    trace = tmp_path / "provenance" / "trace.txt"
    trace.parent.mkdir()
    trace.write_text(
        "task_id\thash\tprocess\tcontainer\n"
        f"1\tabc\tNF_CORE_SAREK:STRELKA\t{tag_line.split(chr(9))[1]}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(execute, "docker_digest", lambda image: None)
    rows = execute.parse_containers(tmp_path)
    assert rows == [
        {
            "process": "NF_CORE_SAREK:STRELKA",
            "image": "quay.io/biocontainers/strelka",
            "tag": expected_tag,
            "digest": expected_digest,
        }
    ]