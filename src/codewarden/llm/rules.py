from __future__ import annotations

import json
import re

# (regex, severity, category, title, explanation, suggestion, (fix_pattern, fix_repl) | None)
_RULES = [
    (r"\b(eval|exec)\s*\(", "high", "security", "Dynamic code execution",
     "eval/exec runs arbitrary code; if any part of the input is user-controlled this is remote code execution.",
     "Parse the data explicitly (json.loads / ast.literal_eval) or dispatch through an allow-list.",
     (r"\beval\(", "ast.literal_eval(")),
    (r"(execute|query)\s*\(\s*f[\"']|(execute|query)\s*\(.*[\"']\s*(%|\+)\s*\w|\.format\(.*\).*(select|insert|update|delete)\b",
     "critical", "security", "SQL built with string formatting",
     "Interpolating values into SQL allows SQL injection.",
     "Use parameterized queries: cursor.execute(sql, params).", None),
    (r"\.innerHTML\s*=|dangerouslySetInnerHTML", "high", "security", "Unsanitised HTML injection",
     "Writing untrusted strings into the DOM as HTML enables XSS.",
     "Use textContent, or sanitise the HTML with a vetted library.",
     (r"\.innerHTML\s*=", ".textContent =")),
    (r"(?i)(api[_-]?key|secret|password|token)\w*\s*[:=]\s*[\"'][^\"']{6,}[\"']", "high", "security",
     "Hard-coded credential",
     "Secrets committed to source control are exposed to everyone with repository access.",
     "Load the value from an environment variable or secret manager and rotate the leaked one.", None),
    (r"^\s*except\s*(Exception\s*)?(as \w+)?\s*:\s*$", "medium", "bug", "Overly broad exception handler",
     "A bare/broad except hides real failures and can swallow KeyboardInterrupt/SystemExit.",
     "Catch the specific exceptions you expect and log or re-raise the rest.",
     (r"except\s*:", "except Exception:")),
    (r"range\(\s*len\([^)]*\)\s*\+\s*1\s*\)", "high", "bug", "Likely off-by-one in loop bound",
     "range(len(x) + 1) iterates one index past the end and raises IndexError.",
     "Use range(len(x)) or iterate the sequence directly.",
     (r"(range\(\s*len\([^)]*\))\s*\+\s*1\s*\)", r"\1)")),
    (r"verify\s*=\s*False", "high", "security", "TLS verification disabled",
     "Disabling certificate verification allows man-in-the-middle attacks.",
     "Remove verify=False or pin the correct CA bundle.",
     (r"verify\s*=\s*False", "verify=True")),
    (r"\bmd5\b|\bsha1\b\(", "medium", "security", "Weak hash function",
     "MD5/SHA-1 are broken for security purposes.", "Use SHA-256 or a password hash such as bcrypt/argon2.", None),
    (r"(?i)ignore (all )?(previous|prior) instructions|approve (this|the) (pr|pull request)", "high", "security",
     "Prompt-injection text in the change",
     "The change contains text that tries to instruct an automated reviewer. Treat it as hostile content.",
     "Remove the text and investigate who added it.", None),
]

_LINE_RE = re.compile(r"^\s*(\d+) \+ (.*)$")
_LOOP_RE = re.compile(r"^\s*(for\b.+:|for\s*\(.+\)\s*\{?|while\b.+:)\s*$")
_DB_CALL_RE = re.compile(r"\.(query|execute|find_one|get_by_id|fetch\w*)\s*\(")
_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(([^)]*)\)")
_FILE_RE = re.compile(r"^File under review: (.+)$", re.M)


def _finding(no, sev, cat, title, why, fix, replacement="", conf=0.8):
    return {"line": no, "severity": sev, "category": cat, "title": title, "explanation": why,
            "suggestion": fix, "replacement": replacement, "confidence": conf}


class RulesLLM:
    """Offline, deterministic reviewer. Not an AI model: it is the pattern-matching baseline
    used for tests, demos without an API key, and as a comparison point in evaluation."""

    def complete(self, system: str, user: str) -> str:
        if "[task:testgen]" in system:
            return self._testgen(user)
        if "[task:qa]" in system:
            return ("Offline mode: no language model is configured, so no answer was generated. "
                    "The retrieved code below is what a model would have been given.")
        return self._review(user)

    def _review(self, user: str) -> str:
        findings, seen = [], set()
        loop_indent = loop_line = None
        for raw in user.splitlines():
            m = _LINE_RE.match(raw)
            if not m:
                continue
            no, code = int(m.group(1)), m.group(2)
            for pattern, sev, cat, title, why, fix, repl in _RULES:
                if re.search(pattern, code, re.I) and (no, title) not in seen:
                    seen.add((no, title))
                    replacement = re.sub(repl[0], repl[1], code, count=1) if repl else ""
                    findings.append(_finding(no, sev, cat, title, why, fix,
                                             replacement if replacement != code else ""))
            indent = len(code) - len(code.lstrip())
            if _LOOP_RE.match(code):
                loop_indent, loop_line = indent, no
            elif loop_indent is not None and code.strip() and indent <= loop_indent:
                loop_indent = loop_line = None
            elif loop_indent is not None and _DB_CALL_RE.search(code) and (no, "n+1") not in seen:
                seen.add((no, "n+1"))
                findings.append(_finding(
                    no, "medium", "performance", "Database call inside a loop (N+1 queries)",
                    f"This runs one query per iteration of the loop at line {loop_line}; it scales linearly with the data.",
                    "Fetch all rows in one query (JOIN / IN clause) before the loop.", conf=0.7))
        return json.dumps({"findings": findings})

    def _testgen(self, user: str) -> str:
        m = _FILE_RE.search(user)
        path = m.group(1).strip() if m else "module.py"
        module = re.sub(r"\.py$", "", path).replace("/", ".")
        funcs = []
        for raw in user.splitlines():
            lm = _LINE_RE.match(raw)
            dm = _DEF_RE.match(lm.group(2)) if lm else None
            if dm and not dm.group(1).startswith("_"):
                args = [a.split("=")[0].split(":")[0].strip() for a in dm.group(2).split(",") if a.strip()]
                funcs.append((dm.group(1), [a for a in args if a not in ("self", "cls")]))
        if not funcs:
            return json.dumps({"filename": "", "code": ""})
        out = [f"import pytest\n\nfrom {module} import " + ", ".join(sorted({n for n, _ in funcs})) + "\n"]
        for name, args in funcs:
            call = ", ".join("None" for _ in args)
            out.append(f"\ndef test_{name}_happy_path():\n    # TODO: replace with realistic inputs and assertions\n"
                       f"    result = {name}({call})\n    assert result is not None\n")
            out.append(f"\ndef test_{name}_rejects_bad_input():\n    # TODO: decide which exception the function should raise\n"
                       f"    with pytest.raises(Exception):\n        {name}({', '.join('object()' for _ in args)})\n")
        fname = "tests/test_" + path.rsplit("/", 1)[-1]
        return json.dumps({"filename": fname, "code": "".join(out)})
