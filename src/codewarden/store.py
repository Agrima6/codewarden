from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from codewarden.models import SEVERITIES, ReviewResult

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    repo TEXT NOT NULL DEFAULT '',
    pr_number INTEGER,
    head_sha TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    rag INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    requests INTEGER NOT NULL DEFAULT 0,
    n_files INTEGER NOT NULL DEFAULT 0,
    n_findings INTEGER NOT NULL DEFAULT 0,
    worst TEXT,
    posted INTEGER NOT NULL DEFAULT 0,
    diff_text TEXT NOT NULL,
    result_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id INTEGER NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    line INTEGER NOT NULL,
    severity TEXT NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    confidence REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_findings_review ON findings(review_id);
CREATE TABLE IF NOT EXISTS eval_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    precision REAL,
    recall REAL,
    false_positives INTEGER NOT NULL,
    cases_json TEXT NOT NULL
);
"""


def result_to_dict(r: ReviewResult) -> dict:
    return {
        "findings": [f.to_dict() for f in r.findings],
        "files_reviewed": r.files_reviewed,
        "files_skipped": r.files_skipped,
        "errors": r.errors,
        "context_used": r.context_used,
        "dropped": {
            "low_confidence": r.dropped_low_confidence, "below_severity": r.dropped_below_severity,
            "duplicates": r.dropped_duplicates, "over_cap": r.dropped_over_cap,
        },
    }


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._lock = threading.Lock()
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(_SCHEMA)

    def add_review(self, *, source: str, title: str, provider: str, model: str, rag: bool, diff_text: str,
                   result: ReviewResult, repo: str = "", pr_number: int | None = None, head_sha: str = "",
                   created_at: float | None = None) -> int:
        with self._lock, self._db:
            cur = self._db.execute(
                "INSERT INTO reviews (created_at, source, title, repo, pr_number, head_sha, provider, model, rag,"
                " duration_ms, requests, n_files, n_findings, worst, diff_text, result_json)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (created_at or time.time(), source, title, repo, pr_number, head_sha, provider, model, int(rag),
                 result.duration_ms, result.requests, len(result.files_reviewed), len(result.findings),
                 result.worst_severity(), diff_text, json.dumps(result_to_dict(result))),
            )
            rid = cur.lastrowid
            self._db.executemany(
                "INSERT INTO findings (review_id, path, line, severity, category, title, confidence) VALUES (?,?,?,?,?,?,?)",
                [(rid, f.path, f.line, f.severity, f.category, f.title, f.confidence) for f in result.findings],
            )
        return rid

    @staticmethod
    def _review_row(row: sqlite3.Row, full: bool = False) -> dict:
        d = {k: row[k] for k in row.keys() if k not in ("diff_text", "result_json")}
        d["rag"] = bool(d["rag"])
        d["posted"] = bool(d["posted"])
        if full:
            d["diff_text"] = row["diff_text"]
            d["result"] = json.loads(row["result_json"])
        return d

    def list_reviews(self, limit: int = 50) -> list[dict]:
        rows = self._db.execute("SELECT * FROM reviews ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for row in rows:
            d = self._review_row(row)
            sev = {s: 0 for s in SEVERITIES}
            for s, n in self._db.execute(
                    "SELECT severity, COUNT(*) FROM findings WHERE review_id=? GROUP BY severity", (row["id"],)):
                sev[s] = n
            d["by_severity"] = sev
            out.append(d)
        return out

    def get_review(self, review_id: int) -> dict | None:
        row = self._db.execute("SELECT * FROM reviews WHERE id=?", (review_id,)).fetchone()
        return self._review_row(row, full=True) if row else None

    def delete_review(self, review_id: int) -> bool:
        with self._lock, self._db:
            return self._db.execute("DELETE FROM reviews WHERE id=?", (review_id,)).rowcount > 0

    def mark_posted(self, review_id: int) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE reviews SET posted=1 WHERE id=?", (review_id,))

    def clear_reviews(self, source: str | None = None) -> None:
        with self._lock, self._db:
            if source:
                self._db.execute("DELETE FROM reviews WHERE source=?", (source,))
            else:
                self._db.execute("DELETE FROM reviews")

    def stats(self) -> dict:
        q = self._db.execute
        totals = q("SELECT COUNT(*) n, COALESCE(SUM(n_findings),0) f, COALESCE(AVG(duration_ms),0) d,"
                   " COALESCE(SUM(n_files),0) files FROM reviews").fetchone()
        sev = {s: 0 for s in SEVERITIES}
        for s, n in q("SELECT severity, COUNT(*) FROM findings GROUP BY severity"):
            sev[s] = n
        cat = {c: n for c, n in q("SELECT category, COUNT(*) FROM findings GROUP BY category ORDER BY 2 DESC")}
        top = [{"title": t, "count": n, "severity": s} for t, n, s in
               q("SELECT title, COUNT(*) n, MAX(severity) FROM findings GROUP BY title ORDER BY n DESC LIMIT 6")]
        hot = [{"path": p, "count": n} for p, n in
               q("SELECT path, COUNT(*) n FROM findings GROUP BY path ORDER BY n DESC, path LIMIT 6")]
        providers = {p: n for p, n in q("SELECT provider, COUNT(*) FROM reviews GROUP BY provider")}
        return {"reviews": totals["n"], "findings": totals["f"], "files_reviewed": totals["files"],
                "avg_duration_ms": int(totals["d"]), "by_severity": sev, "by_category": cat,
                "top_issues": top, "hot_files": hot, "providers": providers}

    def add_eval(self, provider: str, model: str, precision, recall, false_positives: int, cases: list[dict]) -> int:
        with self._lock, self._db:
            cur = self._db.execute(
                "INSERT INTO eval_runs (created_at, provider, model, precision, recall, false_positives, cases_json)"
                " VALUES (?,?,?,?,?,?,?)",
                (time.time(), provider, model, precision, recall, false_positives, json.dumps(cases)))
            return cur.lastrowid

    def list_evals(self, limit: int = 20) -> list[dict]:
        rows = self._db.execute("SELECT * FROM eval_runs ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)).fetchall()
        return [{**{k: r[k] for k in r.keys() if k != "cases_json"}, "cases": json.loads(r["cases_json"])} for r in rows]
