from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from dataclasses import fields
from pathlib import Path

import requests

from codewarden.config import Config
from codewarden.diff import parse_diff
from codewarden.evaluate import run_eval, summarize
from codewarden.github import GitHubClient, GitHubError
from codewarden.llm import LLMError, get_llm
from codewarden.models import Finding
from codewarden.qa import answer_question
from codewarden.rag import build_retriever
from codewarden.report import render_summary
from codewarden.review import review_diff
from codewarden.store import Store
from codewarden.testgen import generate_tests

MAX_DIFF_BYTES = 2_000_000
PR_URL_RE = re.compile(r"^https://github\.com/([\w.-]+)/([\w.-]+)/pull/(\d+)(?:[/?#].*)?$")
PROVIDERS = ("rules", "gemini", "ollama")


class UserError(ValueError):
    """Bad input from the dashboard user; safe to show verbatim."""


def _origin_slug(root: Path) -> str | None:
    try:
        url = subprocess.run(["git", "-C", str(root), "remote", "get-url", "origin"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?/?$", url)
    return m.group(1).lower() if m else None


class Engine:
    """Everything the dashboard and webhook do, independent of HTTP."""

    def __init__(self, store: Store, repo_root: str | Path = ".", config_path: str | None = None,
                 eval_dir: str | Path | None = None, demo_dir: str | Path | None = None):
        self.store = store
        self.repo_root = Path(repo_root).resolve()
        self.config_path = config_path
        self.eval_dir = Path(eval_dir) if eval_dir else None
        self.demo_dir = Path(demo_dir) if demo_dir else None
        self._retriever = None
        self._retriever_key = None
        self._built_at = 0.0
        self._lock = threading.Lock()

    def config(self, provider: str | None = None, model: str | None = None, rag: bool | None = None) -> Config:
        cfg = Config.load(self.config_path)
        if provider:
            if provider not in PROVIDERS:
                raise UserError(f"Unknown provider {provider!r}")
            cfg.provider = provider
            cfg.model = model or ""
        elif model:
            cfg.model = model
        if rag is not None:
            cfg.rag.enabled = rag
        cfg.validate()
        return cfg

    def retriever(self, cfg: Config):
        if not cfg.rag.enabled:
            return None
        key = (cfg.rag.backend, cfg.rag.chunker, cfg.rag.chunk_lines, cfg.rag.extensions.__len__())
        with self._lock:
            if self._retriever_key != key or self._retriever is None or time.time() - self._built_at > 120:
                getattr(self._retriever, "close", lambda: None)()
                self._retriever = build_retriever(self.repo_root, cfg.rag)
                self._retriever_key, self._built_at = key, time.time()
            return self._retriever

    def llm(self, cfg: Config):
        try:
            return get_llm(cfg)
        except LLMError as exc:
            raise UserError(str(exc)) from exc

    # ---- providers -------------------------------------------------------------------------
    def provider_status(self) -> list[dict]:
        out = [{"id": "rules", "label": "Rule-based baseline", "available": True, "models": [],
                "detail": "Offline, deterministic, no model"}]
        has_key = bool(os.environ.get("GEMINI_API_KEY"))
        out.append({"id": "gemini", "label": "Google Gemini", "available": has_key, "models": ["gemini-flash-latest", "gemini-3.8-flash", "gemini-2.5-pro"],
                    "detail": "API key found" if has_key else "Set GEMINI_API_KEY and restart the server"})
        host = (os.environ.get("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
        try:
            tags = requests.get(f"{host}/api/tags", timeout=0.7).json()
            models = [m["name"] for m in tags.get("models", [])]
            out.append({"id": "ollama", "label": "Ollama (local)", "available": bool(models), "models": models,
                        "detail": f"{len(models)} local model(s)" if models else "Running, but no models pulled"})
        except (requests.RequestException, ValueError, KeyError):
            out.append({"id": "ollama", "label": "Ollama (local)", "available": False, "models": [],
                        "detail": "Not running on " + host})
        return out

    # ---- reviews ---------------------------------------------------------------------------
    def review_text(self, diff: str, *, source: str, title: str, provider: str | None, model: str | None,
                    rag: bool | None, repo: str = "", pr_number: int | None = None, head_sha: str = "",
                    pr_body: str = "", seen: set[str] | None = None) -> dict:
        if not diff.strip():
            raise UserError("The diff is empty.")
        if len(diff.encode()) > MAX_DIFF_BYTES:
            raise UserError("The diff is larger than 2 MB. Review a smaller change.")
        cfg = self.config(provider, model, rag)
        llm = self.llm(cfg)
        result = review_diff(diff, cfg, llm, self.retriever(cfg), title, pr_body, seen)
        if result.requests and len(result.errors) >= result.requests:
            raise UserError(f"The {cfg.provider} request failed, so no review was produced. {result.errors[0]}")
        rid = self.store.add_review(source=source, title=title, provider=cfg.provider, model=cfg.resolved_model(),
                                    rag=cfg.rag.enabled, diff_text=diff, result=result, repo=repo,
                                    pr_number=pr_number, head_sha=head_sha)
        return self.hydrate(self.store.get_review(rid))

    @staticmethod
    def hydrate(rv: dict) -> dict:
        """Replace the raw diff text with a parsed structure the dashboard can render."""
        rv = dict(rv)
        rv["files"] = [f.to_dict() for f in parse_diff(rv.pop("diff_text", ""))]
        return rv

    def get_review(self, review_id: int) -> dict | None:
        rv = self.store.get_review(review_id)
        return self.hydrate(rv) if rv else None

    def review_pr_url(self, url: str, *, provider: str | None, model: str | None, rag: bool | None) -> dict:
        m = PR_URL_RE.match(url.strip())
        if not m:
            raise UserError("Enter a GitHub pull request URL like https://github.com/owner/repo/pull/123")
        owner, repo, number = m.group(1), m.group(2), int(m.group(3))
        gh = GitHubClient(os.environ.get("GITHUB_TOKEN", ""), f"{owner}/{repo}")
        try:
            pr = gh.get_pr(number)
            diff = gh.get_diff(number)
        except GitHubError as exc:
            raise UserError(f"{exc}. Private repositories need GITHUB_TOKEN set on the server.") from exc
        if rag is not False and _origin_slug(self.repo_root) != f"{owner}/{repo}".lower():
            rag = False  # the indexed checkout is a different repository, so its code would be misleading context
        return self.review_text(diff, source="pr", title=pr["title"] or f"{owner}/{repo}#{number}",
                                provider=provider, model=model, rag=rag, repo=f"{owner}/{repo}",
                                pr_number=number, head_sha=pr["head_sha"], pr_body=pr["body"])

    def post_to_github(self, review_id: int) -> dict:
        rv = self.store.get_review(review_id)
        if not rv:
            raise UserError("Review not found")
        if not rv["repo"] or not rv["pr_number"] or not rv["head_sha"]:
            raise UserError("Only reviews of a real pull request URL can be posted to GitHub.")
        token = os.environ.get("GITHUB_TOKEN", "")
        if not token:
            raise UserError("GITHUB_TOKEN is not set on the server, so posting is disabled.")
        names = {f.name for f in fields(Finding)}
        findings = [Finding(**{k: v for k, v in d.items() if k in names}) for d in rv["result"]["findings"]]
        if not findings:
            raise UserError("There are no findings to post.")
        from codewarden.models import ReviewResult
        shell = ReviewResult(findings=findings, files_reviewed=rv["result"]["files_reviewed"])
        try:
            gh = GitHubClient(token, rv["repo"])
            posted, moved = gh.post_review(rv["pr_number"], rv["head_sha"], render_summary(shell), findings)
        except GitHubError as exc:
            raise UserError(str(exc)) from exc
        self.store.mark_posted(review_id)
        return {"posted": posted, "moved_to_summary": moved}

    # ---- extras ----------------------------------------------------------------------------
    def tests_for(self, review_id: int, path: str, provider: str | None, model: str | None) -> dict:
        rv = self.store.get_review(review_id)
        if not rv:
            raise UserError("Review not found")
        cfg = self.config(provider, model, False)
        try:
            return generate_tests(rv["diff_text"], path, self.llm(cfg))
        except (ValueError, RuntimeError) as exc:
            raise UserError(str(exc)) from exc

    def ask(self, question: str, provider: str | None, model: str | None) -> dict:
        if not question.strip():
            raise UserError("Ask a question about the code.")
        cfg = self.config(provider, model, True)
        retriever = self.retriever(cfg)
        if retriever is None:
            raise UserError("No indexable source files were found in the repository root.")
        return answer_question(question, retriever, self.llm(cfg), k=max(cfg.rag.top_k, 5))

    def search(self, query: str, k: int = 6) -> dict:
        cfg = self.config(None, None, True)
        retriever = self.retriever(cfg)
        if retriever is None:
            return {"chunks": 0, "results": []}
        hits = retriever.search(query, k=k) if query.strip() else []
        return {"chunks": len(retriever.chunks),
                "results": [{"path": c.path, "start": c.start, "end": c.end, "text": c.text} for c in hits]}

    def _sample_dirs(self):
        return [("Sample pull requests", self.demo_dir), ("Seeded bug cases", self.eval_dir)]

    def samples(self) -> list[dict]:
        out = []
        for group, d in self._sample_dirs():
            if d and d.exists():
                for p in sorted(d.glob("*.diff")):
                    out.append({"id": p.stem, "group": group, "label": p.stem.replace("_", " ").capitalize()})
        return out

    def sample_diff(self, sample_id: str) -> str:
        if re.fullmatch(r"[\w-]+", sample_id):
            for _, d in self._sample_dirs():
                if d and (d / f"{sample_id}.diff").exists():
                    return (d / f"{sample_id}.diff").read_text()
        raise UserError("Unknown sample")

    def seed_demo(self) -> dict:
        """Run the offline reviewer over the bundled demo PRs so a fresh dashboard has real data."""
        if not self.demo_dir or not self.demo_dir.exists():
            raise UserError("No demo pull requests found (pass --demo-dir).")
        self.store.clear_reviews("demo")
        titles = {"checkout_feature": "Add checkout with coupons", "upload_endpoint": "Add file upload endpoint",
                  "small_refactor": "Tidy order helpers"}
        count = 0
        for p in sorted(self.demo_dir.glob("*.diff")):
            self.review_text(p.read_text(), source="demo", title=titles.get(p.stem, p.stem.replace("_", " ")),
                             provider="rules", model=None, rag=True, repo="acme/shop")
            count += 1
        if self.eval_dir and self.eval_dir.exists() and not self.store.list_evals(1):
            self.run_eval("rules", None)
        return {"reviews": count, "warnings": []}

    def clear_demo(self) -> None:
        self.store.clear_reviews("demo")

    def run_eval(self, provider: str, model: str | None) -> dict:
        if self.eval_dir is None or not self.eval_dir.exists():
            raise UserError("No evaluation cases are configured on this server (pass --eval-dir).")
        cfg = self.config(provider, model, False)
        scores = run_eval(self.eval_dir, cfg, self.llm(cfg))
        failed = [s.error for s in scores if s.error]
        if failed:
            raise UserError(f"Evaluation not recorded: {len(failed)} of {len(scores)} cases failed. {failed[0]}")
        t = summarize(scores)
        cases = [s.__dict__ for s in scores]
        eid = self.store.add_eval(cfg.provider, cfg.resolved_model(), t["precision"], t["recall"],
                                  t["false_positives"], cases)
        return next(e for e in self.store.list_evals(1) if e["id"] == eid)
