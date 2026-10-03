import hashlib
import hmac
import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from codewarden.llm.rules import RulesLLM  # noqa: E402
from codewarden.qa import answer_question  # noqa: E402
from codewarden.rag import build_retriever  # noqa: E402
from codewarden.config import RagConfig  # noqa: E402
from codewarden.server import create_app, verify_signature  # noqa: E402
from codewarden.services import Engine, PR_URL_RE, UserError  # noqa: E402
from codewarden.store import Store  # noqa: E402
from codewarden.testgen import generate_tests  # noqa: E402

ROOT = Path(__file__).parent.parent


@pytest.fixture
def engine(tmp_path):
    return Engine(Store(tmp_path / "t.db"), ROOT / "demo/shop", None, ROOT / "eval/cases", ROOT / "demo/prs")


@pytest.fixture
def client(engine):
    return TestClient(create_app(engine, allowed_hosts={"testserver"}))


def test_health_and_providers(client):
    assert client.get("/api/health").json()["ok"] is True
    ids = [p["id"] for p in client.get("/api/providers").json()]
    assert ids == ["rules", "gemini", "ollama"]


def test_static_dashboard_is_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "CodeWarden" in r.text
    assert client.get("/app.js").status_code == 200


def test_review_sample_roundtrip(client):
    r = client.post("/api/reviews", json={"source": "sample", "sample": "checkout_feature", "provider": "rules", "rag": True})
    assert r.status_code == 200, r.text
    rv = r.json()
    assert rv["n_findings"] == 6 and rv["worst"] == "critical" and rv["rag"] is True
    assert "diff_text" not in rv and rv["files"][0]["hunks"]
    assert rv["result"]["context_used"]["app/checkout.py"], "RAG context should be recorded"
    assert "package-lock.json" in rv["result"]["files_skipped"]
    again = client.get(f"/api/reviews/{rv['id']}").json()
    assert again["n_findings"] == 6
    stats = client.get("/api/stats").json()
    assert stats["reviews"] == 1 and stats["by_severity"]["critical"] == 1
    assert client.delete(f"/api/reviews/{rv['id']}").status_code == 200
    assert client.get(f"/api/reviews/{rv['id']}").status_code == 404


def test_replacement_suggestions_only_on_added_lines(client):
    rv = client.post("/api/reviews", json={"source": "sample", "sample": "checkout_feature", "provider": "rules"}).json()
    fixes = {f["title"]: f for f in rv["result"]["findings"] if f["replacement"]}
    assert fixes["Likely off-by-one in loop bound"]["replacement"].strip() == "for i in range(len(items)):"
    assert fixes["Overly broad exception handler"]["replacement"].strip() == "except Exception:"


def test_pasted_diff_validation(client):
    assert client.post("/api/reviews", json={"source": "diff", "diff": "  ", "provider": "rules"}).status_code == 400
    big = "x" * 2_100_000
    r = client.post("/api/reviews", json={"source": "diff", "diff": big, "provider": "rules"})
    assert r.status_code == 400 and "2 MB" in r.json()["error"]
    assert client.post("/api/reviews", json={"source": "bogus"}).status_code == 422


