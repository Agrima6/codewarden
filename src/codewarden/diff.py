from __future__ import annotations

import re
from dataclasses import dataclass, field

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class DiffLine:
    kind: str  # "+", "-", " "
    text: str
    new_no: int | None
    old_no: int | None


@dataclass
class Hunk:
    header: str
    lines: list[DiffLine] = field(default_factory=list)

    def render(self) -> str:
        """Render with real new-file line numbers so the model can cite them."""
        out = [self.header]
        for ln in self.lines:
            num = f"{ln.new_no:>5}" if ln.new_no is not None else "     "
            out.append(f"{num} {ln.kind} {ln.text}")
        return "\n".join(out)


@dataclass
class FileDiff:
    path: str
    hunks: list[Hunk] = field(default_factory=list)
    is_binary: bool = False
    is_deleted: bool = False
    is_new: bool = False

    def commentable_lines(self) -> set[int]:
        """New-file lines GitHub accepts an inline comment on (added or context)."""
        return {ln.new_no for h in self.hunks for ln in h.lines if ln.new_no is not None}

    def added_lines(self) -> dict[int, str]:
        return {ln.new_no: ln.text for h in self.hunks for ln in h.lines if ln.kind == "+" and ln.new_no}

    def line_text(self, no: int) -> str:
        for h in self.hunks:
            for ln in h.lines:
                if ln.new_no == no:
                    return ln.text
        return ""


def parse_diff(text: str) -> list[FileDiff]:
    files: list[FileDiff] = []
    cur: FileDiff | None = None
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("diff --git "):
            m = re.match(r"diff --git a/(.+?) b/(.+)$", line)
            cur = FileDiff(path=m.group(2) if m else "")
            files.append(cur)
        elif cur is not None and line.startswith("new file mode"):
            cur.is_new = True
        elif cur is not None and line.startswith("deleted file mode"):
            cur.is_deleted = True
        elif cur is not None and (line.startswith("Binary files") or line.startswith("GIT binary patch")):
            cur.is_binary = True
        elif cur is not None and line.startswith("+++ "):
            target = line[4:].split("\t")[0]
            if target == "/dev/null":
                cur.is_deleted = True
            elif target.startswith("b/"):
                cur.path = target[2:]
            else:
                cur.path = target
        elif cur is not None and (m := _HUNK_RE.match(line)):
            old_no, new_no = int(m.group(1)), int(m.group(3))
            old_left = int(m.group(2)) if m.group(2) is not None else 1
            new_left = int(m.group(4)) if m.group(4) is not None else 1
            hunk = Hunk(header=line)
            cur.hunks.append(hunk)
            # Hunk bodies are consumed by the counts in the header, so a deleted
            # line whose content starts with "-- " is never mistaken for a file header.
            while (old_left > 0 or new_left > 0) and i + 1 < len(lines):
                body = lines[i + 1]
                if body and body[0] not in "+- \\":
                    break  # header counts were wrong or the diff was truncated; resume header parsing
                i += 1
                if body.startswith("\\"):
                    continue
                kind = body[:1] if body[:1] in "+- " else " "
                content = body[1:]
                if kind == "+":
                    hunk.lines.append(DiffLine("+", content, new_no, None))
                    new_no += 1
                    new_left -= 1
                elif kind == "-":
                    hunk.lines.append(DiffLine("-", content, None, old_no))
                    old_no += 1
                    old_left -= 1
                else:
                    hunk.lines.append(DiffLine(" ", content, new_no, old_no))
                    new_no += 1
                    old_no += 1
                    new_left -= 1
                    old_left -= 1
        i += 1
    return [f for f in files if f.path]
