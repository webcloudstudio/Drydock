"""Measure a provider CLI's fixed request payload for ``drydock config calibrate --probe``.

A trivial prompt's first request is almost entirely the CLI's own payload: its system prompt,
plus the schema of every enabled tool in ``build`` mode. One probe per run mode records that
payload in ``model_calibration.jsonl``; ``model_config.propose`` turns it into an
``overhead_tokens`` proposal.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from pathlib import Path

from drydock.llm import CALIBRATION_PROBE_COMMAND, resolve_provider, run_prompt

PROBE_PROMPT = "Reply with OK only. Do not use any tool."


def probe_overhead(
    model: str,
    *,
    logs_dir: Path,
    runner: Callable[..., object] | None = None,
) -> list[str]:
    """Run the probe prompt once per run mode on ``model``; return one console line per mode."""
    provider = resolve_provider(None, model)
    if provider != "claude":
        return [f"probe: {provider} reports usage per turn, not per request; not probed"]
    execute = runner or run_prompt
    lines: list[str] = []
    with tempfile.TemporaryDirectory(prefix="drydock-probe-") as scratch:
        for mode, allow_tools in (("text", False), ("build", True)):
            result = execute(
                PROBE_PROMPT,
                Path(scratch),
                llm=provider,
                model=model,
                command_name=CALIBRATION_PROBE_COMMAND,
                allow_tools=allow_tools,
                log_dir=logs_dir,
                announce=False,
                announce_completion=False,
            )
            status = "ok" if getattr(result, "returncode", 1) == 0 else "failed"
            lines.append(f"probe: {model} {mode} {status}")
    return lines
