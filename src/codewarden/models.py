from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

SEVERITIES = ("low", "medium", "high", "critical")
CATEGORIES = ("bug", "security", "performance", "maintainability", "style", "test")

_SEVERITY_ALIASES = {
    "info": "low", "minor": "low", "nit": "low", "suggestion": "low",
    "warning": "medium", "moderate": "medium",
    "error": "high", "major": "high",
    "blocker": "critical", "severe": "critical",
}


def severity_rank(severity: str) -> int:
    return SEVERITIES.index(severity)


def normalize_severity(value: object) -> str:
    v = str(value or "").strip().lower()
    v = _SEVERITY_ALIASES.get(v, v)
    return v if v in SEVERITIES else "medium"


def normalize_category(value: object) -> str:
    v = str(value or "").strip().lower()
    return v if v in CATEGORIES else "bug"


@dataclass
class Finding:
    path: str
    line: int
    severity: str
    category: str
    title: str
    explanation: str
    suggestion: str = ""
    confidence: float = 0.7
    line_text: str = ""
    anchored: bool = True

    @property
    def fingerprint(self) -> str:
        # Stable across pushes: keyed on the flagged code, not its line number.
        norm = re.sub(r"\s+", " ", f"{self.path}|{self.category}|{self.title}|{self.line_text}".lower())
        return hashlib.sha1(norm.encode()).hexdigest()[:12]


@dataclass
class ReviewResult:
    findings: list[Finding] = field(default_factory=list)
    files_reviewed: list[str] = field(default_factory=list)
    files_skipped: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    dropped_low_confidence: int = 0
    dropped_below_severity: int = 0
    dropped_duplicates: int = 0
    dropped_over_cap: int = 0

    def worst_severity(self) -> str | None:
        if not self.findings:
            return None
        return max((f.severity for f in self.findings), key=severity_rank)
