from __future__ import annotations

import json
import re

from codewarden.models import normalize_category, normalize_severity

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)


def _extract_json(text: str):
    text = _FENCE.sub("", text.strip()).strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        a, b = text.find(open_c), text.rfind(close_c)
        if a != -1 and b > a:
            try:
                return json.loads(text[a:b + 1])
            except ValueError:
                continue
    return None


def parse_findings(text: str) -> list[dict]:
    """Turn raw model output into validated finding dicts. Never raises on bad model output."""
    data = _extract_json(text)
    if isinstance(data, dict):
        data = data.get("findings", data.get("reviews"))
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            line = int(item.get("line", item.get("lineNumber")))
        except (TypeError, ValueError):
            continue
        title = str(item.get("title") or "").strip()
        explanation = str(item.get("explanation") or item.get("reviewComment") or "").strip()
        if not (title or explanation) or line < 1:
            continue
        try:
            confidence = min(1.0, max(0.0, float(item.get("confidence", 0.7))))
        except (TypeError, ValueError):
            confidence = 0.7
        out.append({
            "line": line,
            "severity": normalize_severity(item.get("severity")),
            "category": normalize_category(item.get("category")),
            "title": title or explanation[:80],
            "explanation": explanation or title,
            "suggestion": str(item.get("suggestion") or "").strip(),
            "confidence": confidence,
        })
    return out
