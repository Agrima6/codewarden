from codewarden.diff import parse_diff


def test_parses_files_and_line_numbers(sample_diff):
    files = parse_diff(sample_diff)
    assert [f.path for f in files] == ["app/db.py", "package-lock.json"]
    db = files[0]
    assert len(db.hunks) == 2
    added = db.added_lines()
    assert added[13].startswith("def find(")
    assert 14 in added and "SELECT" in added[14]
    # second hunk starts at new line 32; context line is 32, '+' lines 33 and 34
    assert db.line_text(33).strip() == "b = 3"
    assert 33 in db.commentable_lines() and 34 in db.commentable_lines()


def test_deleted_lines_have_no_new_number(sample_diff):
    db = parse_diff(sample_diff)[0]
    deleted = [ln for h in db.hunks for ln in h.lines if ln.kind == "-"]
    assert len(deleted) == 1 and deleted[0].new_no is None


def test_deleted_line_that_looks_like_a_file_header_is_not_misparsed():
    diff = (
        "diff --git a/a.sql b/a.sql\n--- a/a.sql\n+++ b/a.sql\n@@ -1,2 +1,2 @@\n"
        "--- a comment\n+-- a new comment\n keep\n"
    )
    f = parse_diff(diff)[0]
    assert f.path == "a.sql"
    kinds = [ln.kind for ln in f.hunks[0].lines]
    assert kinds == ["-", "+", " "]


def test_new_deleted_and_binary_flags():
    diff = (
        "diff --git a/n.py b/n.py\nnew file mode 100644\n--- /dev/null\n+++ b/n.py\n@@ -0,0 +1 @@\n+x = 1\n"
        "diff --git a/old.py b/old.py\ndeleted file mode 100644\n--- a/old.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-y = 2\n"
        "diff --git a/i.png b/i.png\nBinary files a/i.png and b/i.png differ\n"
    )
    new, old, img = parse_diff(diff)
    assert new.is_new and new.added_lines() == {1: "x = 1"}
    assert old.is_deleted and old.path == "old.py"
    assert img.is_binary


def test_hunk_render_uses_new_file_numbers(sample_diff):
    rendered = parse_diff(sample_diff)[0].hunks[0].render()
    assert "   13 + def find(conn, name):" in rendered


def test_wrong_hunk_counts_do_not_swallow_the_next_file():
    diff = (
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1,9 +1,9 @@\n-x\n+y\n"
        "diff --git a/b.py b/b.py\n--- a/b.py\n+++ b/b.py\n@@ -1 +1 @@\n-p\n+q\n"
    )
    assert [f.path for f in parse_diff(diff)] == ["a.py", "b.py"]
