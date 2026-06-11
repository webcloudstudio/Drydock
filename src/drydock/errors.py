"""Drydock error types."""

from __future__ import annotations


class DrydockError(Exception):
    """Base class for all expected Drydock errors."""


class UsageError(DrydockError):
    """Command arguments do not satisfy the public CLI contract."""


class ConfigurationError(DrydockError):
    """A required configuration value is missing or invalid."""


class SpecificationError(DrydockError):
    """A Blueprint or one of its Typed Specification files is invalid."""


class ValidationError(DrydockError):
    """Validation found one or more failures."""


class LlmError(DrydockError):
    """An LLM CLI execution could not be completed."""


class LlmConfigurationError(LlmError):
    """An LLM provider or execution option is invalid."""
