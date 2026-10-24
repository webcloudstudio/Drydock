"""Narrow response normalization. Artifact semantics and retry budgets belong to callers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal

from drydock.artifact_blocks import envelope_spans, is_stray_text, repair_final_artifact_close

OutputFormat = Literal["artifacts", "json"]


@dataclass(frozen=True)
class CleanedOutput:
    text: str
    removed: tuple[str, ...] = ()
    defect: str | None = None
    repaired: tuple[str, ...] = ()


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def load_json(text: str) -> object:
    """Consume a complete JSON value; reject duplicate keys and non-JSON numbers."""
    return json.loads(text, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)


def clean_output(text: str, output_format: OutputFormat) -> CleanedOutput:
    """Strip bounded narration and repair only the exact final artifact-close omission.

    On any ambiguity preserve the entire reply for the caller's existing repair path.
    """
    removed: list[str] = []
    try:
        if output_format == "artifacts":
            candidate, repaired = repair_final_artifact_close(text)
            spans = envelope_spans(candidate)
            for inside, span in spans:
                if not inside and span.strip():
                    if not is_stray_text(span):
                        raise ValueError("content-shaped text outside artifact blocks")
                    removed.append(span)
            return CleanedOutput(
                "".join(span for inside, span in spans if inside or not span.strip()),
                tuple(removed),
                repaired=repaired,
            )
        if output_format != "json":
            raise ValueError(f"unsupported output format: {output_format}")
        body = text.strip()
        # Locate only an object/array beginning a line, optionally in one JSON fence.
        match = re.search(r"(?m)^(?:```(?:json)?[ \t]*\n)?[ \t]*(?=[{\[])", body)
        if match is None:
            raise ValueError("missing JSON object or array")
        prefix = body[: match.start()]
        fenced = body[match.start() :].startswith("```")
        start = match.end()
        decoder = json.JSONDecoder(
            object_pairs_hook=_unique_object, parse_constant=_invalid_constant
        )
        _, end = decoder.raw_decode(body, start)
        suffix = body[end:]
        if fenced:
            closing = re.match(r"\s*```", suffix)
            if closing is None:
                raise ValueError("unclosed JSON fence")
            suffix = suffix[closing.end() :]
        for span in (prefix, suffix):
            if span.strip():
                if re.match(r'^(?:"|-?\d|-?Infinity\b|NaN\b|true\b|false\b|null\b)', span.strip()):
                    raise ValueError("additional JSON value outside payload")
                if not is_stray_text(span):
                    raise ValueError("content-shaped text outside JSON payload")
                removed.append(span)
        if fenced:
            removed.append("JSON code fence")
        return CleanedOutput(body[start:end], tuple(removed))
    except ValueError as exc:
        return CleanedOutput(text, defect=str(exc))


def parse_json_output(text: str) -> object:
    cleaned = clean_output(text, "json")
    if cleaned.defect:
        raise ValueError(cleaned.defect)
    return load_json(cleaned.text)
