from reproagent.diff.compare import compare_trees


def test_diff_classifier(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (a / "same.txt").write_text("same")
    (b / "same.txt").write_text("same")
    (a / "changed.txt").write_text("one\ntwo\n")
    (b / "changed.txt").write_text("two\none\n")
    (a / "a.txt").write_text("a")
    (b / "b.txt").write_text("b")
    result = compare_trees(a, b)
    assert result.summary == {"identical": 1, "differs": 1, "only-in-A": 1, "only-in-B": 1}
    assert (
        next(x for x in result.files if x.path == "changed.txt").cause
        == "thread-scheduling nondeterminism"
    )
