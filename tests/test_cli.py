import json
from unittest.mock import MagicMock

from codewarden import cli
from codewarden.config import Config
from codewarden.llm.rules import RulesLLM


def test_review_diff_file_text_output_and_fail_on(tmp_path, capsys, sample_diff, monkeypatch):
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "x.diff"
    d.write_text(sample_diff)
    code = cli.main(["review", "--diff-file", str(d), "--provider", "rules", "--no-rag"])
    out = capsys.readouterr().out
    assert code == 0 and "SQL built with string formatting" in out and "app/db.py:14" in out

    (tmp_path / ".codewarden.yml").write_text("fail_on: critical\n")
    assert cli.main(["review", "--diff-file", str(d), "--provider", "rules", "--no-rag"]) == 1


def test_review_json_format(tmp_path, capsys, sample_diff):
    d = tmp_path / "x.diff"
    d.write_text(sample_diff)
    cli.main(["review", "--diff-file", str(d), "--provider", "rules", "--no-rag", "--format", "json"])
    data = json.loads(capsys.readouterr().out)
    assert data[0]["path"] == "app/db.py" and len(data[0]["fingerprint"]) == 12


def test_missing_api_key_is_a_clean_error(tmp_path, capsys, monkeypatch, sample_diff):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    d = tmp_path / "x.diff"
    d.write_text(sample_diff)
    assert cli.main(["review", "--diff-file", str(d), "--provider", "gemini"]) == 2
    assert "GEMINI_API_KEY" in capsys.readouterr().err


def _event(tmp_path, monkeypatch, name, payload):
    p = tmp_path / "event.json"
    p.write_text(json.dumps(payload))
    monkeypatch.setenv("GITHUB_EVENT_NAME", name)
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(p))
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))


def _fake_gh(monkeypatch, diff, seen=()):
    gh = MagicMock()
    gh.get_pr.return_value = {"title": "T", "body": "B", "head_sha": "abc", "draft": False}
    gh.get_diff.return_value = diff
    gh.existing_fingerprints.return_value = set(seen)
    gh.post_review.return_value = (1, 0)
    monkeypatch.setattr(cli, "GitHubClient", lambda token, repo: gh)
    return gh


def test_action_pull_request_posts_review(tmp_path, monkeypatch, sample_diff):
    monkeypatch.chdir(tmp_path)
    _event(tmp_path, monkeypatch, "pull_request",
           {"pull_request": {"number": 5, "head": {"repo": {"full_name": "o/r"}}}})
    gh = _fake_gh(monkeypatch, sample_diff)
    assert cli.main(["action", "--provider", "rules"]) == 0
    number, sha, summary, findings = gh.post_review.call_args.args
    assert (number, sha) == (5, "abc") and "CodeWarden review" in summary and findings


def test_action_posts_nothing_when_all_findings_already_reported(tmp_path, monkeypatch, sample_diff, cfg):
    from codewarden.review import review_diff
    monkeypatch.chdir(tmp_path)
    fps = {f.fingerprint for f in review_diff(sample_diff, cfg, RulesLLM()).findings}
    _event(tmp_path, monkeypatch, "pull_request",
           {"pull_request": {"number": 5, "head": {"repo": {"full_name": "o/r"}}}})
    gh = _fake_gh(monkeypatch, sample_diff, seen=fps)
    cli.main(["action", "--provider", "rules"])
    gh.post_review.assert_not_called()


def test_action_ignores_unrelated_comments(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _event(tmp_path, monkeypatch, "issue_comment",
           {"issue": {"number": 1, "pull_request": {}}, "comment": {"body": "looks good"}})
    gh = _fake_gh(monkeypatch, "")
    assert cli.main(["action", "--provider", "rules"]) == 0
    gh.get_pr.assert_not_called()


def test_action_skips_fork_pr_without_secret(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    _event(tmp_path, monkeypatch, "pull_request",
           {"pull_request": {"number": 5, "head": {"repo": {"full_name": "fork/r"}}}})
    assert cli.main(["action", "--provider", "gemini"]) == 0
    assert "Skipping review of fork PR" in capsys.readouterr().out