def test_unknown_or_unavailable_provider_is_a_clean_400(client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    r = client.post("/api/reviews", json={"source": "sample", "sample": "off_by_one", "provider": "gemini"})
    assert r.status_code == 400 and "GEMINI_API_KEY" in r.json()["error"]
    r = client.post("/api/reviews", json={"source": "sample", "sample": "off_by_one", "provider": "skynet"})
    assert r.status_code == 400


def test_sample_ids_cannot_escape_the_directory(client):
    r = client.post("/api/reviews", json={"source": "sample", "sample": "../../pyproject", "provider": "rules"})
    assert r.status_code == 400 and "Unknown sample" in r.json()["error"]


def test_pr_url_validation(client):
    assert PR_URL_RE.match("https://github.com/o/r/pull/12")
    for bad in ["http://github.com/o/r/pull/1", "https://evil.com/o/r/pull/1", "https://github.com/o/r/issues/1",
                "https://github.com.evil.com/o/r/pull/1"]:
        assert not PR_URL_RE.match(bad), bad
    r = client.post("/api/reviews", json={"source": "pr", "pr_url": "https://evil.com/o/r/pull/1", "provider": "rules"})
    assert r.status_code == 400


def test_post_requires_a_real_pr_and_token(client, monkeypatch):
    rv = client.post("/api/reviews", json={"source": "sample", "sample": "off_by_one", "provider": "rules"}).json()
    r = client.post(f"/api/reviews/{rv['id']}/post")
    assert r.status_code == 400 and "pull request" in r.json()["error"]


def test_tests_endpoint_and_unknown_file(client):
    rv = client.post("/api/reviews", json={"source": "sample", "sample": "checkout_feature", "provider": "rules"}).json()
    ok = client.post(f"/api/reviews/{rv['id']}/tests", json={"path": "app/checkout.py", "provider": "rules"}).json()
    assert "def test_apply_coupon_happy_path" in ok["code"] and ok["filename"] == "tests/test_checkout.py"
    assert client.post(f"/api/reviews/{rv['id']}/tests", json={"path": "nope.py", "provider": "rules"}).status_code == 400


def test_search_and_ask_use_the_repo_index(client):
    hits = client.get("/api/search", params={"q": "verify the user is logged in require_login"}).json()
    assert hits["chunks"] > 0 and "app/auth.py" in [r["path"] for r in hits["results"][:3]]
    ans = client.post("/api/ask", json={"question": "how do I run a query safely?", "provider": "rules"}).json()
    assert "app/db.py" in [s["path"] for s in ans["sources"]] and "Offline mode" in ans["answer"]
    assert client.post("/api/ask", json={"question": " ", "provider": "rules"}).status_code == 400


def test_eval_endpoint_persists_runs(client):
    run = client.post("/api/eval", json={"provider": "rules"}).json()
    assert 0.8 <= run["precision"] <= 0.9 and 0.5 <= run["recall"] <= 0.7
    assert len(client.get("/api/eval").json()) == 1


def test_demo_seed_and_clear(client):
    assert client.post("/api/demo/seed").json()["reviews"] == 3
    assert client.get("/api/stats").json()["reviews"] == 3
    assert client.post("/api/demo/seed").json()["reviews"] == 3  # idempotent
    assert client.get("/api/stats").json()["reviews"] == 3
    client.delete("/api/demo")
    assert client.get("/api/stats").json()["reviews"] == 0


def test_dns_rebinding_host_is_rejected(engine):
    c = TestClient(create_app(engine))  # default: loopback names only
    assert c.get("/api/health", headers={"Host": "evil.example.com"}).status_code == 403
    assert c.get("/api/health", headers={"Host": "127.0.0.1:8765"}).status_code == 200
    assert c.get("/api/health", headers={"Host": "localhost"}).status_code == 200
    assert c.get("/api/health", headers={"Host": "[::1]:8765"}).status_code == 200


def test_dashboard_token_protects_the_api(engine):
    c = TestClient(create_app(engine, dashboard_token="s3cret"))
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/stats").status_code == 401
    assert c.get("/api/stats", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert c.get("/api/stats", headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_unexpected_errors_do_not_leak_details(engine, monkeypatch):
    c = TestClient(create_app(engine, allowed_hosts={"testserver"}), raise_server_exceptions=False)
    monkeypatch.setattr(engine.store, "stats", lambda: 1 / 0)
    r = c.get("/api/stats")
    assert r.status_code == 500 and "division" not in r.text


def _sign(secret, body):
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_webhook_signature_check():
    body = b'{"a":1}'
    assert verify_signature("k", body, _sign("k", body))
    assert not verify_signature("k", body, _sign("other", body))
    assert not verify_signature("k", body, None) and not verify_signature("k", body, "sha1=abc")


def test_webhook_flow(client, monkeypatch):
    body = json.dumps({"action": "opened", "pull_request": {"number": 3, "draft": False},
                       "repository": {"full_name": "o/r"}}).encode()
    assert client.post("/webhook/github", content=body).status_code == 503  # no secret configured
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "k")
    calls = []
    monkeypatch.setattr("codewarden.server._review_webhook_pr", lambda e, repo, n: calls.append((repo, n)))
    h = {"X-Hub-Signature-256": _sign("k", body), "X-GitHub-Event": "pull_request"}
    assert client.post("/webhook/github", content=body, headers={**h, "X-Hub-Signature-256": "sha256=bad"}).status_code == 401
    assert client.post("/webhook/github", content=body, headers=h).json()["queued"] == "o/r#3"
    assert calls == [("o/r", 3)]
    ping = client.post("/webhook/github", content=body, headers={**h, "X-GitHub-Event": "ping"})
    assert ping.json()["pong"] is True
    closed = json.dumps({"action": "closed", "pull_request": {"number": 3}, "repository": {"full_name": "o/r"}}).encode()
    r = client.post("/webhook/github", content=closed, headers={"X-Hub-Signature-256": _sign("k", closed), "X-GitHub-Event": "pull_request"})
    assert "ignored" in r.json() and len(calls) == 1


def test_store_stats_and_cascade(tmp_path, cfg):
    from codewarden.review import review_diff
    from tests.conftest import StubLLM
    s = Store(tmp_path / "s.db")
    res = review_diff((ROOT / "eval/cases/sql_injection.diff").read_text(), cfg, RulesLLM())
    rid = s.add_review(source="diff", title="t", provider="rules", model="", rag=False, diff_text="d", result=res)
    assert s.list_reviews()[0]["by_severity"]["critical"] == 1
    assert s.stats()["hot_files"][0]["path"] == "app/users.py"
    s.delete_review(rid)
    assert s.stats()["findings"] == 0


def test_testgen_skips_files_without_functions():
    diff = "diff --git a/c.py b/c.py\n--- a/c.py\n+++ b/c.py\n@@ -0,0 +1 @@\n+X = 1\n"
    out = generate_tests(diff, "c.py", RulesLLM())
    assert out["code"] == "" and "No testable" in out["note"]


def test_qa_with_empty_index_and_llm_error():
    from codewarden.llm.base import LLMError
    assert answer_question("q", None, RulesLLM())["sources"] == []

    class Boom:
        def complete(self, s, u):
            raise LLMError("quota")
    r = build_retriever(ROOT / "demo/shop", RagConfig())
    out = answer_question("database query", r, Boom())
    assert out["error"] == "quota" and out["sources"]


def test_langchain_chunker_splits_on_code_structure_with_correct_lines():
    pytest.importorskip("langchain_text_splitters")
    from codewarden.rag.lc import chunk_text_langchain
    src = "\n".join(f"def f{i}(x):\n    return x + {i}\n" for i in range(60))
    chunks = chunk_text_langchain("m.py", src, chunk_chars=300, overlap_chars=0)
    assert len(chunks) > 3
    lines = src.splitlines()
    for c in chunks:
        assert lines[c.start - 1].strip() and c.text.splitlines()[0].strip() == lines[c.start - 1].strip()
    r = build_retriever(ROOT / "demo/shop", RagConfig(chunker="langchain"))
    assert "app/auth.py" in [c.path for c in r.search("sanitize filename", k=3)]


def test_langchain_retriever_adapter():
    pytest.importorskip("langchain_core")
    from codewarden.rag.lc import as_langchain_retriever
    docs = as_langchain_retriever(build_retriever(ROOT / "demo/shop", RagConfig()), k=2).invoke("run_query sanctioned database")
    assert len(docs) == 2 and docs[0].metadata["path"] == "app/db.py"
