"""Guardrails: controls around the model, in four layers.

    INPUT   what may be sent to a model          (sensitive files, secrets, PII, injected instructions)
    MODEL   what is accepted back from a model   (schema, grounding in the diff, confidence, caps, duplicates)
    OUTPUT  what may be published                (mentions, links, HTML, leaked secrets, unsafe fix suggestions)
    ACTION  what the tool may do on GitHub       (comment-only, explicit confirmation, rate limit)

Every rule that fires produces a GuardEvent, stored with the review and shown in the dashboard.
"""
from __future__ import annotations

import fnmatch
import re
from dataclasses import asdict, dataclass

from codewarden.redact import _PATTERNS as SECRET_PATTERNS

ZWSP = "​"


@dataclass
class GuardEvent:
    layer: str   # input | model | output | action
    rule: str
    action: str  # skipped | redacted | masked | neutralized | flagged | dropped | sanitized | removed | blocked
    where: str = ""
    detail: str = ""
    count: int = 1

    def to_dict(self) -> dict:
        return asdict(self)


# Metadata the dashboard renders. "code" points at the implementation so each rule can be inspected.
RULES: list[dict] = [
    {"id": "sensitive_files", "layer": "input", "title": "Sensitive files are never sent",
     "what": "Files such as .env, private keys, credentials and Terraform state are skipped entirely.",
     "code": "guardrails.py: sensitive_path()"},
    {"id": "secret_redaction", "layer": "input", "title": "Secret redaction",
     "what": "API keys, tokens, private keys and password literals are replaced with placeholders before any model call.",
     "code": "redact.py + guardrails.py: prepare_for_model()"},
    {"id": "pii_masking", "layer": "input", "title": "PII masking",
     "what": "Email addresses, phone numbers, card numbers (Luhn-checked) and Aadhaar-style IDs are masked.",
     "code": "guardrails.py: mask_pii()"},
    {"id": "injection_detection", "layer": "input", "title": "Prompt-injection detection",
     "what": "Instruction-like text in the diff, PR text or retrieved code is flagged; in PR text and retrieved code it is also neutralised. Hits in changed lines become findings.",
     "code": "guardrails.py: detect_injection()"},
    {"id": "untrusted_data", "layer": "input", "title": "Untrusted-data prompt",
     "what": "The system prompt declares the PR, diff and retrieved code to be data, never instructions.",
     "code": "prompts.py: SYSTEM_PROMPT"},
    {"id": "schema_validation", "layer": "model", "title": "Output schema validation",
     "what": "Model output must parse into the findings schema. Malformed or incomplete findings are dropped, and the model's output is never executed.",
     "code": "parsing.py: parse_findings()"},
    {"id": "line_grounding", "layer": "model", "title": "Grounded in the diff",
     "what": "A finding must point at a real changed line. Findings that cannot be anchored are kept out of inline comments.",
     "code": "review.py: _anchor()"},
    {"id": "confidence_filter", "layer": "model", "title": "Confidence and severity thresholds",
     "what": "Findings below the configured confidence or severity are not published.",
     "code": "review.py: review_diff()"},
    {"id": "comment_cap", "layer": "model", "title": "Comment cap and dedupe",
     "what": "At most N comments per review, highest severity first, and findings already reported on earlier pushes are not repeated.",
     "code": "review.py + report.py: fingerprint"},
    {"id": "output_sanitization", "layer": "output", "title": "Output sanitisation",
     "what": "Model text is stripped of @mentions (no surprise pings), images, external links, HTML, and is length-limited before it is published.",
     "code": "guardrails.py: sanitize_output()"},
    {"id": "output_secret_scrub", "layer": "output", "title": "Secret scrub on output",
     "what": "If a model echoes something that looks like a credential, it is redacted before publishing.",
     "code": "guardrails.py: sanitize_output()"},
    {"id": "unsafe_suggestion", "layer": "output", "title": "Unsafe fix suggestions blocked",
     "what": "One-click replacements that add dangerous code (shell pipes, eval/exec, TLS off, chmod 777 ...) are removed.",
     "code": "guardrails.py: unsafe_replacement()"},
    {"id": "comment_only", "layer": "action", "title": "Comment-only reviews",
     "what": "CodeWarden can only post review comments. It never approves, requests changes, merges or pushes.",
     "code": "github.py: ALLOWED_REVIEW_EVENTS"},
    {"id": "server_confirmation", "layer": "action", "title": "Explicit confirmation to post",
     "what": "Posting to GitHub needs a confirmation that the server checks, not just the browser.",
     "code": "services.py: post_to_github()"},
    {"id": "post_rate_limit", "layer": "action", "title": "Posting rate limit",
     "what": "A cap on reviews posted per hour stops a loop or a bug from flooding a repository.",
     "code": "services.py: PostingLimiter"},
]
RULE_IDS = {r["id"] for r in RULES}

