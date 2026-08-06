"""Materialize the built Target's ``.env`` from its committed ``.env.example``.

A build that leaves the operator to invent configuration has not delivered a runnable
program. ``.env.example`` is the declared configuration surface (``Rigging/stack/
env_variables_and_secrets.md`` §2); this module turns that declaration into the local
file the application actually reads, generating a real value for every secret-shaped
variable so the first run needs no operator action.

Deterministic and LLM-free. Two invariants govern it:

* **An existing ``.env`` is never read, rewritten, or inspected.** It holds the operator's
  own values and a signing key that live sessions and stored data depend on; a rebuild
  that rotated it would silently invalidate them.
* **Only placeholders are replaced.** A value the example author actually chose is
  configuration, not a gap, and is copied through unchanged.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from pathlib import Path

#: Variable names whose value is a credential Drydock can safely generate itself.
_SECRET_NAME = re.compile(r"SECRET|PASSWORD|TOKEN|API_KEY|_KEY$|^KEY$|SALT|SIGNING", re.IGNORECASE)

#: Example values that mean "no value yet". Compared case-insensitively.
_PLACEHOLDERS = frozenset({
    "",
    "change-me",
    "changeme",
    "change_me",
    "replace-me",
    "replaceme",
    "your-secret-here",
    "your-secret-key",
    "generate-me",
    "todo",
    "xxx",
})

#: A value the operator must supply from somewhere Drydock cannot reach — a third-party
#: credential, an endpoint, an account id. Angle brackets are the documented spelling.
_OPERATOR_PLACEHOLDER = re.compile(r"^<.*>$")

#: Bytes of entropy behind a generated secret. 48 urlsafe bytes is 64 characters.
_SECRET_BYTES = 48


@dataclass(frozen=True)
class EnvMaterialization:
    """Outcome of one ``.env`` materialization attempt."""

    path: Path | None
    created: bool
    generated_keys: tuple[str, ...] = ()
    needs_operator_value: tuple[str, ...] = ()
    detail: str = ""

    def summary(self) -> str:
        """One line for the build summary and the run evidence."""
        if not self.created:
            return self.detail
        generated = f" ({', '.join(self.generated_keys)} generated)" if self.generated_keys else ""
        return f"{self.path}{generated}"


def is_secret_name(key: str) -> bool:
    """Return whether ``key`` names a credential Drydock may generate a value for."""
    return bool(_SECRET_NAME.search(key))


def declared_keys(build_dir: Path) -> tuple[str, ...]:
    """Return every variable name declared by ``.env.example``, in file order.

    This is the built project's declared configuration surface. The boot check uses it to
    strip those variables from its own environment, so a build can only boot on values it
    supplies for itself.
    """
    example = build_dir / ".env.example"
    if not example.is_file():
        return ()
    keys: list[str] = []
    for line in _read_lines(example):
        parsed = _parse_assignment(line)
        if parsed is not None and parsed[0] not in keys:
            keys.append(parsed[0])
    return tuple(keys)


def materialize_env_file(build_dir: Path) -> EnvMaterialization:
    """Write ``build_dir/.env`` from ``.env.example`` when no ``.env`` exists yet."""
    env_path = build_dir / ".env"
    example_path = build_dir / ".env.example"

    if env_path.exists():
        return EnvMaterialization(env_path, False, detail="existing .env preserved")
    if not example_path.is_file():
        return EnvMaterialization(None, False, detail="no .env.example")

    generated: list[str] = []
    needs_value: list[str] = []
    out: list[str] = []

    for line in _read_lines(example_path):
        parsed = _parse_assignment(line)
        if parsed is None:
            # Comments, blank lines, and anything unparseable are carried through so the
            # generated .env reads as the documented example it came from.
            out.append(line)
            continue
        key, value = parsed
        if _OPERATOR_PLACEHOLDER.match(value.strip()):
            needs_value.append(key)
            out.append(line)
            continue
        if is_secret_name(key) and _is_placeholder(value):
            out.append(f"{key}={secrets.token_urlsafe(_SECRET_BYTES)}")
            generated.append(key)
            continue
        out.append(line)

    env_path.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
    _restrict_permissions(env_path)

    return EnvMaterialization(
        path=env_path,
        created=True,
        generated_keys=tuple(generated),
        needs_operator_value=tuple(needs_value),
        detail="written from .env.example",
    )


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _parse_assignment(line: str) -> tuple[str, str] | None:
    """Return ``(key, value)`` for an assignment line, or ``None`` for anything else."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    raw_key, _, value = stripped.partition("=")
    # ``export FOO=bar`` is valid in a sourced .env; the variable is still FOO.
    key = raw_key.strip().removeprefix("export ").strip()
    if not key or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
        return None
    return key, value


def _is_placeholder(value: str) -> bool:
    return value.strip().strip("\"'").lower() in _PLACEHOLDERS


def _restrict_permissions(path: Path) -> None:
    """Best-effort owner-only mode. A filesystem that ignores it must not fail the build."""
    try:
        path.chmod(0o600)
    except OSError:  # pragma: no cover - depends on the host filesystem
        pass
