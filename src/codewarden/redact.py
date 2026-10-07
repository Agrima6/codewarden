from __future__ import annotations

import re

_PATTERNS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), "[REDACTED_PRIVATE_KEY]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), "[REDACTED_GOOGLE_KEY]"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"), "[REDACTED_SLACK_TOKEN]"),
    (
        re.compile(r"""(?ix)(\w*?(?:api[_-]?key|secret|token|passw(?:or)?d|pwd|auth)[\w-]*\s*[:=]\s*)(["'])(?!\[REDACTED)([^"'\n]{8,})\2"""),
        r"\1\2[REDACTED_SECRET]\2",
    ),
]


def redact(text: str) -> str:
    """Strip likely credentials before any code is sent to an LLM."""
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text
