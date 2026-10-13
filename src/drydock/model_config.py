"""Per-model token accounting and provider argument rules, read from ``model_config.jsonl``.

One JSON object per line. ``kind: provider`` rows carry the CLI arguments that shape a
provider's tool surface (``build_args`` for tool-using runs, ``text_args`` for text-only runs).
``kind: model`` rows carry everything Drydock needs to cost and route a prompt for a model
family: the tokenizer ratio (``bytes_per_token``), the CLI's fixed request payload
(``overhead_tokens`` by run mode), the stacking target, the warning threshold, and an optional
price-tier limit with the model to escalate to when a prompt would cross it.

A model name matches the first ``model`` row, in file order, whose ``match`` list contains a
substring of the lowercased name; ``*`` matches anything. Order is therefore significant:
``haiku-4`` precedes the bare ``haiku`` alias, which selects the current Haiku.

The packaged seed lives in Rigging. The live copy is user configuration, created from the seed
on first use beside the Drydock ``.env``; ``DRYDOCK_MODEL_CONFIG`` names another file. Only
``drydock config calibrate --apply`` rewrites the live copy, from measured evidence.
"""

from __future__ import annotations

import json
import math
import os
import shutil
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from drydock.errors import ConfigurationError

MODEL_CONFIG_NAME = "model_config.jsonl"
CALIBRATION_NAME = "model_calibration.jsonl"

#: A prompt whose estimated request size exceeds this fraction of a model's
#: ``prompt_limit_tokens`` runs on the row's ``escalate_model``. Token estimates are not exact;
#: the margin absorbs the difference.
ESCALATION_FRACTION = 0.98

#: Measured values that differ from the configured value by more than this fraction are
#: reported as drift and proposed by ``drydock config calibrate``.
DRIFT_FRACTION = 0.05

#: Observations needed before a measured ratio is proposed.
MIN_CALIBRATION_RUNS = 3

#: Run modes. ``build`` runs carry the provider's tool schemas; ``text`` runs carry none.
RUN_MODES = ("build", "text")

_REQUIRED_MODEL_FIELDS = (
    "provider",
    "match",
    "bytes_per_token",
    "overhead_tokens",
    "prompt_target_tokens",
    "prompt_warning_tokens",
)


@dataclass(frozen=True)
class ProviderProfile:
    provider: str
    build_args: tuple[str, ...] = ()
    text_args: tuple[str, ...] = ()

    def args(self, allow_tools: bool) -> tuple[str, ...]:
        return self.build_args if allow_tools else self.text_args


@dataclass(frozen=True)
class ModelProfile:
    provider: str
    match: tuple[str, ...]
    bytes_per_token: float
    overhead_tokens: Mapping[str, int]
    prompt_target_tokens: int
    prompt_warning_tokens: int
    prompt_limit_tokens: int | None = None
    escalate_model: str | None = None
    thinking: str = "effort"
    measured: Mapping[str, Any] | None = None
    index: int = 0

    @property
    def label(self) -> str:
        return "|".join(self.match)

    def overhead(self, allow_tools: bool) -> int:
        return int(self.overhead_tokens.get("build" if allow_tools else "text", 0))

    def estimate(self, byte_count: int) -> int:
        """Tokens this model's tokenizer produces for ``byte_count`` bytes of prompt."""
        if byte_count <= 0:
            return 0
        return math.ceil(byte_count / self.bytes_per_token)

    def request_tokens(self, byte_count: int, allow_tools: bool) -> int:
        """Estimated first-request size: the prompt plus the CLI's fixed payload."""
        return self.estimate(byte_count) + self.overhead(allow_tools)

    def matches(self, model: str) -> bool:
        name = model.lower().strip()
        return any(marker == "*" or marker in name for marker in self.match)


@dataclass(frozen=True)
class ModelConfig:
    path: Path
    providers: Mapping[str, ProviderProfile]
    models: tuple[ModelProfile, ...]
    rows: tuple[dict[str, Any], ...] = field(default=(), repr=False)

    def model(self, name: str | None) -> ModelProfile:
        for profile in self.models:
            if profile.matches(name or ""):
                return profile
        raise ConfigurationError(
            f"No model_config row matches model {name!r} in {self.path}.\n"
            '  Add a row, or a catch-all row with "match": ["*"].'
        )

    def provider(self, name: str) -> ProviderProfile:
        return self.providers.get(name, ProviderProfile(provider=name))


