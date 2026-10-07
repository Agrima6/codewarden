import json
import subprocess
import time
from pathlib import Path

import pytest

from codewarden.config import Config
from codewarden.experiment import ExperimentError, build_systems, load_suite, run_experiment, wilson
from codewarden.repos import RepoError, RepoManager, parse_repo_url, slug_for

ROOT = Path(__file__).parent.parent
EVAL = ROOT / "eval/cases"


def test_wilson_interval_matches_known_values():
    lo, hi = wilson(6, 10)
    assert 0.31 < lo < 0.32 and 0.83 < hi < 0.84
    assert wilson(0, 0) is None
    lo, hi = wilson(10, 10)
    assert hi == 1.0 and lo > 0.7


def test_build_systems_gives_each_model_an_ablation_pair():
    ids = [s.id for s in build_systems(["rules", "gemini", "ollama"], {"ollama": "m1"})]
    assert ids == ["rules", "gemini-diff", "gemini-rag", "ollama-diff", "ollama-rag"]
    assert [s.rag for s in build_systems(["gemini"])] == [False, True]


def test_baseline_experiment_is_deterministic_and_matches_the_eval_numbers():
    cfg = Config()
    res = run_experiment(systems=build_systems(["rules"]), repeats=2, eval_dir=EVAL, base_cfg=cfg)
    g, c = res["metrics"]["rules|general"], res["metrics"]["rules|context"]
    assert (g["matched"], g["expected"]) == (12, 20)  # 6 of 10 bugs, two repeats pooled
    assert g["false_positives"] == 2 and round(g["precision"], 2) == 0.86
    assert c["recall"] == 0.0 and c["f1"] == 0.0 and c["precision"] is None
    assert g["run_to_run"]["recall"][1] == 0.0  # no variance for a deterministic system
    assert res["suites"]["general"]["bugs"] == 10 and res["suites"]["context"]["bugs"] == 6
    assert res["config"]["dataset_hash"] and res["config"]["prompt_hash"]
    assert any(f["kind"] == "missed" and f["case"] == "path_traversal" for f in res["failures"])


class Oracle:
    """A perfect reviewer: flags exactly the planted line of the file under review."""

    def __init__(self, truth):
        self.truth, self.prompts = truth, []
        self.usage = {"prompt": 0, "output": 0}

    def complete(self, system, user):
        self.prompts.append(user)
        self.usage["prompt"] += 10
        path = user.split("File under review: ")[1].splitlines()[0].strip()
        if path not in self.truth:
            return json.dumps({"findings": []})
        return json.dumps({"findings": [{"line": self.truth[path], "severity": "high", "category": "bug",
                                         "title": "planted", "explanation": "x", "confidence": 0.9}]})


def test_llm_systems_run_the_ablation_and_aggregate_correctly(monkeypatch):
    truth = {}
    for d in (EVAL, ROOT / "eval/context_cases"):
        for case in load_suite(d):
            for e in case["expected"]:
                truth[e["path"]] = e["lines"][0]
    oracle = Oracle(truth)
    monkeypatch.setattr("codewarden.experiment.get_llm", lambda cfg: oracle)
    cfg = Config()
    cfg.rag.backend = "bm25"
    res = run_experiment(systems=build_systems(["gemini"]), repeats=1, eval_dir=EVAL, base_cfg=cfg)
    m = res["metrics"]
    assert set(m) == {"gemini-diff|general", "gemini-diff|context", "gemini-rag|context"}, "RAG variant skips the general suite"
    for v in m.values():
        assert v["recall"] == 1.0 and v["precision"] == 1.0 and v["false_positives"] == 0
    assert m["gemini-diff|general"]["tokens_prompt"] == 120
    ctx_prompts = oracle.prompts[12:]
    assert not any("Related code from elsewhere" in p for p in ctx_prompts[:7]), "diff-only must not receive context"
    assert all("Related code from elsewhere" in p for p in ctx_prompts[7:14] if "File under review: app/" in p)
    assert res["failures"] == []


def test_any_provider_failure_aborts_instead_of_recording_garbage(monkeypatch):
    from codewarden.llm.base import LLMError

    class Down:
        def complete(self, s, u):
            raise LLMError("HTTP 429: quota", 429)

    monkeypatch.setattr("codewarden.experiment.get_llm", lambda cfg: Down())
    with pytest.raises(ExperimentError, match="quota"):
        run_experiment(systems=build_systems(["gemini"]), repeats=1, eval_dir=EVAL, base_cfg=Config())
    with pytest.raises(ExperimentError):
        run_experiment(systems=build_systems(["rules"]), repeats=0, eval_dir=EVAL, base_cfg=Config())


def test_repo_url_validation():
    assert parse_repo_url("https://github.com/octocat/Hello-World") == ("octocat", "Hello-World")
    assert parse_repo_url("https://github.com/o/r.git/") == ("o", "r")
    for bad in ["http://github.com/o/r", "https://evil.com/o/r", "file:///etc", "https://github.com/../r",
                "https://github.com/o/r/tree/main", "git@github.com:o/r.git", "", "https://github.com/o"]:
        with pytest.raises(RepoError):
            parse_repo_url(bad)


def test_repo_manager_lists_and_removes_and_blocks_bad_slugs(tmp_path):
    m = RepoManager(tmp_path)
    repo = tmp_path / slug_for("o", "r")
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=a@b.c", "-c", "user.name=t", "commit", "-qm", "first"], check=True)
    listed = m.list()
    assert listed[0]["slug"] == "o__r" and listed[0]["files"] == 1 and listed[0]["last_commit"] == "first"
    for bad in ["../x", "a/b", "..__..", "x"]:
        with pytest.raises(RepoError):
            m.path_for(bad)
    assert m.remove("o__r") is True and m.list() == []


def test_experiment_and_repo_api(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from codewarden.server import create_app
    from codewarden.services import Engine
    from codewarden.store import Store

    engine = Engine(Store(tmp_path / "t.db"), ROOT / "demo/shop", None, EVAL, ROOT / "demo/prs", repos_dir=tmp_path / "repos")
    c = TestClient(create_app(engine, allowed_hosts={"testserver"}))
    meta = c.get("/api/experiment/meta").json()
    assert meta["suites"]["general"]["cases"] == 12 and meta["calls_per_repeat_per_model"] == 26
    exp = c.post("/api/experiments", json={"providers": ["rules"], "repeats": 1}).json()
    for _ in range(100):
        got = c.get(f"/api/experiments/{exp['id']}").json()
        if got["status"] != "running":
            break
        time.sleep(0.1)
    assert got["status"] == "done" and got["results"]["metrics"]["rules|general"]["matched"] == 6
    assert c.post("/api/experiments", json={"providers": ["gemini"], "repeats": 1}).status_code in (200, 400)
    assert c.post("/api/experiments", json={"providers": ["rules"], "repeats": 9}).status_code == 422
    assert c.delete(f"/api/experiments/{exp['id']}").status_code == 200

    assert c.post("/api/repos", json={"url": "https://evil.com/o/r"}).status_code == 400
    assert c.post("/api/repos", json={"url": "file:///etc/passwd"}).status_code == 400
    assert c.delete("/api/repos/..%2f..%2fetc").status_code in (400, 404, 405)
    assert c.get("/api/repos/nope__nope/pulls").status_code == 400
    assert c.get("/api/repos").json()["connected"] == []
