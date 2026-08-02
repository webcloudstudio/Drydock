"""Canonical ``## Questions`` contract for Blueprint and Sea Trials Markdown."""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

from drydock.errors import SpecificationError

QUESTIONS_HEADING = "## Questions"
QUESTION_STATUSES = frozenset({"open", "answered"})
QUESTION_ORIGINS = frozenset({"plan", "build", "analyze-questionnaire"})
QUESTION_SEVERITIES = frozenset({"low", "material", "blocking"})

_SECTION_RE = re.compile(r"^## Questions\s*$\n(?P<body>.*?)(?=^##\s+|\Z)", re.MULTILINE | re.DOTALL)
_ALTERNATE_HEADING_RE = re.compile(
    r"^(?:##\s+(?:Open\s+Questions?|Question)|QUESTIONS:)\s*$", re.MULTILINE | re.IGNORECASE
)
_QUESTION_HEADER_RE = re.compile(
    r"^###\s+(?P<id>Q-[A-Za-z0-9][A-Za-z0-9._-]*):\s*(?P<name>.+?)\s*$",
    re.MULTILINE,
)
_FIELD_RE = re.compile(
    r"^-\s+(?P<key>Origin|Status|Severity):\s*(?P<value>.*?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(frozen=True)
class MarkdownQuestion:
    question_id: str
    name: str
    origin: str
    status: str
    question: str
    answer: str
    severity: str = "blocking"


def _subsection(body: str, heading: str) -> str:
    match = re.search(
        rf"^####\s+{re.escape(heading)}\s*$\n(?P<body>.*?)(?=^####\s+|\Z)",
        body,
        re.MULTILINE | re.DOTALL,
    )
    return match.group("body").strip() if match else ""


def parse_questions(text: str, *, source: str = "<memory>") -> tuple[MarkdownQuestion, ...]:
    """Parse and validate the canonical Questions section.

    The section is optional for compatibility with non-governed Markdown. Call
    :func:`validate_questions_document` when a governed artifact requires it.
    """
    alternate = _ALTERNATE_HEADING_RE.search(text)
    if alternate:
        raise SpecificationError(
            f"{source} uses non-canonical question heading {alternate.group(0)!r}; "
            "use exactly '## Questions'"
        )
    section = _SECTION_RE.search(text)
    if not section:
        return ()
    body = section.group("body").strip()
    semantic_body = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL).strip()
    if not semantic_body or " ".join(semantic_body.split()).rstrip(".").lower() in {
        "- none",
        "none",
    }:
        return ()

    headers = list(_QUESTION_HEADER_RE.finditer(body))
    if not headers:
        raise SpecificationError(
            f"{source} ## Questions must contain '- None.' or one or more "
            "'### Q-<id>: <name>' records"
        )

    questions: list[MarkdownQuestion] = []
    seen: set[str] = set()
    for index, header in enumerate(headers):
        stop = headers[index + 1].start() if index + 1 < len(headers) else len(body)
        record = body[header.end() : stop].strip()
        question_id = header.group("id")
        if question_id in seen:
            raise SpecificationError(f"{source} has duplicate question id {question_id!r}")
        seen.add(question_id)
        fields = {
            match.group("key").lower(): match.group("value").strip()
            for match in _FIELD_RE.finditer(record)
        }
        origin = fields.get("origin", "")
        status = fields.get("status", "")
        severity = fields.get("severity", "blocking").lower()
        question = _subsection(record, "Question")
        answer = _subsection(record, "Answer")
        if origin not in QUESTION_ORIGINS:
            raise SpecificationError(
                f"{source} question {question_id} has invalid Origin {origin!r}; expected "
                + ", ".join(sorted(QUESTION_ORIGINS))
            )
        if status not in QUESTION_STATUSES:
            raise SpecificationError(
                f"{source} question {question_id} has invalid Status {status!r}; expected "
                + ", ".join(sorted(QUESTION_STATUSES))
            )
        if severity not in QUESTION_SEVERITIES:
            raise SpecificationError(
                f"{source} question {question_id} has invalid Severity {severity!r}; expected "
                + ", ".join(sorted(QUESTION_SEVERITIES))
            )
        if not question:
            raise SpecificationError(f"{source} question {question_id} has no #### Question text")
        if status == "answered" and not answer:
            raise SpecificationError(
                f"{source} question {question_id} is answered but has no #### Answer text"
            )
        if status == "open" and answer:
            raise SpecificationError(
                f"{source} question {question_id} has answer text but Status is open"
            )
        questions.append(
            MarkdownQuestion(
                question_id=question_id,
                name=header.group("name").strip(),
                origin=origin,
                status=status,
                question=question,
                answer=answer,
                severity=severity,
            )
        )
    return tuple(questions)


