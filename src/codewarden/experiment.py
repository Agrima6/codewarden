"""Controlled comparison of review systems on labelled datasets.

Research question: does retrieving repository context (RAG) improve LLM-based pull request review, and how do
LLM reviewers compare with a pattern-matching baseline? Every number the dashboard shows comes from this module.
"""
from __future__ import annotations

import hashlib
import json
import math
import platform
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from codewarden import __version__
from codewarden.config import Config
from codewarden.evaluate import score_case
from codewarden.llm import get_llm
from codewarden.llm.base import LLMError
from codewarden.prompts import SYSTEM_PROMPT
from codewarden.rag import build_retriever
from codewarden.review import review_diff

Progress = Callable[[int, int, str], None]

CASE_BACKOFF_S = (10, 30, 60, 90)  # waits before re-trying a case when the provider is overloaded
_sleep = time.sleep


def _transient(message: str) -> bool:
    m = message.lower()
    return any(t in m for t in ("http 503", "http 429", "http 500", "http 502", "http 504", "timeout", "network error", "no content", "giving up"))


@dataclass(frozen=True)
class System:
    id: str
    label: str
    provider: str
    model: str
    rag: bool

    def to_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "provider": self.provider, "model": self.model, "rag": self.rag}


class ExperimentError(RuntimeError):
    pass


def build_systems(providers: list[str], models: dict[str, str] | None = None) -> list[System]:
    """The baseline gets one system; each language model gets a diff-only and a retrieval-augmented variant."""
    models = models or {}
    systems: list[System] = []
    for p in providers:
        if p == "rules":
            systems.append(System("rules", "Regex baseline", "rules", "", False))
            continue
        model = models.get(p, "")
        label = {"gemini": "Gemini", "ollama": "Ollama"}.get(p, p)
        shown = f" ({model})" if model else ""
        systems.append(System(f"{p}-diff", f"{label}{shown}, diff only", p, model, False))
        systems.append(System(f"{p}-rag", f"{label}{shown} + RAG", p, model, True))
    return systems


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """95% Wilson score interval for a proportion; honest about small samples."""
    if n == 0:
        return None
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def effective_wilson(successes: float, n: float, repeats: int) -> tuple[float, float] | None:
    """Interval that treats each distinct case as one observation. Repeated runs of the same cases measure
    run-to-run noise; they are not new evidence, so counting them would make the interval look too tight."""
    return wilson(successes / repeats, n / repeats) if n else None


def refresh_intervals(res: dict) -> dict:
    """Recompute intervals on stored results created before the per-case method (idempotent)."""
    if res.get("config", {}).get("ci_method") == "per-case":
        return res
    for m in res["metrics"].values():
        r = max(1, m.get("repeats", 1))
        m["precision_ci"] = effective_wilson(m["true_positives"], m["findings"], r)
        m["recall_ci"] = effective_wilson(m["matched"], m["expected"], r)
    res.setdefault("config", {})["ci_method"] = "per-case"
    return res


def load_suite(cases_dir: Path) -> list[dict]:
    cases = []
    for diff in sorted(cases_dir.glob("*.diff")):
        exp = diff.with_suffix(".expected.json")
        expected = json.loads(exp.read_text())["expected"] if exp.exists() else []
        cases.append({"name": diff.stem, "diff": diff.read_text(), "expected": expected})
    return cases


def dataset_hash(*dirs: Path) -> str:
    h = hashlib.sha256()
    for d in dirs:
        for p in sorted(d.glob("*")):
            if p.is_file():
                h.update(p.name.encode())
                h.update(p.read_bytes())
    return h.hexdigest()[:12]


def _git_commit(root: Path) -> str:
    try:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _describe(expected: list[dict]) -> str:
    return "; ".join(f"{e['path']}:{e['lines'][0]} ({e.get('category', '?')})" for e in expected) or "clean: no issue planted"


def _f1(precision: float | None, recall: float | None, expected: int) -> float | None:
    if not expected:
        return None
    if not precision or not recall:
        return 0.0  # nothing reported, or nothing correct: F1 is 0 by convention
    return 2 * precision * recall / (precision + recall)


