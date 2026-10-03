from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from codewarden.config import Config
from codewarden.llm.base import LLM
from codewarden.models import Finding
from codewarden.review import review_diff

LINE_TOLERANCE = 2


@dataclass
class CaseScore:
    name: str
    expected: int
    matched: int
    findings: int
    true_positive_findings: int
    categories_ok: int
    expected_desc: str = ""
    found_desc: str = ""
    error: str = ""


def score_case(findings: list[Finding], expected: list[dict]) -> tuple[int, int, int]:
    """Returns (expected matched, findings that hit an expected issue, of which category agreed)."""
    matched_exp: set[int] = set()
    tp_findings = cat_ok = 0
    for f in findings:
        for i, e in enumerate(expected):
            lo, hi = e["lines"][0], e["lines"][-1]
            if f.path == e["path"] and lo - LINE_TOLERANCE <= f.line <= hi + LINE_TOLERANCE:
                matched_exp.add(i)
                tp_findings += 1
                cat_ok += int(f.category == e.get("category", f.category))
                break
    return len(matched_exp), tp_findings, cat_ok


def run_eval(cases_dir: Path, cfg: Config, llm: LLM) -> list[CaseScore]:
    scores = []
    for diff_path in sorted(cases_dir.glob("*.diff")):
        exp_path = diff_path.with_suffix(".expected.json")
        expected = json.loads(exp_path.read_text())["expected"] if exp_path.exists() else []
        res = review_diff(diff_path.read_text(), cfg, llm, retriever=None)
        m, tp, cat = score_case(res.findings, expected)
        exp_desc = "; ".join(f"{e['path']}:{e['lines'][0]} ({e.get('category', '?')})" for e in expected) or "no issues"
        found_desc = "; ".join(f"{f.path}:{f.line} {f.title}" for f in res.findings) or "no findings"
        scores.append(CaseScore(diff_path.stem, len(expected), m, len(res.findings), tp, cat, exp_desc, found_desc,
                                  res.errors[0] if res.errors else ""))
    return scores


def summarize(scores: list[CaseScore]) -> dict:
    exp = sum(s.expected for s in scores)
    found = sum(s.findings for s in scores)
    tp = sum(s.true_positive_findings for s in scores)
    matched = sum(s.matched for s in scores)
    return {
        "cases": len(scores),
        "precision": (tp / found) if found else None,
        "recall": (matched / exp) if exp else None,
        "false_positives": found - tp,
    }
