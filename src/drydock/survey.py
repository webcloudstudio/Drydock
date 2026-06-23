"""``drydock survey`` — score a Target's build process against its acceptance criteria.

The Surveyor reads the per-command acceptance-criteria files under
``targets/<Target>/survey/ac/``, evaluates each command's work, and records a reproducible score
per command in ``targets/<Target>/survey/scores.jsonl``. The scoring math (dimension weights →
composite score → band) is deterministic and lives here; an LLM is used only to judge each
acceptance criterion and to synthesize generalized, actionable recommendations. The model emits
JSON; this module computes the scores and writes the files, so tests inject a fake runner and never
spend API credits.

See ``targets/<Target>/survey/RUBRIC.md`` for the human description of the same function.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from drydock.errors import SpecificationError
from drydock.llm import run_prompt
from drydock.prompt_assembly import PromptAssembly, fenced_markdown_part, lines_part, part
from drydock.prompts import load_prompt

SCHEMA = 1
SCORES_FILE = "scores.jsonl"
AC_DIR = "ac"

# Canonical scoring function. RUBRIC.md documents these; this is the source of truth.
DIMENSION_WEIGHTS: dict[str, float] = {"D1": 0.30, "D2": 0.25, "D3": 0.20, "D4": 0.15, "D5": 0.10}
RESULT_VALUE: dict[str, float] = {"pass": 1.0, "partial": 0.5, "fail": 0.0}
# A breach is never "minor" — these flags cap the band regardless of the numeric score.
CAP_FLAGS: frozenset[str] = frozenset({"guardrail-breach", "regression"})

_BANDS: tuple[tuple[int, str], ...] = (
    (90, "SEAWORTHY"),
    (75, "SEA_TRIALS"),
    (60, "TAKING_WATER"),
    (0, "DRY_DOCK"),
)
_BAND_ICON = {"SEAWORTHY": "✓", "SEA_TRIALS": "~", "TAKING_WATER": "!", "DRY_DOCK": "✗"}

_AC_ID = re.compile(r"^[A-Z][A-Z0-9]*-[A-Z0-9]+$")
_H1 = re.compile(r"^#\s+SURVEY-SPEC:\s*(.+?)\s*$", re.MULTILINE)

RunnerFn = Callable[..., object]
TextCallback = Callable[[str], None]


# ---------------------------------------------------------------------------
# Acceptance-criteria specs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AcItem:
    id: str
    criterion: str
    dimension: str  # D1..D5
    check: str  # "assertion" | "judgment"
    weight: float


@dataclass(frozen=True)
class CommandSpec:
    command: str  # e.g. "drydock status"
    goal: str
    ac: list[AcItem]
    path: Path


def survey_dir_for(target_dir: Path) -> Path:
    """The Surveyor workspace for a Target: ``<target>/survey``."""
    return target_dir / "survey"


def _parse_check(token: str) -> str:
    t = token.strip().lower()
    if t in {"a", "assertion"}:
        return "assertion"
    return "judgment"


def parse_ac_file(path: Path) -> CommandSpec:
    """Parse one ``SURVEY-<command>.md`` acceptance-criteria file."""
    text = path.read_text(encoding="utf-8")
    m = _H1.search(text)
    command = m.group(1).strip() if m else path.stem.replace("SURVEY-", "").replace("-", " ")

    goal = ""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip().lower() == "## goal":
            body: list[str] = []
            for nxt in lines[i + 1 :]:
                if nxt.startswith("## "):
                    break
                body.append(nxt)
            goal = " ".join(s.strip() for s in body if s.strip())
            break

    ac: list[AcItem] = []
    for line in lines:
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 6 or not _AC_ID.match(cells[0]):
            continue
        try:
            weight = float(cells[4])
        except ValueError:
            weight = 1.0
        ac.append(
            AcItem(
                id=cells[0],
                criterion=cells[1],
                dimension=cells[2].upper(),
                check=_parse_check(cells[3]),
                weight=weight,
            )
        )
    return CommandSpec(command=command, goal=goal, ac=ac, path=path)


def load_specs(survey_dir: Path, command: str | None = None) -> list[CommandSpec]:
    """Load every ``ac/SURVEY-*.md`` spec, optionally filtered to one command."""
    ac_dir = survey_dir / AC_DIR
    if not ac_dir.is_dir():
        raise SpecificationError(f"no survey acceptance criteria directory: {ac_dir}")
    specs = [parse_ac_file(p) for p in sorted(ac_dir.glob("SURVEY-*.md"))]
    if command:
        want = command.lower()
        specs = [s for s in specs if want in s.command.lower()]
        if not specs:
            raise SpecificationError(f"no survey spec matches command: {command!r}")
    return specs


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def band_for(score: int, flags: list[str] | None = None) -> str:
    base = next(name for threshold, name in _BANDS if score >= threshold)
    if flags and CAP_FLAGS.intersection(flags):
        # Cap at TAKING_WATER: never report a breach as SEAWORTHY/SEA_TRIALS.
        if base in {"SEAWORTHY", "SEA_TRIALS"}:
            return "TAKING_WATER"
    return base


@dataclass
class Scored:
    dimensions: dict[str, float | None]
    assessed: list[str]
    score: int
    provisional: bool


def compute_score(spec: CommandSpec, results: dict[str, str]) -> Scored:
    """Compute dimension and composite scores from per-AC results.

    ``results`` maps AC id → ``pass`` | ``partial`` | ``fail``. AC absent from ``results`` are
    unassessed. Each dimension is the weighted pass-rate of its assessed AC. The composite
    redistributes the dimension weights across the assessed dimensions only.
    """
    spec_dims = {ac.dimension for ac in spec.ac}
    dimensions: dict[str, float | None] = {d: None for d in DIMENSION_WEIGHTS}

    for dim in DIMENSION_WEIGHTS:
        items = [ac for ac in spec.ac if ac.dimension == dim and ac.id in results]
        if not items:
            continue
        earned = sum(ac.weight * RESULT_VALUE.get(results[ac.id], 0.0) for ac in items)
        possible = sum(ac.weight for ac in items)
        dimensions[dim] = round(earned * 100 / possible, 1) if possible else 0.0

    assessed = [d for d, v in dimensions.items() if v is not None]
    if assessed:
        total_w = sum(DIMENSION_WEIGHTS[d] for d in assessed)
        composite = sum(DIMENSION_WEIGHTS[d] * dimensions[d] for d in assessed) / total_w  # type: ignore[operator]
        score = round(composite)
    else:
        score = 0

    provisional = set(assessed) != spec_dims or not assessed
    return Scored(dimensions=dimensions, assessed=assessed, score=score, provisional=provisional)


# ---------------------------------------------------------------------------
# Score records (scores.jsonl)
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")


def _short_head(cwd: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def load_records(survey_dir: Path) -> list[dict]:
    path = survey_dir / SCORES_FILE
    if not path.is_file():
        return []
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        if rec.get("type") == "meta":
            continue
        records.append(rec)
    return records


def append_records(survey_dir: Path, records: list[dict]) -> Path:
    """Append score records, creating the log with a schema meta line if absent."""
    path = survey_dir / SCORES_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        if new_file:
            meta = {
                "schema": SCHEMA,
                "type": "meta",
                "created_at": _now(),
                "rubric": "survey/RUBRIC.md",
                "note": "Append-only survey log. One data record per command per run.",
            }
            fh.write(json.dumps(meta) + "\n")
        for rec in records:
            fh.write(json.dumps(rec) + "\n")
    return path


def latest_per_command(records: list[dict]) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for rec in records:
        cmd = rec.get("command", "?")
        if cmd not in latest or rec.get("recorded_at", "") >= latest[cmd].get("recorded_at", ""):
            latest[cmd] = rec
    return latest


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_scoreboard(records: list[dict], command: str | None = None) -> str:
    latest = latest_per_command(records)
    if command:
        want = command.lower()
        latest = {k: v for k, v in latest.items() if want in k.lower()}

    out: list[str] = ["", "Surveyor scoreboard", ""]
    if not latest:
        out.append("  (no scores yet — run `drydock survey <Target> --run` to score)")
        out.append("")
        return "\n".join(out)

    out.append(f"  {'command':<22} {'score':>5}  {'band':<13} flags")
    out.append(f"  {'-' * 22} {'-' * 5}  {'-' * 13} {'-' * 30}")
    for cmd in sorted(latest):
        rec = latest[cmd]
        icon = _BAND_ICON.get(rec.get("band", ""), "?")
        score = rec.get("score", "—")
        prov = "*" if rec.get("provisional") else " "
        band = rec.get("band", "—")
        flags = ", ".join(rec.get("flags", [])) or "—"
        out.append(f"  {cmd:<22} {score:>4}{prov}  {icon} {band:<11} {flags}")
    out.append("")
    out.append("  * = provisional (not all dimensions assessed)")
    out.append("")

    for cmd in sorted(latest):
        rec = latest[cmd]
        fails = [a for a in rec.get("ac", []) if a.get("result") in ("fail", "partial")]
        actions = rec.get("actions", [])
        if not fails and not actions:
            continue
        out.append(
            f"  {cmd}  ({rec.get('recorded_at', '')}, surveyed {rec.get('surveyed_commit', '?')})"
        )
        for a in fails:
            out.append(f"    [{a.get('result', ''):>7}] {a.get('id', ''):<12} {a.get('note', '')}")
        for act in actions:
            out.append(f"    -> {act}")
        out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Survey run (LLM-assisted scoring)
# ---------------------------------------------------------------------------


def _artifact_inventory(target_dir: Path) -> str:
    blueprint = target_dir / "blueprint"
    lines = [f"- target_dir: {target_dir}"]
    lines.append(f"- MANIFEST.md present: {(target_dir / 'MANIFEST.md').is_file()}")
    if blueprint.is_dir():
        files = sorted(p.name for p in blueprint.glob("*.md"))
        lines.append(f"- blueprint files: {', '.join(files) or '(none)'}")
    return "\n".join(lines)


def _ac_block(specs: list[CommandSpec]) -> str:
    out: list[str] = []
    for spec in specs:
        out.append(f"### {spec.command}")
        out.append(f"goal: {spec.goal}")
        for ac in spec.ac:
            out.append(f"- {ac.id} [{ac.dimension}/{ac.check}/w{ac.weight:g}] {ac.criterion}")
        out.append("")
    return "\n".join(out)


def _assemble_survey_prompt(body: str, *, target: str, inventory: str, ac_block: str) -> str:
    return _assemble_survey_prompt_assembly(
        body,
        target=target,
        inventory=inventory,
        ac_block=ac_block,
    ).rendered_text


def _assemble_survey_prompt_assembly(
    body: str,
    *,
    target: str,
    inventory: str,
    ac_block: str,
) -> PromptAssembly:
    return PromptAssembly(
        parts=(
            part("Prompt body", body + "\n\n", kind="prompt-body"),
            lines_part("Survey job", ["## Survey job", "", f"- TARGET: {target}", ""], kind="job"),
            lines_part(
                "Available artifacts",
                ["### Available artifacts", "", inventory, ""],
                kind="section",
            ),
            lines_part(
                "Acceptance criteria",
                ["### Acceptance criteria to evaluate", "", ac_block, ""],
                kind="section",
            ),
        )
    )


def _parse_survey_json(text: str) -> dict:
    body = text.strip()
    fence = re.search(r"```(?:json)?\s*\n(.*?)\n```", body, re.DOTALL)
    if fence:
        body = fence.group(1).strip()
    start = body.find("{")
    end = body.rfind("}")
    if start == -1 or end == -1:
        raise SpecificationError("survey model output contained no JSON object")
    return json.loads(body[start : end + 1])


def run_survey(
    target: str,
    target_dir: Path,
    *,
    command: str | None = None,
    runner: RunnerFn | None = None,
    on_text: TextCallback | None = None,
    model: str | None = None,
    llm_provider: str | None = None,
    log_dir: Path | None = None,
) -> list[dict]:
    """Score each in-scope command and append one record per command to scores.jsonl."""
    run = runner if runner is not None else run_prompt
    survey_dir = survey_dir_for(target_dir)
    specs = load_specs(survey_dir, command)
    by_command = {s.command: s for s in specs}

    prompt = load_prompt("survey")
    prompt_assembly = _assemble_survey_prompt_assembly(
        prompt.body,
        target=target,
        inventory=_artifact_inventory(target_dir),
        ac_block=_ac_block(specs),
    )
    result = run(
        prompt_assembly.rendered_text,
        target_dir,
        llm=llm_provider,
        model=model or prompt.model,
        command_name="survey",
        parameters={"target": target},
        log_dir=log_dir,
        target=target,
        on_text=on_text,
        prompt_assembly=prompt_assembly,
    )
    if not getattr(result, "ok", False) or not getattr(result, "text", "").strip():
        raise SpecificationError("survey LLM execution failed or returned no output")

    payload = _parse_survey_json(result.text)
    recorded_at = _now()
    head = _short_head(target_dir)
    execution_id = getattr(result, "execution_id", "")

    records: list[dict] = []
    for entry in payload.get("surveys", []):
        cmd = entry.get("command", "")
        spec = by_command.get(cmd) or next(
            (s for s in specs if cmd and cmd.lower() in s.command.lower()), None
        )
        if spec is None:
            continue
        ac_entries = entry.get("ac", [])
        results = {a["id"]: a.get("result", "fail") for a in ac_entries if "id" in a}
        flags = entry.get("flags", [])
        scored = compute_score(spec, results)
        records.append(
            {
                "schema": SCHEMA,
                "recorded_at": recorded_at,
                "command": spec.command,
                "surveyed_commit": head,
                "run_ref": execution_id or "manual",
                "dimensions": scored.dimensions,
                "assessed": scored.assessed,
                "score": scored.score,
                "band": band_for(scored.score, flags),
                "provisional": scored.provisional,
                "flags": flags,
                "ac": ac_entries,
                "actions": entry.get("actions", []),
            }
        )

    if records:
        append_records(survey_dir, records)
    return records


# ---------------------------------------------------------------------------
# Import / regenerate acceptance criteria from a specification directory
# ---------------------------------------------------------------------------


def import_specs(
    target: str,
    target_dir: Path,
    source_path: Path,
    *,
    runner: RunnerFn | None = None,
    on_text: TextCallback | None = None,
    model: str | None = None,
    llm_provider: str | None = None,
    log_dir: Path | None = None,
) -> list[Path]:
    """Re-read a Blueprint/sources directory and (re)generate per-command AC files.

    The model proposes acceptance-criteria file bodies; this module writes them under
    ``survey/ac/`` so file writes stay deterministic and assertable.
    """
    run = runner if runner is not None else run_prompt
    if not source_path.is_dir():
        raise SpecificationError(f"import source directory not found: {source_path}")
    survey_dir = survey_dir_for(target_dir)
    ac_dir = survey_dir / AC_DIR
    ac_dir.mkdir(parents=True, exist_ok=True)

    inventory = []
    for md in sorted(source_path.glob("*.md")):
        inventory.append(md)
    prompt = load_prompt("survey_import")
    prompt_assembly = PromptAssembly(
        parts=(
            part("Prompt body", prompt.body + "\n\n", kind="prompt-body"),
            lines_part(
                "Import job",
                ["## Import job", "", f"- TARGET: {target}", f"- SOURCE: {source_path}", ""],
                kind="job",
            ),
            lines_part("Source specification file header", ["### Source specification files", ""], kind="section"),
            *tuple(
                fenced_markdown_part(
                    md.name,
                    f"#### {md.name}",
                    md.read_text(encoding="utf-8"),
                    role="source file",
                    path=md,
                )
                for md in inventory
            ),
        )
    )
    result = run(
        prompt_assembly.rendered_text,
        target_dir,
        llm=llm_provider,
        model=model or prompt.model,
        command_name="survey import",
        parameters={"target": target, "source": str(source_path)},
        log_dir=log_dir,
        target=target,
        on_text=on_text,
        prompt_assembly=prompt_assembly,
    )
    if not getattr(result, "ok", False) or not getattr(result, "text", "").strip():
        raise SpecificationError("survey import LLM execution failed or returned no output")

    written: list[Path] = []
    for block in re.finditer(
        r"=== (SURVEY-[\w-]+\.md) ===\s*\n(.*?)\n=== END \1 ===", result.text, re.DOTALL
    ):
        name, body = block.group(1), block.group(2).strip() + "\n"
        out = ac_dir / name
        out.write_text(body, encoding="utf-8", newline="\n")
        written.append(out)
    return written