@dataclass(frozen=True)
class Escalation:
    from_model: str
    to_model: str
    estimated_tokens: int
    limit_tokens: int

    def describe(self) -> str:
        return (
            f"upgraded=prompt_limit {self.from_model}->{self.to_model} "
            f"({self.estimated_tokens:,} > {ESCALATION_FRACTION:.0%} of {self.limit_tokens:,})"
        )


def seed_path() -> Path:
    from drydock.paths import get_rigging_root

    return get_rigging_root() / MODEL_CONFIG_NAME


def config_path() -> Path:
    override = os.environ.get("DRYDOCK_MODEL_CONFIG", "").strip()
    if override:
        return Path(override).expanduser()
    from drydock.config import _config_path

    return _config_path().parent / MODEL_CONFIG_NAME


_CACHE: dict[Path, tuple[tuple[int, int], ModelConfig]] = {}


def load(path: Path | None = None) -> ModelConfig:
    """Load the live model configuration, creating it from the packaged seed when absent."""
    target = path or config_path()
    if not target.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(seed_path(), target)
    stat = target.stat()
    mtime = (stat.st_mtime_ns, stat.st_size)
    cached = _CACHE.get(target)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    config = parse(target.read_text(encoding="utf-8"), target)
    _CACHE[target] = (mtime, config)
    return config


def parse(text: str, path: Path) -> ModelConfig:
    providers: dict[str, ProviderProfile] = {}
    models: list[ModelProfile] = []
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ConfigurationError(f"{path}:{number}: invalid JSON: {exc.msg}") from None
        if not isinstance(row, dict):
            raise ConfigurationError(f"{path}:{number}: each line must be a JSON object.")
        rows.append(row)
        kind = row.get("kind")
        if kind == "provider":
            name = str(row.get("provider") or "").strip()
            if not name:
                raise ConfigurationError(f"{path}:{number}: provider row has no provider.")
            providers[name] = ProviderProfile(
                provider=name,
                build_args=tuple(str(a) for a in row.get("build_args") or ()),
                text_args=tuple(str(a) for a in row.get("text_args") or ()),
            )
        elif kind == "model":
            models.append(_model_row(row, path, number, len(rows) - 1))
        else:
            raise ConfigurationError(f"{path}:{number}: kind must be 'provider' or 'model'.")
    if not models:
        raise ConfigurationError(f"{path}: no model rows.")
    return ModelConfig(path=path, providers=providers, models=tuple(models), rows=tuple(rows))


def _model_row(row: Mapping[str, Any], path: Path, number: int, index: int) -> ModelProfile:
    missing = [name for name in _REQUIRED_MODEL_FIELDS if row.get(name) in (None, "", [])]
    if missing:
        raise ConfigurationError(f"{path}:{number}: model row missing {', '.join(missing)}.")
    try:
        bytes_per_token = float(row["bytes_per_token"])
        target = int(row["prompt_target_tokens"])
        warning = int(row["prompt_warning_tokens"])
        limit = row.get("prompt_limit_tokens")
        limit = int(limit) if limit is not None else None
        overhead_values = {str(k): int(v) for k, v in dict(row["overhead_tokens"]).items()}
    except (TypeError, ValueError):
        raise ConfigurationError(
            f"{path}:{number}: token and ratio values must be numbers."
        ) from None
    if bytes_per_token <= 0 or target <= 0 or warning <= 0 or (limit is not None and limit <= 0):
        raise ConfigurationError(f"{path}:{number}: token and ratio values must be positive.")
    overhead = row["overhead_tokens"]
    if not isinstance(overhead, Mapping) or set(overhead) - set(RUN_MODES):
        raise ConfigurationError(
            f"{path}:{number}: overhead_tokens must map {' and '.join(RUN_MODES)} to tokens."
        )
    thinking = str(row.get("thinking") or "effort")
    if thinking not in {"effort", "budget"}:
        raise ConfigurationError(f"{path}:{number}: thinking must be 'effort' or 'budget'.")
    match = row["match"]
    return ModelProfile(
        provider=str(row["provider"]),
        match=tuple(str(m).lower() for m in ([match] if isinstance(match, str) else match)),
        bytes_per_token=bytes_per_token,
        overhead_tokens=overhead_values,
        prompt_target_tokens=target,
        prompt_warning_tokens=warning,
        prompt_limit_tokens=limit,
        escalate_model=str(row["escalate_model"]) if row.get("escalate_model") else None,
        thinking=thinking,
        measured=row.get("measured"),
        index=index,
    )


