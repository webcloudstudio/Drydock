#!/usr/bin/env python3
"""check_disclosure.py — backstop lint for disclosure safety.

Scans a draft's BODY (frontmatter is skipped) for patterns that should never be
published, plus project-specific banned terms read from blog/DISCLOSURE.md.

Exit code 0 = clean, 1 = findings. This is a backstop, not a substitute for the
human review in GENERATION.md.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DISCLOSURE = ROOT / "blog" / "DISCLOSURE.md"

# Built-in patterns: (label, regex)
BUILTIN = [
    ("Anthropic/OpenAI-style API key", r"sk-[A-Za-z0-9]{16,}"),
    ("AWS access key id", r"AKIA[0-9A-Z]{16}"),
    ("Private key block", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("Email address", r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    ("IPv4 address", r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    ("Absolute filesystem path", r"(?:/[A-Za-z0-9_.-]+){3,}"),
    ("Source filename", r"\b[\w-]+\.(?:py|ts|tsx|js|rs|go|java|rb|c|cpp|h)\b"),
    ("Code call shape", r"\b[a-z_][a-z0-9_]*\([a-z_=]"),
    ("Windows path", r"[A-Za-z]:\\[\\\w.-]+"),
]


def load_banned_terms() -> list[str]:
    """Read extra regexes from the ```banned-regex``` block in DISCLOSURE.md."""
    if not DISCLOSURE.exists():
        return []
    text = DISCLOSURE.read_text(encoding="utf-8")
    m = re.search(r"```banned-regex\n(.*?)```", text, re.DOTALL)
    if not m:
        return []
    return [ln.strip() for ln in m.group(1).splitlines() if ln.strip()]


def strip_frontmatter(text: str) -> str:
    """Return the body, dropping a leading --- ... --- YAML block."""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            nl = text.find("\n", end + 1)
            return text[nl + 1 :] if nl != -1 else ""
    return text


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_disclosure.py <draft.md>", file=sys.stderr)
        return 2
    path = Path(argv[1])
    body = strip_frontmatter(path.read_text(encoding="utf-8"))

    patterns = list(BUILTIN) + [("Banned term", t) for t in load_banned_terms()]
    findings: list[str] = []
    for ln_no, line in enumerate(body.splitlines(), 1):
        # Skip fenced code and inline-code spans: those are illustrative, but a
        # published devnote should not contain code anyway, so flag fences too.
        for label, rx in patterns:
            try:
                if re.search(rx, line):
                    findings.append(f"  line {ln_no}: {label} -> {line.strip()[:80]}")
            except re.error:
                pass  # tolerate a malformed user regex

    if findings:
        print(f"DISCLOSURE LINT: {len(findings)} potential issue(s) in {path.name}:")
        print("\n".join(findings))
        return 1
    print(f"DISCLOSURE LINT: clean — {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