def _agg(per_repeat: list[dict]) -> dict:
    """Aggregate counts across repeats into metrics. Precision/recall come from pooled counts."""
    tp = sum(r["tp"] for r in per_repeat)
    exp = sum(r["expected"] for r in per_repeat)
    matched = sum(r["matched"] for r in per_repeat)
    found = sum(r["findings"] for r in per_repeat)
    clean_n = sum(r["clean_cases"] for r in per_repeat)
    clean_fp = sum(r["clean_with_findings"] for r in per_repeat)
    precision = tp / found if found else None
    recall = matched / exp if exp else None
    f1 = _f1(precision, recall, exp)

    def run_stats(key):
        vals = [r[key] for r in per_repeat if r[key] is not None]
        return (statistics.mean(vals), statistics.pstdev(vals)) if len(vals) > 1 else None

    cats: dict[str, list[int]] = {}
    for r in per_repeat:
        for c, (hit, total) in r["by_category"].items():
            cats.setdefault(c, [0, 0])
            cats[c][0] += hit
            cats[c][1] += total
    cases = sum(r["cases"] for r in per_repeat)
    return {
        "repeats": len(per_repeat), "cases": cases, "expected": exp, "matched": matched, "findings": found,
        "true_positives": tp, "false_positives": found - tp, "false_negatives": exp - matched,
        "precision": precision, "recall": recall, "f1": f1,
        "precision_ci": effective_wilson(tp, found, len(per_repeat)), "recall_ci": effective_wilson(matched, exp, len(per_repeat)),
        "clean_cases": clean_n, "clean_false_alarms": clean_fp,
        "clean_false_alarm_rate": (clean_fp / clean_n) if clean_n else None,
        "run_to_run": {k: run_stats(k) for k in ("precision", "recall", "f1")} if len(per_repeat) > 1 else None,
        "by_category": {c: {"found": h, "total": t, "recall": h / t if t else None} for c, (h, t) in sorted(cats.items())},
        "avg_latency_ms": int(sum(r["latency_ms"] for r in per_repeat) / max(1, cases)),
        "requests": sum(r["requests"] for r in per_repeat),
        "tokens_prompt": sum(r["tokens_prompt"] for r in per_repeat),
        "tokens_output": sum(r["tokens_output"] for r in per_repeat),
    }