def active_model() -> str:
    """The invocation's model: ``--model`` (published to ``DRYDOCK_MODEL``) or configuration."""
    from drydock.config import get_model

    try:
        return get_model()
    except ConfigurationError:
        return ""


def active_profile() -> ModelProfile:
    return load().model(active_model())


def profile_for(model: str | None) -> ModelProfile:
    return load().model(model or active_model())


def estimate_tokens(byte_count: int, model: str | None = None) -> int:
    """Token estimate for ``byte_count`` prompt bytes on ``model`` (default: the active model)."""
    return profile_for(model).estimate(byte_count)


def escalation(
    model: str | None,
    prompt_bytes: int,
    *,
    allow_tools: bool,
    prior_context_tokens: int = 0,
) -> Escalation | None:
    """Return the model to run instead when this request would cross the model's price limit.

    ``prior_context_tokens`` is the context a resumed session already carries; a resumed
    request sends it again ahead of the new prompt.
    """
    if not model:
        return None
    profile = load().model(model)
    if profile.prompt_limit_tokens is None or not profile.escalate_model:
        return None
    if prior_context_tokens:
        estimated = prior_context_tokens + profile.estimate(prompt_bytes)
    else:
        estimated = profile.request_tokens(prompt_bytes, allow_tools)
    if estimated <= ESCALATION_FRACTION * profile.prompt_limit_tokens:
        return None
    return Escalation(
        from_model=model,
        to_model=profile.escalate_model,
        estimated_tokens=estimated,
        limit_tokens=profile.prompt_limit_tokens,
    )


# ── Calibration ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Observation:
    """One provider call's measured first request, appended to ``model_calibration.jsonl``."""

    at: str
    model: str
    resolved_model: str | None
    provider: str
    mode: str
    cli_version: str | None
    prompt_bytes: int
    first_request_tokens: int
    resumed: bool = False
    probe: bool = False


@dataclass(frozen=True)
class RequestUsage:
    resolved_model: str | None
    cli_version: str | None
    first_request_tokens: int | None
    last_request_tokens: int | None


def claude_request_usage(events: Iterable[Mapping[str, Any]]) -> RequestUsage:
    """Read the first and last request sizes from a Claude ``stream-json`` event stream.

    Each assistant message reports the full context of the request that produced it, so the
    first is the assembled prompt plus the CLI payload and the last is the session's context
    at exit.
    """
    resolved = None
    version = None
    first = None
    last = None
    for event in events:
        if event.get("type") == "system" and event.get("subtype") == "init":
            resolved = event.get("model") or resolved
            version = event.get("claude_code_version") or version
            continue
        if event.get("type") != "assistant":
            continue
        message = event.get("message")
        usage = message.get("usage") if isinstance(message, Mapping) else None
        if not isinstance(usage, Mapping):
            continue
        total = sum(
            int(usage.get(key) or 0)
            for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
        )
        if total <= 0:
            continue
        if first is None:
            first = total
        last = total
    return RequestUsage(resolved, version, first, last)


def calibration_path(logs_dir: Path) -> Path:
    return logs_dir / CALIBRATION_NAME


def record_observation(logs_dir: Path, observation: Observation) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    with calibration_path(logs_dir).open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(observation.__dict__, sort_keys=True) + "\n")


def read_observations(logs_dir: Path) -> list[Observation]:
    path = calibration_path(logs_dir)
    if not path.is_file():
        return []
    names = set(Observation.__dataclass_fields__)
    observations: list[Observation] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and names.issuperset(row) and "first_request_tokens" in row:
            observations.append(Observation(**row))
    return observations


@dataclass(frozen=True)
class Proposal:
    """A measured value that differs from the live row: ``field`` on the row at ``index``."""

    index: int
    label: str
    field: str
    current: Any
    proposed: Any
    runs: int
    cli_version: str | None = None

    def describe(self) -> str:
        return (
            f"{self.label}: {self.field} {self.current} -> {self.proposed} "
            f"({self.runs} run{'s' if self.runs != 1 else ''})"
        )


def _quantile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))]


def _differs(current: float, proposed: float) -> bool:
    return current <= 0 or abs(proposed - current) / current > DRIFT_FRACTION


