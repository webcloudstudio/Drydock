"""Drydock error types."""

from __future__ import annotations


class DrydockError(Exception):
    """Base class for all expected Drydock errors."""


class ConfigurationError(DrydockError):
    """A required configuration value is missing or invalid."""


class SpecificationError(DrydockError):
    """A specification directory or file is invalid."""


class ValidationError(DrydockError):
    """Validation found one or more failures."""


class LlmError(DrydockError):
    """An LLM CLI execution could not be completed."""


class LlmConfigurationError(LlmError):
    """An LLM provider or execution option is invalid."""
