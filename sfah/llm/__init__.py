"""Project-scoped LLM runtime and profile helpers."""

from __future__ import annotations

from pathlib import Path

from .config import LLMRegistry
from .models import LLMConfig, LLMProfile, LLMProjectConfig, ProviderType
from .providers import (
    AnthropicProvider,
    LLMGenerationError,
    LLMProvider,
    MockProvider,
    OpenAICompatibleProvider,
    build_provider,
)


def build_default_provider(start_dir: Path | None = None, profile_name: str | None = None) -> LLMProvider:
    """Build the active provider for the current project."""
    registry = LLMRegistry.load(start_dir)
    config = registry.resolve_profile(profile_name)
    return build_provider(config)


__all__ = [
    "AnthropicProvider",
    "LLMConfig",
    "LLMGenerationError",
    "LLMProfile",
    "LLMProjectConfig",
    "LLMProvider",
    "LLMRegistry",
    "MockProvider",
    "OpenAICompatibleProvider",
    "ProviderType",
    "build_default_provider",
    "build_provider",
]
