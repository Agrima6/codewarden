from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from codewarden import __version__
from codewarden.github import GitHubClient, GitHubError
from codewarden.services import Engine, UserError
from codewarden.store import Store

log = logging.getLogger("codewarden.server")
WEB_DIR = Path(__file__).parent / "web"
WEBHOOK_ACTIONS = {"opened", "synchronize", "reopened", "ready_for_review"}


class ReviewIn(BaseModel):
    source: str = Field(pattern="^(diff|pr|sample)$")
    diff: str = ""
    pr_url: str = ""
    sample: str = ""
    title: str = Field(default="", max_length=200)
    provider: str | None = None
    model: str | None = None
    rag: bool | None = None
    repo: str | None = Field(default=None, max_length=200)


class EvalIn(BaseModel):
    provider: str
    model: str | None = None


class ExperimentIn(BaseModel):
    providers: list[str] = Field(min_length=1, max_length=3)
    repeats: int = Field(default=1, ge=1, le=5)


class RepoIn(BaseModel):
    url: str = Field(max_length=300)


class TestsIn(BaseModel):
    path: str
    provider: str | None = None
    model: str | None = None


class AskIn(BaseModel):
    question: str = Field(max_length=1000)
    repo: str | None = Field(default=None, max_length=200)
    provider: str | None = None
    model: str | None = None


def _hostname(host_header: str) -> str:
    if host_header.startswith("["):  # IPv6 literal such as [::1]:8765
        return host_header.split("]")[0] + "]"
    return host_header.split(":")[0]


def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


