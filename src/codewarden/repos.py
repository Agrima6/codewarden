"""Connect a public GitHub repository: shallow clone into a private cache so it can be indexed for RAG."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import requests

GITHUB_REPO_RE = re.compile(r"^https://github\.com/([A-Za-z0-9][\w-]*)/([\w.-]+?)(?:\.git)?/?$")
SLUG_RE = re.compile(r"[A-Za-z0-9][\w-]*__[\w.-]+")
MAX_REPO_MB = 400
CLONE_TIMEOUT_S = 240


class RepoError(ValueError):
    """Safe to show to the user."""


def parse_repo_url(url: str) -> tuple[str, str]:
    m = GITHUB_REPO_RE.match((url or "").strip())
    if not m or m.group(2) in (".", ".."):
        raise RepoError("Enter a GitHub repository URL like https://github.com/owner/repo")
    return m.group(1), m.group(2)


def slug_for(owner: str, repo: str) -> str:
    return f"{owner}__{repo}".lower()


def _dir_mb(path: Path) -> float:
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += (Path(root) / f).stat().st_size
            except OSError:
                pass
    return total / 1_000_000


def _git(args: list[str], cwd: Path | None = None, timeout: int = 30) -> subprocess.CompletedProcess:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1"}
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)


class RepoManager:
    def __init__(self, base: Path):
        self.base = Path(base)
        self.base.mkdir(parents=True, exist_ok=True)

    def path_for(self, slug: str) -> Path:
        if not SLUG_RE.fullmatch(slug) or slug.split("__", 1)[1] in (".", ".."):
            raise RepoError("Unknown repository")
        return self.base / slug

    def connect(self, url: str) -> dict:
        owner, repo = parse_repo_url(url)
        slug = slug_for(owner, repo)
        dest = self.base / slug
        if (dest / ".git").exists():
            r = _git(["fetch", "--depth", "1", "origin"], cwd=dest, timeout=CLONE_TIMEOUT_S)
            if r.returncode == 0:
                _git(["reset", "--hard", "FETCH_HEAD"], cwd=dest, timeout=60)
            return self.describe(slug, owner, repo)
        if dest.exists():
            shutil.rmtree(dest)
        try:
            r = _git(["clone", "--depth", "1", "--no-tags", "--single-branch", "--no-recurse-submodules",
                      "-c", "core.symlinks=false", "-c", "protocol.file.allow=never",
                      f"https://github.com/{owner}/{repo}.git", str(dest)], timeout=CLONE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            shutil.rmtree(dest, ignore_errors=True)
            raise RepoError("Cloning took too long. Try a smaller repository.")
        if r.returncode != 0:
            shutil.rmtree(dest, ignore_errors=True)
            hint = "It may be private or misspelled." if "not found" in r.stderr.lower() or "denied" in r.stderr.lower() else ""
            raise RepoError(f"Could not clone {owner}/{repo}. {hint}".strip())
        size = _dir_mb(dest)
        if size > MAX_REPO_MB:
            shutil.rmtree(dest, ignore_errors=True)
            raise RepoError(f"{owner}/{repo} is {size:.0f} MB, above the {MAX_REPO_MB} MB limit.")
        return self.describe(slug, owner, repo)

    def describe(self, slug: str, owner: str = "", repo: str = "") -> dict:
        path = self.path_for(slug)
        if not owner:
            owner, _, repo = slug.partition("__")
        head = _git(["rev-parse", "--short", "HEAD"], cwd=path).stdout.strip()
        branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=path).stdout.strip()
        subject = _git(["log", "-1", "--format=%s"], cwd=path).stdout.strip()
        files = sum(1 for _ in (p for p in path.rglob("*") if p.is_file() and ".git" not in p.parts))
        return {"slug": slug, "owner": owner, "repo": repo, "url": f"https://github.com/{owner}/{repo}", "head": head,
                "branch": branch, "last_commit": subject, "files": files, "size_mb": round(_dir_mb(path), 1),
                "connected_at": path.stat().st_mtime if path.exists() else time.time()}

    def list(self) -> list[dict]:
        out = []
        for p in sorted(self.base.iterdir()):
            if p.is_dir() and (p / ".git").exists() and SLUG_RE.fullmatch(p.name):
                try:
                    out.append(self.describe(p.name))
                except (subprocess.SubprocessError, OSError):
                    continue
        return out

    def remove(self, slug: str) -> bool:
        path = self.path_for(slug)
        if not path.exists():
            return False
        shutil.rmtree(path, ignore_errors=True)
        return True


def recent_pulls(owner: str, repo: str, token: str = "", limit: int = 12) -> list[dict]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "codewarden"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.get(f"https://api.github.com/repos/{owner}/{repo}/pulls",
                     params={"state": "all", "per_page": limit, "sort": "updated", "direction": "desc"},
                     headers=headers, timeout=20)
    if r.status_code == 403 and "rate limit" in r.text.lower():
        raise RepoError("GitHub's anonymous rate limit was reached. Set GITHUB_TOKEN on the server or wait a few minutes.")
    if r.status_code != 200:
        raise RepoError(f"Could not list pull requests (HTTP {r.status_code}).")
    return [{"number": p["number"], "title": p["title"], "state": "merged" if p.get("merged_at") else p["state"],
             "author": (p.get("user") or {}).get("login", ""), "updated_at": p["updated_at"], "url": p["html_url"]}
            for p in r.json()]
