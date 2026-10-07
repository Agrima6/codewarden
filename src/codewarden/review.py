from __future__ import annotations

import time

from codewarden.config import Config
from codewarden.diff import FileDiff, Hunk, parse_diff
from codewarden.filters import skip_reason
from codewarden.llm.base import LLM, LLMError
from codewarden.models import Finding, ReviewResult, severity_rank
from codewarden.guardrails import (INJECTION_TITLE, GuardEvent, detect_injection, neutralize_injection,
                                   prepare_for_model, sanitize_output, unsafe_replacement)
from codewarden.parsing import parse_findings_ex
from codewarden.prompts import SYSTEM_PROMPT, build_user_prompt
from codewarden.rag.chunker import Chunk

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
    events: list[GuardEvent] = result.guardrails
    candidates: list[Finding] = []
    reviewed = 0

    if cfg.detect_injection:  # PR text is attacker-controlled: neutralise instruction-like phrases before the model sees it
        for label, text in (("PR title", pr_title), ("PR description", pr_body)):
            clean, hits = neutralize_injection(text or "")
            if hits:
                events.append(GuardEvent("input", "injection_detection", "neutralized", label, ", ".join(hits), len(hits)))
                if label == "PR title":
                    pr_title = clean
                else:
                    pr_body = clean

    for f in parse_diff(diff_text):
        reason = skip_reason(f, cfg.exclude)
        if reason is None and reviewed >= cfg.max_files:
            reason = f"over the {cfg.max_files}-file review limit"
        if reason:
            result.files_skipped[f.path] = reason
            if reason.startswith("sensitive file"):
                events.append(GuardEvent("input", "sensitive_files", "skipped", f.path, reason))
            continue
        reviewed += 1
        result.files_reviewed.append(f.path)

        added = f.added_lines()
        injected: list[tuple[int, str, list[str]]] = []
        if cfg.detect_injection:
            for no, text in added.items():
                hits = detect_injection(text)
                if hits:
                    injected.append((no, text, hits))
                    events.append(GuardEvent("input", "injection_detection", "flagged", f"{f.path}:{no}", ", ".join(hits), len(hits)))
        for batch in make_batches(f, cfg.max_chars_per_request):
            diff_block = "\n".join(h.render() for h in batch)
            context = _context_for(retriever, f, batch, cfg.rag.top_k)
            if cfg.detect_injection:
                safe_context = []
                for c in context:
                    clean, hits = neutralize_injection(c.text)
                    if hits:
                        events.append(GuardEvent("input", "injection_detection", "neutralized", f"retrieved {c.path}:{c.start}-{c.end}", ", ".join(hits), len(hits)))
                    safe_context.append(Chunk(c.path, c.start, c.end, clean))
                context = safe_context
            refs = result.context_used.setdefault(f.path, [])
            refs += [r for r in (f"{c.path}:{c.start}-{c.end}" for c in context) if r not in refs]
            user = build_user_prompt(f.path, diff_block, pr_title, pr_body, context)
            user, prep = prepare_for_model(user, redact_secrets=cfg.redact_secrets, pii=cfg.mask_pii, where=f.path)
            events.extend(prep)
            result.requests += 1
            try:
                raw = llm.complete(SYSTEM_PROMPT, user)
            except LLMError as exc:
                result.errors.append(f"{f.path}: {exc}")
                continue
            items, rejected = parse_findings_ex(raw)
            if rejected:
                events.append(GuardEvent("model", "schema_validation", "dropped", f.path, f"{rejected} malformed finding(s) rejected", rejected))
            for item in items:
                if cfg.sanitize_output:
                    acts: dict[str, int] = {}
                    for fld in ("title", "explanation", "suggestion"):
                        item[fld], a = sanitize_output(item[fld], fld)
                        for k, n in a.items():
                            acts[k] = acts.get(k, 0) + n
                    scrubbed = acts.pop("secret scrubbed", 0)
                    if scrubbed:
                        events.append(GuardEvent("output", "output_secret_scrub", "redacted", f.path, f"{scrubbed} credential-like value(s) removed from model text", scrubbed))
                    if acts:
                        events.append(GuardEvent("output", "output_sanitization", "sanitized", f.path, ", ".join(f"{n} {k}" for k, n in acts.items()), sum(acts.values())))
                line = _anchor(f, item["line"])
                finding = Finding(path=f.path, line=line or item["line"], anchored=line is not None,
                                  severity=item["severity"], category=item["category"], title=item["title"],
                                  explanation=item["explanation"], suggestion=item["suggestion"],
                                  confidence=item["confidence"])
                finding.line_text = f.line_text(finding.line).strip()
                if item["replacement"] and finding.anchored and finding.line in added \
                        and item["replacement"].strip() != finding.line_text:
                    danger = unsafe_replacement(item["replacement"], finding.line_text) if cfg.sanitize_output else None
                    if danger:
                        events.append(GuardEvent("output", "unsafe_suggestion", "removed", f"{f.path}:{finding.line}", f"suggested fix {danger}", 1))
                    else:
                        finding.replacement = item["replacement"]
                if not finding.anchored:
                    events.append(GuardEvent("model", "line_grounding", "flagged", f.path, f"line {item['line']} is not a changed line; kept out of inline comments"))
                candidates.append(finding)
        for no, text, hits in injected:  # a hit in changed code is always reported, whatever the model said
            if not any(c.path == f.path and c.line == no for c in candidates):
                candidates.append(Finding(
                    path=f.path, line=no, severity="high", category="security", title=INJECTION_TITLE,
                    explanation="This line contains text that tries to instruct an automated reviewer (" + ", ".join(hits) +
                                "). Treat it as hostile content.",
                    suggestion="Remove the text and find out who added it.", confidence=0.95, line_text=text.strip()))

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
    low = result.dropped_low_confidence + result.dropped_below_severity
    if low:
        events.append(GuardEvent("model", "confidence_filter", "dropped", "", f"{low} finding(s) below the confidence/severity threshold", low))
    capped = result.dropped_over_cap + result.dropped_duplicates
    if capped:
        events.append(GuardEvent("model", "comment_cap", "dropped", "", f"{result.dropped_duplicates} already reported, {result.dropped_over_cap} over the comment cap", capped))
    result.findings = kept[: cfg.max_comments]
    result.duration_ms = int((time.monotonic() - started) * 1000)
    return result