def validate_questions_document(
    text: str,
    *,
    source: str = "<memory>",
    require_first_section: bool = False,
) -> tuple[MarkdownQuestion, ...]:
    """Require the canonical section and optionally its first-section placement."""
    questions = parse_questions(text, source=source)
    section = _SECTION_RE.search(text)
    if not section:
        raise SpecificationError(f"{source} missing required '## Questions' section")
    if require_first_section:
        first = re.search(r"^##\s+.+$", text, re.MULTILINE)
        if first is None or first.start() != section.start():
            raise SpecificationError(
                f"{source} must place '## Questions' before every other level-two section"
            )
    return questions


def render_questions(questions: tuple[MarkdownQuestion, ...]) -> str:
    lines = [QUESTIONS_HEADING, ""]
    if not questions:
        return "\n".join([*lines, "- None.", ""])
    for item in questions:
        lines.extend([
            f"### {item.question_id}: {item.name}",
            "",
            f"- Origin: {item.origin}",
            f"- Severity: {item.severity.title()}",
            f"- Status: {item.status}",
            "",
            "#### Question",
            "",
            item.question,
            "",
            "#### Answer",
            "",
        ])
        if item.answer:
            lines.extend([item.answer, ""])
    return "\n".join(lines).rstrip() + "\n"


def replace_questions_section(text: str, questions: tuple[MarkdownQuestion, ...]) -> str:
    section = _SECTION_RE.search(text)
    if not section:
        raise SpecificationError("Document has no canonical ## Questions section")
    replacement = render_questions(questions).rstrip()
    return text[: section.start()] + replacement + "\n\n" + text[section.end() :].lstrip("\n")


def normalize_questions_first(text: str, *, source: str = "<memory>") -> str:
    """Move an existing canonical Questions section after the typed metadata table."""
    section = _SECTION_RE.search(text)
    if section is None:
        raise SpecificationError(f"{source} missing required '## Questions' section")
    body_lines = section.group("body").strip().splitlines()
    trailing_lines = body_lines[1:] if body_lines else []
    if (
        body_lines
        and " ".join(body_lines[0].split()).rstrip(".").lower() == "- none"
        and any(line.strip() for line in trailing_lines)
        and all(not line.strip() or line.lstrip().startswith("|") for line in trailing_lines)
    ):
        # Some SCREEN emitters place their route/navigation table after an already empty Questions
        # section. The section parser correctly sees that table as non-question content. Move this
        # narrowly recognized table back into the metadata header before validating and ordering.
        trailing_table = "\n".join(trailing_lines).strip()
        text = (
            text[: section.start()]
            + trailing_table
            + "\n\n## Questions\n\n- None.\n\n"
            + text[section.end() :].lstrip("\n")
        )
        section = _SECTION_RE.search(text)
        assert section is not None
    parse_questions(text, source=source)
    stripped = text[: section.start()] + text[section.end() :].lstrip("\n")
    lines = stripped.splitlines()
    insert_at = 1
    table_started = False
    for index, line in enumerate(lines[1:], start=1):
        if line.lstrip().startswith("|"):
            table_started = True
            insert_at = index + 1
            continue
        if table_started and not line.strip():
            # A SCREEN header may contain a second route/navigation table separated from the
            # typed metadata table by one blank line. Questions belongs after both tables.
            continue
        if table_started:
            break
    section_text = section.group(0).strip()
    before = "\n".join(lines[:insert_at]).rstrip()
    after = "\n".join(lines[insert_at:]).lstrip()
    parts = [before, section_text]
    if after:
        parts.append(after)
    return "\n\n".join(parts).rstrip() + "\n"


def answer_question(path: Path, question_id: str, answer: str) -> MarkdownQuestion:
    """Atomically answer one question in its authoritative Markdown artifact."""
    value = answer.strip()
    if not value:
        raise SpecificationError("Question answer must not be empty")
    text = path.read_text(encoding="utf-8")
    questions = list(parse_questions(text, source=str(path)))
    for index, item in enumerate(questions):
        if item.question_id == question_id:
            updated = replace(item, status="answered", answer=value)
            questions[index] = updated
            break
    else:
        raise SpecificationError(f"Unknown question {question_id!r} in {path}")
    rendered = replace_questions_section(text, tuple(questions))
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, newline="\n"
    ) as handle:
        handle.write(rendered)
        temporary = Path(handle.name)
    temporary.replace(path)
    return updated


def append_question(path: Path, question: MarkdownQuestion) -> bool:
    """Atomically append a non-duplicate record to a governed Questions section."""
    text = path.read_text(encoding="utf-8")
    questions = list(parse_questions(text, source=str(path)))
    if any(item.question_id == question.question_id for item in questions):
        return False
    questions.append(question)
    rendered = replace_questions_section(text, tuple(questions))
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, newline="\n"
    ) as handle:
        handle.write(rendered)
        temporary = Path(handle.name)
    temporary.replace(path)
    return True
