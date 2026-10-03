from __future__ import annotations

import re

from codewarden.models import SEVERITIES, Finding, ReviewResult

MARKER_RE = re.compile(r"<!-- codewarden:([0-9a-f]{12}) -->")


def render_comment(f: Finding) -> str:
    lines = [f"**[{f.severity.upper()}] {f.category.title()}** - {f.title}", "", f.explanation]
    if f.suggestion:
        lines += ["", "**Suggested fix:**", f.suggestion]
    if f.replacement and f.anchored:
        lines += ["", "```suggestion", f.replacement, "```"]
    lines += ["", f"<sub>CodeWarden - confidence {f.confidence:.0%}. Automated review; verify before acting.</sub>",
              f"<!-- codewarden:{f.fingerprint} -->"]
    return "\n".join(lines)


def render_summary(r: ReviewResult) -> str:
    out = ["## CodeWarden review", ""]
    if not r.findings:
        out.append(f"No issues found in {len(r.files_reviewed)} reviewed file(s).")
    else:
        counts = {s: sum(1 for f in r.findings if f.severity == s) for s in SEVERITIES}
        badge = " | ".join(f"{counts[s]} {s}" for s in reversed(SEVERITIES) if counts[s])
        out.append(f"**{len(r.findings)} finding(s)** across {len(r.files_reviewed)} reviewed file(s): {badge}")
        out += ["", "| Severity | Category | Location | Issue |", "|---|---|---|---|"]
        for f in r.findings:
            out.append(f"| {f.severity} | {f.category} | `{f.path}:{f.line}` | {f.title} |")
    notes = []
    if r.dropped_over_cap:
        notes.append(f"{r.dropped_over_cap} lower-priority finding(s) omitted (comment cap)")
    if r.dropped_duplicates:
        notes.append(f"{r.dropped_duplicates} already reported earlier")
    if r.files_skipped:
        notes.append(f"{len(r.files_skipped)} file(s) skipped")
    if r.errors:
        notes.append(f"{len(r.errors)} request(s) failed, so some files may be partially reviewed")
    if notes:
        out += ["", "<sub>" + "; ".join(notes) + ".</sub>"]
    out += ["", "<sub>Automated first-pass review. A human reviewer makes the final call.</sub>"]
    return "\n".join(out)


def render_terminal(r: ReviewResult) -> str:
    out = []
    for f in r.findings:
        loc = f"{f.path}:{f.line}" + ("" if f.anchored else " (outside diff)")
        out.append(f"[{f.severity.upper():8}] {loc}  {f.category}: {f.title}")
        out.append(f"           {f.explanation}")
        if f.suggestion:
            out.append(f"           fix: {f.suggestion}")
    out.append("")
    out.append(f"{len(r.findings)} finding(s), {len(r.files_reviewed)} file(s) reviewed, "
               f"{len(r.files_skipped)} skipped, {len(r.errors)} error(s)")
    for e in r.errors:
        out.append(f"  error: {e}")
    return "\n".join(out)
