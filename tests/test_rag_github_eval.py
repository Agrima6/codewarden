from pathlib import Path
from unittest.mock import MagicMock

import pytest

from codewarden.config import Config, RagConfig
from codewarden.evaluate import run_eval, summarize
from codewarden.github import GitHubClient, GitHubError
from codewarden.llm.base import LLMError, post_json
from codewarden.llm.rules import RulesLLM
from codewarden.models import Finding
from codewarden.rag import build_retriever
from codewarden.rag.chunker import chunk_text, tokenize
from codewarden.report import MARKER_RE, render_comment, render_summary
from codewarden.models import ReviewResult


def test_tokenize_splits_identifiers():
    toks = tokenize("def getUserById(user_id): return fetch_all_orders")
    assert {"get", "user", "getuserbyid", "fetch", "orders"} <= set(toks)


def test_chunking_overlap_and_ranges():
    text = "\n".join(f"line {i}" for i in range(1, 101))
    chunks = chunk_text("a.py", text, size=40, overlap=8)
    assert chunks[0].start == 1 and chunks[0].end == 40
    assert chunks[1].start == 33
    assert chunks[-1].end == 100


def test_bm25_retrieves_relevant_chunk(tmp_path):
    (tmp_path / "auth.py").write_text("def verify_password(user, password):\n    return check_hash(user.password_hash, password)\n")
    (tmp_path / "billing.py").write_text("def compute_invoice_total(items):\n    return sum(i.price for i in items)\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "junk.js").write_text("verify_password verify_password")
    r = build_retriever(tmp_path, RagConfig())
    hits = r.search("verify password hash check", k=2)
    assert hits[0].path == "auth.py"
    assert all("node_modules" not in h.path for h in r.chunks)
    assert r.search("zzzz qqqq") == []


def test_build_retriever_disabled_or_empty(tmp_path):
    assert build_retriever(tmp_path, RagConfig(enabled=False)) is None
    assert build_retriever(tmp_path, RagConfig()) is None


def test_post_json_retries_then_raises(monkeypatch):
    calls = []

    def fake_post(url, **kw):
        calls.append(1)
        m = MagicMock(status_code=503, text="busy")
        return m
    monkeypatch.setattr("codewarden.llm.base.requests.post", fake_post)
    monkeypatch.setattr("codewarden.llm.base.time.sleep", lambda s: None)
    with pytest.raises(LLMError):
        post_json("http://x", {}, retries=2)
    assert len(calls) == 3


def test_post_json_does_not_retry_client_errors(monkeypatch):
    calls = []
    monkeypatch.setattr("codewarden.llm.base.requests.post",
                        lambda url, **kw: calls.append(1) or MagicMock(status_code=400, text="bad key"))
    with pytest.raises(LLMError):
        post_json("http://x", {})
    assert len(calls) == 1


def _finding(anchored=True, line=14):
    return Finding("app/db.py", line, "high", "security", "SQL injection", "bad", "use params", 0.9,
                   "conn.execute(f...)", anchored)


def test_comment_contains_marker_and_marker_roundtrips():
    f = _finding()
    assert MARKER_RE.findall(render_comment(f)) == [f.fingerprint]


def test_summary_mentions_counts():
    s = render_summary(ReviewResult(findings=[_finding()], files_reviewed=["a"]))
    assert "1 finding" in s and "`app/db.py:14`" in s


def _client(responses):
    session = MagicMock()
    session.headers = {}
    session.request.side_effect = responses
    return GitHubClient("tok", "o/r", session), session


def _resp(status, payload=None, text=""):
    return MagicMock(status_code=status, json=lambda: payload, text=text)


def test_post_review_uses_line_and_side_not_position():
    gh, session = _client([_resp(200, {})])
    posted, moved = gh.post_review(7, "abc", "sum", [_finding()])
    assert (posted, moved) == (1, 0)
    body = session.request.call_args.kwargs["json"]
    assert body["commit_id"] == "abc" and body["event"] == "COMMENT"
    assert body["comments"][0]["line"] == 14 and body["comments"][0]["side"] == "RIGHT"
    assert "position" not in body["comments"][0]


def test_post_review_falls_back_per_comment_on_422():
    gh, session = _client([_resp(422, text="bad"), _resp(201), _resp(422), _resp(200)])
    posted, moved = gh.post_review(7, "abc", "sum", [_finding(line=14), _finding(line=99)])
    assert (posted, moved) == (1, 1)
    last_body = session.request.call_args.kwargs["json"]["body"]
    assert "Could not anchor inline" in last_body and "app/db.py:99" in last_body


def test_unanchored_findings_not_posted_inline():
    gh, session = _client([_resp(200, {})])
    gh.post_review(7, "abc", "sum", [_finding(anchored=False)])
    assert session.request.call_args.kwargs["json"]["comments"] == []


def test_existing_fingerprints_paginates():
    page1 = [{"body": f"x <!-- codewarden:{i:012x} -->"} for i in range(100)]
    page2 = [{"body": "<!-- codewarden:ffffffffffff -->"}]
    gh, _ = _client([_resp(200, page1), _resp(200, page2)])
    assert len(gh.existing_fingerprints(1)) == 101


def test_github_client_validates_inputs():
    with pytest.raises(GitHubError):
        GitHubClient("t", "not-a-repo")
    with pytest.raises(GitHubError):
        GitHubClient("", "o/r").post_review(1, "sha", "s", [])


def test_eval_scores_rules_baseline_on_seeded_cases():
    cases = Path(__file__).parent.parent / "eval/cases"
    cfg = Config()
    cfg.rag.enabled = False
    totals = summarize(run_eval(cases, cfg, RulesLLM()))
    assert totals["cases"] == 12
    # The baseline is a regex reviewer: good at pattern bugs, blind to logic/authorisation bugs, and it
    # raises one false alarm on the safe-but-scary trap case. Real models should beat this.
    assert 0.5 <= totals["recall"] <= 0.7
    assert 0.8 <= totals["precision"] < 1.0
    assert totals["false_positives"] == 1
