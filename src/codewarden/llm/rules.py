from __future__ import annotations

import json
import re

# (regex, severity, category, title, explanation, suggestion)
_RULES = [
    (r"\b(eval|exec)\s*\(", "high", "security", "Dynamic code execution",
     "eval/exec runs arbitrary code; if any part of the input is user-controlled this is remote code execution.",
     "Parse the data explicitly (json.loads / ast.literal_eval) or dispatch through an allow-list."),
    (r"(execute|query)\s*\(\s*f[\"']|(execute|query)\s*\(.*[\"']\s*(%|\+)\s*\w|\.format\(.*\).*(select|insert|update|delete)\b",
     "critical", "security", "SQL built with string formatting",
     "Interpolating values into SQL allows SQL injection.",
     "Use parameterized queries: cursor.execute(sql, params)."),
    (r"\.innerHTML\s*=|dangerouslySetInnerHTML", "high", "security", "Unsanitised HTML injection",
     "Writing untrusted strings into the DOM as HTML enables XSS.",
     "Use textContent, or sanitise the HTML with a vetted library."),
    (r"(?i)(api[_-]?key|secret|password|token)\w*\s*[:=]\s*[\"'][^\"']{6,}[\"']", "high", "security",
     "Hard-coded credential",
     "Secrets committed to source control are exposed to everyone with repository access.",
     "Load the value from an environment variable or secret manager and rotate the leaked one."),
    (r"^\s*except\s*(Exception\s*)?(as \w+)?\s*:\s*$", "medium", "bug", "Overly broad exception handler",
     "A bare/broad except hides real failures and can swallow KeyboardInterrupt/SystemExit.",
     "Catch the specific exceptions you expect and log or re-raise the rest."),
    (r"range\(\s*len\([^)]*\)\s*\+\s*1\s*\)", "high", "bug", "Likely off-by-one in loop bound",
     "range(len(x) + 1) iterates one index past the end and raises IndexError.",
     "Use range(len(x)) or iterate the sequence directly."),
    (r"verify\s*=\s*False", "high", "security", "TLS verification disabled",
     "Disabling certificate verification allows man-in-the-middle attacks.",
     "Remove verify=False or pin the correct CA bundle."),
    (r"\bmd5\b|\bsha1\b\(", "medium", "security", "Weak hash function",
     "MD5/SHA-1 are broken for security purposes.", "Use SHA-256 or a password hash such as bcrypt/argon2."),
]

_LINE_RE = re.compile(r"^\s*(\d+) \+ (.*)$")


class RulesLLM:
    """Offline, deterministic reviewer. Not an AI model: it is the pattern-matching baseline
    used for tests, demos without an API key, and as a comparison point in evaluation."""

    def complete(self, system: str, user: str) -> str:
        findings = []
        seen = set()
        for raw in user.splitlines():
            m = _LINE_RE.match(raw)
            if not m:
                continue
            no, code = int(m.group(1)), m.group(2)
            for pattern, sev, cat, title, why, fix in _RULES:
                if re.search(pattern, code, re.I) and (no, title) not in seen:
                    seen.add((no, title))
                    findings.append({
                        "line": no, "severity": sev, "category": cat, "title": title,
                        "explanation": why, "suggestion": fix, "confidence": 0.8,
                    })
        return json.dumps({"findings": findings})
