from __future__ import annotations

import time

from codewarden.config import Config
from codewarden.diff import FileDiff, Hunk, parse_diff
from codewarden.filters import skip_reason
from codewarden.llm.base import LLM, LLMError
from codewarden.models import Finding, ReviewResult, severity_rank
from codewarden.parsing import parse_findings
from codewarden.prompts import SYSTEM_PROMPT, build_user_prompt
from codewarden.redact import redact

_QUERY_CHARS = 2000


def _split_hunk(h: Hunk, limit: int) -> list[Hunk]:
    if len(h.render()) <= limit:
        return [h]
    pieces, cur, size = [], [], len(h.header)
    for ln in h.lines:
        cost = len(ln.text) + 12
        if cur and size + cost > limit:
            pieces.append(Hunk(h.header, cur))
            cur, size = [], len(h.header)
        cur.append(ln)
        size += cost
    if cur:
        pieces.append(Hunk(h.header, cur))
    return pieces


def make_batches(f: FileDiff, limit: int) -> list[list[Hunk]]:
    """Pack hunks into batches that each fit one LLM request."""
    batches: list[list[Hunk]] = []
    cur: list[Hunk] = []
    size = 0
    for hunk in (p for h in f.hunks for p in _split_hunk(h, limit)):
        n = len(hunk.render())
        if cur and size + n > limit:
            batches.append(cur)
            cur, size = [], 0
        cur.append(hunk)
        size += n
    if cur:
        batches.append(cur)
    return batches


def _anchor(f: FileDiff, line: int, tolerance: int = 3) -> int | None:
    ok = f.commentable_lines()
    if line in ok:
        return line
    if ok:
        nearest = min(ok, key=lambda n: abs(n - line))
        if abs(nearest - line) <= tolerance:
            return nearest
    return None


def _context_for(retriever, f: FileDiff, batch: list[Hunk], k: int):
    if retriever is None:
        return []
    changed = [ln for h in batch for ln in h.lines if ln.new_no is not None]
    if not changed:
        return []
    lo, hi = min(ln.new_no for ln in changed), max(ln.new_no for ln in changed)
    query = f.path + "\n" + "\n".join(ln.text for ln in changed if ln.kind == "+")[:_QUERY_CHARS]

    def overlaps_change(c) -> bool:
        return c.path == f.path and c.start <= hi and c.end >= lo

    return retriever.search(query, k=k, exclude=overlaps_change)


def review_diff(diff_text: str, cfg: Config, llm: LLM, retriever=None, pr_title: str = "",
                pr_body: str = "", seen_fingerprints: set[str] | None = None) -> ReviewResult:
    started = time.monotonic()
    result = ReviewResult()
    candidates: list[Finding] = []
    reviewed = 0

    for f in parse_diff(diff_text):
        reason = skip_reason(f, cfg.exclude)
        if reason is None and reviewed >= cfg.max_files:
            reason = f"over the {cfg.max_files}-file review limit"
        if reason:
            result.files_skipped[f.path] = reason
            continue
        reviewed += 1
        result.files_reviewed.append(f.path)

        added = f.added_lines()
        for batch in make_batches(f, cfg.max_chars_per_request):
            diff_block = "\n".join(h.render() for h in batch)
            context = _context_for(retriever, f, batch, cfg.rag.top_k)
            refs = result.context_used.setdefault(f.path, [])
            refs += [r for r in (f"{c.path}:{c.start}-{c.end}" for c in context) if r not in refs]
            user = build_user_prompt(f.path, diff_block, pr_title, pr_body, context)
            if cfg.redact_secrets:
                user = redact(user)
            result.requests += 1
            try:
                raw = llm.complete(SYSTEM_PROMPT, user)
            except LLMError as exc:
                result.errors.append(f"{f.path}: {exc}")
                continue
            for item in parse_findings(raw):
                line = _anchor(f, item["line"])
                finding = Finding(path=f.path, line=line or item["line"], anchored=line is not None,
                                  severity=item["severity"], category=item["category"], title=item["title"],
                                  explanation=item["explanation"], suggestion=item["suggestion"],
                                  confidence=item["confidence"])
                finding.line_text = f.line_text(finding.line).strip()
                if item["replacement"] and finding.anchored and finding.line in added \
                        and item["replacement"].strip() != finding.line_text:
                    finding.replacement = item["replacement"]
                candidates.append(finding)

    seen = set(seen_fingerprints or ())
    kept: list[Finding] = []
    for fd in candidates:
        if fd.confidence < cfg.min_confidence:
            result.dropped_low_confidence += 1
        elif severity_rank(fd.severity) < severity_rank(cfg.min_severity):
            result.dropped_below_severity += 1
        elif fd.fingerprint in seen:
            result.dropped_duplicates += 1
        else:
            seen.add(fd.fingerprint)
            kept.append(fd)

    kept.sort(key=lambda fd: (-severity_rank(fd.severity), -fd.confidence, fd.path, fd.line))
    result.dropped_over_cap = max(0, len(kept) - cfg.max_comments)
    result.findings = kept[: cfg.max_comments]
    result.duration_ms = int((time.monotonic() - started) * 1000)
    return result
