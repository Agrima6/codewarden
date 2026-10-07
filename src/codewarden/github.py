from __future__ import annotations

import re

import requests

from codewarden.models import Finding
from codewarden.report import MARKER_RE, render_comment

API = "https://api.github.com"
ALLOWED_REVIEW_EVENTS = frozenset({"COMMENT"})  # guardrail: never APPROVE or REQUEST_CHANGES


class GitHubError(RuntimeError):
    pass


class GitHubClient:
    def __init__(self, token: str, repo: str, session: requests.Session | None = None):
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
            raise GitHubError(f"Invalid repository {repo!r}, expected owner/name")
        self.repo = repo
        self.s = session or requests.Session()
        self.token = token
        self.s.headers.update({"X-GitHub-Api-Version": "2022-11-28", "User-Agent": "codewarden"})
        if token:  # reading public PRs works without one; posting does not
            self.s.headers["Authorization"] = f"Bearer {token}"

    def _req(self, method: str, path: str, accept: str = "application/vnd.github+json", **kw):
        resp = self.s.request(method, f"{API}/repos/{self.repo}{path}", headers={"Accept": accept},
                              timeout=60, **kw)
        return resp

    def get_pr(self, number: int) -> dict:
        r = self._req("GET", f"/pulls/{number}")
        if r.status_code != 200:
            raise GitHubError(f"Cannot read PR #{number}: HTTP {r.status_code}")
        d = r.json()
        return {"title": d.get("title") or "", "body": d.get("body") or "",
                "head_sha": d["head"]["sha"], "draft": bool(d.get("draft"))}

    def get_diff(self, number: int) -> str:
        r = self._req("GET", f"/pulls/{number}", accept="application/vnd.github.v3.diff")
        if r.status_code != 200:
            raise GitHubError(f"Cannot fetch diff for PR #{number}: HTTP {r.status_code}")
        return r.text

    def existing_fingerprints(self, number: int) -> set[str]:
        found: set[str] = set()
        page = 1
        while page <= 10:
            r = self._req("GET", f"/pulls/{number}/comments", params={"per_page": 100, "page": page})
            if r.status_code != 200:
                break
            batch = r.json()
            for c in batch:
                found.update(MARKER_RE.findall(c.get("body") or ""))
            if len(batch) < 100:
                break
            page += 1
        return found

    def post_review(self, number: int, head_sha: str, summary: str, findings: list[Finding]) -> tuple[int, int]:
        """Post one review with inline comments. Returns (inline_posted, moved_to_summary)."""
        if not self.token:
            raise GitHubError("GITHUB_TOKEN is not set; cannot post a review")
        inline = [f for f in findings if f.anchored]
        payload_comments = [{"path": f.path, "line": f.line, "side": "RIGHT", "body": render_comment(f)} for f in inline]
        event = "COMMENT"
        if event not in ALLOWED_REVIEW_EVENTS:
            raise GitHubError(f"Review event {event!r} is not allowed")
        body = {"commit_id": head_sha, "event": event, "body": summary, "comments": payload_comments}
        r = self._req("POST", f"/pulls/{number}/reviews", json=body)
        if r.status_code == 200:
            return len(inline), 0
        if r.status_code != 422 or not payload_comments:
            raise GitHubError(f"Posting review failed: HTTP {r.status_code} {r.text[:200]}")

        # One bad anchor rejects the whole batch; retry per comment so good ones still land.
        posted, failed = 0, []
        for f, c in zip(inline, payload_comments):
            rc = self._req("POST", f"/pulls/{number}/comments", json={**c, "commit_id": head_sha})
            if rc.status_code == 201:
                posted += 1
            else:
                failed.append(f)
        extra = "\n".join(f"- `{f.path}:{f.line}` **[{f.severity.upper()}]** {f.title}" for f in failed)
        tail = f"\n\n**Could not anchor inline:**\n{extra}" if extra else ""
        r2 = self._req("POST", f"/pulls/{number}/reviews",
                       json={"commit_id": head_sha, "event": "COMMENT", "body": summary + tail})
        if r2.status_code != 200:
            raise GitHubError(f"Posting summary failed: HTTP {r2.status_code}")
        return posted, len(failed)