def propose(config: ModelConfig, observations: Iterable[Observation]) -> list[Proposal]:
    """Compare evidence with the live rows and return the values worth replacing.

    Overhead comes from probes: a trivial prompt whose first request is almost entirely CLI
    payload. The ratio comes from ordinary runs that did not resume a session, measured against
    the configured overhead for their mode, and the proposal is the 10th percentile of bytes per
    token — the conservative end, so an estimate errs toward more tokens.
    """
    by_row: dict[int, list[Observation]] = {}
    for observation in observations:
        try:
            profile = config.model(observation.model)
        except ConfigurationError:
            continue
        by_row.setdefault(profile.index, []).append(observation)
    proposals: list[Proposal] = []
    for profile in config.models:
        rows = by_row.get(profile.index, [])
        for mode in RUN_MODES:
            probes = [o for o in rows if o.probe and o.mode == mode]
            if probes:
                latest = probes[-1]
                measured = max(
                    0, latest.first_request_tokens - profile.estimate(latest.prompt_bytes)
                )
                current = profile.overhead(mode == "build")
                if _differs(current, measured):
                    proposals.append(
                        Proposal(
                            profile.index,
                            profile.label,
                            f"overhead_tokens.{mode}",
                            current,
                            measured,
                            len(probes),
                            latest.cli_version,
                        )
                    )
        ratios: list[float] = []
        versions: list[str | None] = []
        for o in rows:
            if o.probe or o.resumed:
                continue
            payload = o.first_request_tokens - profile.overhead(o.mode == "build")
            if payload > 0 and o.prompt_bytes > 0:
                ratios.append(o.prompt_bytes / payload)
                versions.append(o.cli_version)
        if len(ratios) >= MIN_CALIBRATION_RUNS:
            measured_ratio = round(_quantile(ratios, 0.10), 2)
            if _differs(profile.bytes_per_token, measured_ratio):
                proposals.append(
                    Proposal(
                        profile.index,
                        profile.label,
                        "bytes_per_token",
                        profile.bytes_per_token,
                        measured_ratio,
                        len(ratios),
                        versions[-1],
                    )
                )
    return proposals


def unprobed_cli(config: ModelConfig, observation: Observation) -> bool:
    """True when ``observation`` ran on a CLI version its row's overhead was not measured on."""
    try:
        profile = config.model(observation.model)
    except ConfigurationError:
        return False
    measured = profile.measured or {}
    return bool(observation.cli_version) and measured.get("cli") not in (
        None,
        observation.cli_version,
    )


def apply(config: ModelConfig, proposals: Iterable[Proposal], *, today: str) -> Path:
    """Write ``proposals`` into the live file, preserving every other row and field."""
    rows = [json.loads(json.dumps(row)) for row in config.rows]
    touched: dict[int, list[Proposal]] = {}
    for proposal in proposals:
        touched.setdefault(proposal.index, []).append(proposal)
        row = rows[proposal.index]
        if proposal.field.startswith("overhead_tokens."):
            row.setdefault("overhead_tokens", {})[proposal.field.split(".", 1)[1]] = int(
                proposal.proposed
            )
        else:
            row[proposal.field] = proposal.proposed
    for index, applied in touched.items():
        versions = [p.cli_version for p in applied if p.cli_version]
        previous = rows[index].get("measured") or {}
        rows[index]["measured"] = {
            "cli": versions[-1] if versions else previous.get("cli"),
            "at": today,
            "runs": max(p.runs for p in applied),
        }
    text = "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows)
    config.path.write_text(text, encoding="utf-8", newline="\n")
    _CACHE.pop(config.path, None)
    return config.path


_LAST_NOTICE: dict[Path, str] = {}


def calibration_notice(logs_dir: Path) -> str | None:
    """One line when the evidence disagrees with the live configuration, else ``None``.

    Reported once per distinct finding per process, so a long build does not repeat it after
    every step. Never raises: calibration is advisory.
    """
    try:
        config = load()
        observations = read_observations(logs_dir)
    except (ConfigurationError, OSError):
        return None
    findings = [proposal.describe() for proposal in propose(config, observations)]
    latest = observations[-1] if observations else None
    if latest is not None and unprobed_cli(config, latest):
        findings.append(
            f"CLI {latest.cli_version} not probed for {config.model(latest.model).label}"
        )
    if not findings:
        return None
    notice = "calibration: " + "; ".join(findings) + " (drydock config calibrate)"
    if _LAST_NOTICE.get(logs_dir) == notice:
        return None
    _LAST_NOTICE[logs_dir] = notice
    return notice