# ---- input: sensitive files ---------------------------------------------------------------------
_SENSITIVE = [".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore", "id_rsa", "id_rsa.*",
              "id_ed25519", "id_ed25519.*", "id_dsa", "*.tfstate", "*.tfstate.*", ".npmrc", ".pypirc", ".netrc",
              "credentials", "credentials.*", "secrets.*", "secret.*", "service-account*.json", "*.kdbx", ".htpasswd"]
_SAFE_SENSITIVE = {".env.example", ".env.sample", ".env.template", ".env.dist"}


def sensitive_path(path: str) -> str | None:
    name = path.rsplit("/", 1)[-1].lower()
    if name in _SAFE_SENSITIVE:
        return None
    for pattern in _SENSITIVE:
        if fnmatch.fnmatch(name, pattern):
            return pattern
    return None


# ---- input: secrets and PII ---------------------------------------------------------------------
def redact_secrets_counted(text: str) -> tuple[str, int]:
    total = 0
    for pattern, repl in SECRET_PATTERNS:
        text, n = pattern.subn(repl, text)
        total += n
    return text, total


_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r"(?<![\w.])(?:\+\d{1,3}[ -]?\d{4,5}[ -]?\d{4,6}|\(?\b\d{3}\)?[-. ]\d{3}[-. ]\d{4})\b")
_CARD = re.compile(r"\b(?:\d{4}[ -]\d{4}[ -]\d{4}[ -]\d{1,7}|\d{15,16})\b")  # grouped, or 15-16 contiguous digits: not epoch timestamps
_AADHAAR = re.compile(r"\b\d{4} \d{4} \d{4}\b")