def create_app(engine: Engine, dashboard_token: str | None = None, allowed_hosts: set[str] | None = None) -> FastAPI:
    app = FastAPI(title="CodeWarden", version=__version__, docs_url="/api/docs", redoc_url=None)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        # Without a token the dashboard trusts "being on localhost". Checking Host stops DNS-rebinding pages
        # from reaching it through the browser.
        if not dashboard_token:
            if _hostname(request.headers.get("host", "")) not in (allowed_hosts or LOOPBACK_HOSTS):
                return JSONResponse({"error": "Host not allowed"}, status_code=403)
        if dashboard_token and request.url.path.startswith("/api/") and request.url.path != "/api/health":
            supplied = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
            if not secrets.compare_digest(supplied, dashboard_token):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
        response = await call_next(request)
        if not request.url.path.startswith(("/api/", "/webhook/")):
            response.headers["Cache-Control"] = "no-cache"  # always pick up the current dashboard code
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.exception_handler(UserError)
    async def user_error(_: Request, exc: UserError):
        return JSONResponse({"error": str(exc)}, status_code=400)

    @app.exception_handler(Exception)
    async def unexpected(_: Request, exc: Exception):
        log.exception("unhandled error")
        return JSONResponse({"error": "Internal error. See the server log."}, status_code=500)

    @app.get("/api/health")
    def health():
        return {"ok": True, "version": __version__, "auth_required": bool(dashboard_token)}

    @app.get("/api/providers")
    def providers():
        return engine.provider_status()

    @app.get("/api/config")
    def config():
        cfg = engine.config()
        return {"repo_root": engine.repo_root.name, "rag": cfg.rag.__dict__ | {"extensions": len(cfg.rag.extensions)},
                "min_severity": cfg.min_severity, "min_confidence": cfg.min_confidence,
                "max_comments": cfg.max_comments, "redact_secrets": cfg.redact_secrets,
                "github_token": bool(os.environ.get("GITHUB_TOKEN")),
                "webhook": bool(os.environ.get("GITHUB_WEBHOOK_SECRET"))}

    @app.get("/api/stats")
    def stats():
        return engine.store.stats()

    @app.get("/api/samples")
    def samples():
        return engine.samples()

    @app.get("/api/reviews")
    def list_reviews(limit: int = 50):
        return engine.store.list_reviews(max(1, min(limit, 200)))

    @app.post("/api/reviews")
    def create_review(body: ReviewIn):
        common = dict(provider=body.provider, model=body.model, rag=body.rag)
        if body.source == "pr":
            return engine.review_pr_url(body.pr_url, **common)
        root = engine.repo_root_for(body.repo) if body.repo else None
        if body.source == "sample":
            return engine.review_text(engine.sample_diff(body.sample), source="sample", root=root,
                                      title=body.title or f"Sample: {body.sample.replace('_', ' ')}", **common)
        return engine.review_text(body.diff, source="diff", title=body.title or "Pasted diff", root=root, **common)

    @app.get("/api/reviews/{review_id}")
    def get_review(review_id: int):
        rv = engine.get_review(review_id)
        if not rv:
            raise HTTPException(404, "Review not found")
        return rv

    @app.delete("/api/reviews/{review_id}")
    def delete_review(review_id: int):
        if not engine.store.delete_review(review_id):
            raise HTTPException(404, "Review not found")
        return {"ok": True}

    @app.post("/api/reviews/{review_id}/post")
    def post_review(review_id: int):
        return engine.post_to_github(review_id)

    @app.post("/api/reviews/{review_id}/tests")
    def make_tests(review_id: int, body: TestsIn):
        return engine.tests_for(review_id, body.path, body.provider, body.model)

    @app.post("/api/demo/seed")
    def seed_demo():
        return engine.seed_demo()

    @app.delete("/api/demo")
    def clear_demo():
        engine.clear_demo()
        return {"ok": True}

    @app.get("/api/eval")
    def list_evals():
        return engine.store.list_evals()

    @app.post("/api/eval")
    def run_eval(body: EvalIn):
        return engine.run_eval(body.provider, body.model)

    @app.get("/api/repos")
    def list_repos():
        return engine.list_repos()

    @app.post("/api/repos")
    def connect_repo(body: RepoIn):
        return engine.connect_repo(body.url)

    @app.delete("/api/repos/{slug}")
    def remove_repo(slug: str):
        engine.remove_repo(slug)
        return {"ok": True}

    @app.get("/api/repos/{slug}/pulls")
    def repo_pulls(slug: str):
        return engine.repo_pulls(slug)

    @app.get("/api/experiment/meta")
    def experiment_meta():
        return engine.experiment_meta()

    @app.get("/api/experiments")
    def list_experiments():
        return engine.store.list_experiments()

    @app.post("/api/experiments")
    def start_experiment(body: ExperimentIn):
        return engine.start_experiment(body.providers, body.repeats)

    @app.get("/api/experiments/{exp_id}")
    def get_experiment(exp_id: int):
        exp = engine.store.get_experiment(exp_id)
        if not exp:
            raise HTTPException(404, "Experiment not found")
        return exp

    @app.delete("/api/experiments/{exp_id}")
    def delete_experiment(exp_id: int):
        if not engine.store.delete_experiment(exp_id):
            raise HTTPException(404, "Experiment not found or still running")
        return {"ok": True}

    @app.get("/api/search")
    def search(q: str = "", k: int = 6, repo: str | None = None):
        return engine.search(q[:500], max(1, min(k, 15)), repo)

    @app.post("/api/ask")
    def ask(body: AskIn):
        return engine.ask(body.question, body.provider, body.model, body.repo)

    @app.post("/webhook/github", status_code=202)
    async def github_webhook(request: Request, background: BackgroundTasks):
        secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
        if not secret:
            raise HTTPException(503, "Webhook disabled: set GITHUB_WEBHOOK_SECRET")
        raw = await request.body()
        if not verify_signature(secret, raw, request.headers.get("x-hub-signature-256")):
            raise HTTPException(401, "Bad signature")
        event = request.headers.get("x-github-event", "")
        if event == "ping":
            return {"ok": True, "pong": True}
        if event != "pull_request":
            return {"ok": True, "ignored": event}
        payload = await request.json()
        pr = payload.get("pull_request") or {}
        if payload.get("action") not in WEBHOOK_ACTIONS or pr.get("draft"):
            return {"ok": True, "ignored": payload.get("action")}
        repo = (payload.get("repository") or {}).get("full_name", "")
        background.add_task(_review_webhook_pr, engine, repo, int(pr["number"]))
        return {"ok": True, "queued": f"{repo}#{pr['number']}"}

    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


def _review_webhook_pr(engine: Engine, repo: str, number: int) -> None:
    try:
        gh = GitHubClient(os.environ.get("GITHUB_TOKEN", ""), repo)
        pr = gh.get_pr(number)
        rv = engine.review_text(gh.get_diff(number), source="webhook", title=pr["title"] or f"{repo}#{number}",
                                provider=None, model=None, rag=None, repo=repo, pr_number=number,
                                head_sha=pr["head_sha"], pr_body=pr["body"], seen=gh.existing_fingerprints(number))
        if os.environ.get("CODEWARDEN_WEBHOOK_POST") == "1" and rv["result"]["findings"]:
            engine.post_to_github(rv["id"])
    except (GitHubError, UserError):
        log.exception("webhook review failed for %s#%s", repo, number)