def run_experiment(*, systems: list[System], repeats: int, eval_dir: Path, base_cfg: Config,
                   progress: Progress | None = None, project_root: Path | None = None) -> dict:
    """Run every system on every applicable suite. Raises ExperimentError on any provider failure:
    a partial or silently-empty result would be misleading, so nothing is returned in that case."""
    if repeats < 1 or repeats > 10:
        raise ExperimentError("repeats must be between 1 and 10")
    project_root = project_root or eval_dir.parent.parent
    context_dir = eval_dir.parent / "context_cases"
    suites: dict[str, dict] = {"general": {"dir": eval_dir, "repo": None}}
    if context_dir.exists():
        meta = json.loads((context_dir / "suite.json").read_text()) if (context_dir / "suite.json").exists() else {}
        suites["context"] = {"dir": context_dir, "repo": project_root / meta.get("repo", "demo/shop")}
    for s in suites.values():
        s["cases"] = load_suite(s["dir"])
    descr = {"general": "Bugs visible in the diff alone", "context": "Bugs that depend on repository conventions and helper signatures"}

    def plan_for(system: System) -> list[str]:
        # Retrieval only matters where the repository is known, so the general suite runs once, diff-only.
        if system.rag:
            return [k for k in suites if suites[k]["repo"]]
        return list(suites)

    total = repeats * sum(len(suites[k]["cases"]) for sy in systems for k in plan_for(sy))
    done = 0
    retrievers: dict[str, object] = {}
    results = {"per_system": {}, "per_case": {}}
    models_used: dict[str, list[str]] = {}
    started = time.time()

    for system in systems:
        cfg = replace(base_cfg, provider=system.provider, model=system.model, max_comments=100,
                      rag=replace(base_cfg.rag))
        try:
            llm = get_llm(cfg)
        except LLMError as exc:
            raise ExperimentError(f"{system.label}: {exc}") from exc
        for suite_name in plan_for(system):
            suite = suites[suite_name]
            per_repeat = []
            for rep in range(repeats):
                row = {"tp": 0, "expected": 0, "matched": 0, "findings": 0, "clean_cases": 0, "clean_with_findings": 0,
                       "by_category": {}, "latency_ms": 0, "requests": 0, "tokens_prompt": 0, "tokens_output": 0,
                       "cases": len(suite["cases"])}
                for case in suite["cases"]:
                    cfg.rag.enabled = system.rag
                    retriever = None
                    if system.rag:
                        key = str(suite["repo"])
                        if key not in retrievers:
                            retrievers[key] = build_retriever(suite["repo"], base_cfg.rag)
                        retriever = retrievers[key]
                    before = dict(getattr(llm, "usage", {}) or {})
                    for wait in (*CASE_BACKOFF_S, None):
                        res = review_diff(case["diff"], cfg, llm, retriever)
                        if not res.errors:
                            break
                        if wait is None or not _transient(res.errors[0]):
                            raise ExperimentError(f"{system.label} on {suite_name}/{case['name']}: {res.errors[0]}")
                        if progress:
                            progress(done, total, f"Provider busy, retrying in {wait}s · {system.label} · {suite_name}/{case['name']}")
                        _sleep(wait)
                    matched, tp, _ = score_case(res.findings, case["expected"])
                    expected_n = len(case["expected"])
                    row["expected"] += expected_n
                    row["matched"] += matched
                    row["tp"] += tp
                    row["findings"] += len(res.findings)
                    if expected_n == 0:
                        row["clean_cases"] += 1
                        row["clean_with_findings"] += int(bool(res.findings))
                    for e in case["expected"]:
                        hit = any(f.path == e["path"] and e["lines"][0] - 2 <= f.line <= e["lines"][-1] + 2 for f in res.findings)
                        c = row["by_category"].setdefault(e.get("category", "?"), [0, 0])
                        c[0] += int(hit)
                        c[1] += 1
                    row["latency_ms"] += res.duration_ms
                    row["requests"] += res.requests
                    after = getattr(llm, "usage", {}) or {}
                    row["tokens_prompt"] += after.get("prompt", 0) - before.get("prompt", 0)
                    row["tokens_output"] += after.get("output", 0) - before.get("output", 0)
                    slot = results["per_case"].setdefault((suite_name, case["name"]), {
                        "suite": suite_name, "case": case["name"], "expected": _describe(case["expected"]),
                        "clean": expected_n == 0, "systems": {}})
                    s = slot["systems"].setdefault(system.id, {"found_in": 0, "false_alarm_runs": 0, "runs": 0, "findings": []})
                    s["runs"] += 1
                    s["found_in"] += int(expected_n > 0 and matched == expected_n)
                    s["false_alarm_runs"] += int(len(res.findings) > tp)
                    for f in res.findings:
                        label = f"{f.path}:{f.line} [{f.severity}] {f.title}"
                        if label not in s["findings"]:
                            s["findings"].append(label)
                    done += 1
                    if progress:
                        progress(done, total, f"{system.label} · {suite_name}/{case['name']} (run {rep + 1}/{repeats})")
                p, r = (row["tp"] / row["findings"] if row["findings"] else None), (row["matched"] / row["expected"] if row["expected"] else None)
                row["precision"], row["recall"] = p, r
                row["f1"] = _f1(p, r, row["expected"])
                per_repeat.append(row)
            results["per_system"][f"{system.id}|{suite_name}"] = _agg(per_repeat)
        models_used[system.id] = sorted(getattr(llm, "models_used", set()) or ([system.model] if system.model else []))

    cases_out = []
    for (suite_name, name), slot in results["per_case"].items():
        cases_out.append(slot)
    failures = []
    for slot in cases_out:
        for sid, s in slot["systems"].items():
            if not slot["clean"] and s["found_in"] < s["runs"]:
                failures.append({"kind": "missed", "suite": slot["suite"], "case": slot["case"], "system": sid,
                                 "detail": f"found in {s['found_in']}/{s['runs']} runs. Expected {slot['expected']}",
                                 "reported": s["findings"]})
            if s["false_alarm_runs"]:
                failures.append({"kind": "false_alarm", "suite": slot["suite"], "case": slot["case"], "system": sid,
                                 "detail": f"extra findings in {s['false_alarm_runs']}/{s['runs']} runs",
                                 "reported": s["findings"]})
    return {
        "systems": [s.to_dict() for s in systems],
        "suites": {k: {"description": descr.get(k, ""), "cases": len(v["cases"]),
                       "bugs": sum(len(c["expected"]) for c in v["cases"]),
                       "clean": sum(1 for c in v["cases"] if not c["expected"]),
                       "repo": v["repo"].name if v["repo"] else None} for k, v in suites.items()},
        "metrics": results["per_system"],
        "cases": cases_out,
        "failures": failures,
        "config": {
            "repeats": repeats, "temperature": base_cfg.temperature, "min_confidence": base_cfg.min_confidence,
            "line_tolerance": 2, "redact_secrets": base_cfg.redact_secrets, "ci_method": "per-case",
            "rag": {"backend": base_cfg.rag.backend, "chunker": base_cfg.rag.chunker, "top_k": base_cfg.rag.top_k},
            "models_that_answered": models_used,
            "prompt_hash": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()[:12],
            "dataset_hash": dataset_hash(*[s["dir"] for s in suites.values()]),
            "codewarden_version": __version__, "git_commit": _git_commit(project_root),
            "python": platform.python_version(), "duration_s": round(time.time() - started, 1),
            "command": "codewarden experiment --providers " + ",".join(sorted({s.provider for s in systems})) + f" --repeats {repeats}",
        },
    }