def _luhn(number: str) -> bool:
    digits = [int(c) for c in number if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def mask_pii(text: str) -> tuple[str, dict[str, int]]:
    found: dict[str, int] = {}

    def sub(kind: str, pattern: re.Pattern, placeholder: str, check=None):
        nonlocal text

        def repl(m: re.Match) -> str:
            if check and not check(m.group(0)):
                return m.group(0)
            found[kind] = found.get(kind, 0) + 1
            return placeholder

        text = pattern.sub(repl, text)

    sub("card number", _CARD, "[CARD]", _luhn)
    sub("Aadhaar-style ID", _AADHAAR, "[ID_NUMBER]")
    sub("email", _EMAIL, "[EMAIL]")
    sub("phone number", _PHONE, "[PHONE]")
    return text, found


# ---- input: prompt injection --------------------------------------------------------------------
_INJECTION = [
    (re.compile(r"ignore\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier)\s+(?:instructions?|prompts?|rules?)", re.I), "ignore-instructions"),
    (re.compile(r"disregard\s+(?:all\s+|the\s+)?(?:previous|prior|above|system)\b", re.I), "disregard-instructions"),
    (re.compile(r"\byou\s+are\s+now\b|\bact\s+as\s+(?:an?\s+)?(?:unrestricted|jailbroken|different)", re.I), "role-override"),
    (re.compile(r"(?:reveal|print|show|repeat)\s+(?:your\s+|the\s+)?(?:system\s+prompt|instructions|hidden\s+prompt)", re.I), "prompt-exfiltration"),
    (re.compile(r"\b(?:approve|accept|merge)\s+(?:this|the)\s+(?:pr|pull\s+request|change)\b", re.I), "approve-request"),
    (re.compile(r"(?:do\s+not|don'?t)\s+(?:report|flag|mention)\s+(?:any\s+)?(?:issues?|findings?|bugs?|vulnerabilit)", re.I), "suppress-findings"),
    (re.compile(r"return\s+an?\s+empty\s+(?:findings?\s+)?(?:array|list)|\"findings\"\s*:\s*\[\s*\]", re.I), "force-empty-output"),
    (re.compile(r"</?\s*system\s*>|\[/?INST\]|<\|im_(?:start|end)\|>|###\s*system", re.I), "fake-system-tags"),
    (re.compile(r"\bnew\s+instructions?\s*:", re.I), "new-instructions"),
]
INJECTION_TITLE = "Prompt-injection text in the change"
_NEUTRALIZED = "[instruction-like text removed]"


def detect_injection(text: str) -> list[str]:
    return sorted({label for pattern, label in _INJECTION if pattern.search(text)})


def neutralize_injection(text: str) -> tuple[str, list[str]]:
    hits: list[str] = []
    for pattern, label in _INJECTION:
        text, n = pattern.subn(_NEUTRALIZED, text)
        if n:
            hits.append(label)
    return text, hits


def prepare_for_model(text: str, *, redact_secrets: bool, pii: bool, where: str) -> tuple[str, list[GuardEvent]]:
    events: list[GuardEvent] = []
    if redact_secrets:
        text, n = redact_secrets_counted(text)
        if n:
            events.append(GuardEvent("input", "secret_redaction", "redacted", where, f"{n} credential-like value(s) replaced with placeholders", n))
    if pii:
        text, found = mask_pii(text)
        if found:
            total = sum(found.values())
            events.append(GuardEvent("input", "pii_masking", "masked", where, ", ".join(f"{n} {k}" for k, n in found.items()), total))
    return text, events


# ---- output ---------------------------------------------------------------------------------------
_MENTION = re.compile(r"(?<![\w`@/.])@([A-Za-z0-9][\w-]{0,38})")
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MDLINK = re.compile(r"\[([^\]]+)\]\((?:https?://|//)[^)]*\)")
_HTML = re.compile(r"</?[A-Za-z][^>]{0,200}>|<!--.*?-->", re.S)
_URL = re.compile(r"https?://[^\s)>\]]+")
_TRUSTED_HOSTS = ("github.com", "owasp.org", "cwe.mitre.org", "docs.python.org", "developer.mozilla.org", "nvd.nist.gov")
MAX_LEN = {"title": 120, "explanation": 1200, "suggestion": 800}


def sanitize_output(text: str, field: str = "explanation") -> tuple[str, dict[str, int]]:
    acts: dict[str, int] = {}

    def bump(name: str, n: int = 1):
        acts[name] = acts.get(name, 0) + n

    text, n = _IMAGE.subn("[image removed]", text)
    if n:
        bump("image removed", n)
    text, n = _MDLINK.subn(r"\1", text)
    if n:
        bump("link removed", n)
    text, n = _HTML.subn("", text)
    if n:
        bump("HTML stripped", n)

    def url_sub(m: re.Match) -> str:
        host = re.sub(r"^https?://", "", m.group(0)).split("/")[0].lower().split(":")[0]
        if any(host == t or host.endswith("." + t) for t in _TRUSTED_HOSTS):
            return m.group(0)
        bump("link removed")
        return "[link removed]"

    text = _URL.sub(url_sub, text)
    text, n = _MENTION.subn(lambda m: "@" + ZWSP + m.group(1), text)
    if n:
        bump("@mention neutralised", n)
    text, n = redact_secrets_counted(text)
    if n:
        bump("secret scrubbed", n)
    limit = MAX_LEN.get(field, 1200)
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
        bump("truncated")
    return text.strip(), acts


_UNSAFE_REPLACEMENT = [
    (re.compile(r"\b(?:curl|wget)\b.*\|\s*(?:sudo\s+)?(?:ba|z)?sh\b", re.I), "pipes a download into a shell"),
    (re.compile(r"\brm\s+-[a-z]*r[a-z]*f|\brm\s+-[a-z]*f[a-z]*r", re.I), "recursive delete"),
    (re.compile(r"\bchmod\s+(?:-R\s+)?0?777\b"), "world-writable permissions"),
    (re.compile(r"\b(?:eval|exec)\s*\("), "dynamic code execution"),
    (re.compile(r"\bos\.system\s*\(|\bshell\s*=\s*True"), "shell execution"),
    (re.compile(r"verify\s*=\s*False|rejectUnauthorized\s*:\s*false|InsecureSkipVerify\s*:\s*true", re.I), "TLS verification disabled"),
    (re.compile(r"\bpickle\.loads?\s*\(|yaml\.load\s*\((?!.*Loader)"), "unsafe deserialisation"),
    (re.compile(r"--no-verify|--insecure|--no-check-certificate"), "security check disabled"),
    (re.compile(r"(?:password|secret|api[_-]?key|token)\s*=\s*[\"'][^\"']{4,}[\"']", re.I), "hard-coded credential"),
]


def unsafe_replacement(code: str, original: str = "") -> str | None:
    """Reason a suggested replacement should not be offered, or None. Only flags danger the fix would introduce."""
    for pattern, reason in _UNSAFE_REPLACEMENT:
        if pattern.search(code) and not pattern.search(original):
            return reason
    return None


def summarise(events: list[GuardEvent]) -> dict[str, int]:
    out: dict[str, int] = {}
    for e in events:
        out[e.rule] = out.get(e.rule, 0) + e.count
    return out
