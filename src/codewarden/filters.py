from __future__ import annotations

import fnmatch

from codewarden.diff import FileDiff
from codewarden.guardrails import sensitive_path


def skip_reason(f: FileDiff, exclude: list[str]) -> str | None:
    if f.is_deleted:
        return "deleted file"
    sensitive = sensitive_path(f.path)
    if sensitive:
        return f"sensitive file ({sensitive}): never sent to a model"
    if f.is_binary:
        return "binary file"
    if not f.hunks:
        return "no textual changes"
    name = f.path.rsplit("/", 1)[-1]
    for pattern in exclude:
        if fnmatch.fnmatch(f.path, pattern) or fnmatch.fnmatch(name, pattern):
            return f"excluded by pattern {pattern!r}"
    return None
