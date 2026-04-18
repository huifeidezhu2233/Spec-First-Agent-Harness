"""LLM provider configuration models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


DEFAULT_TIMEOUT_SECONDS = 90
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_TOKENS = 4096


class ProviderType(str, Enum):
    """Supported LLM provider families."""

    OPENAI_COMPAT = "openai_compat"
    ANTHROPIC = "anthropic"
    MOCK = "mock"


@dataclass
class LLMProfile:
    """Serializable profile definition stored in project config."""

    name: str
    provider: ProviderType
    model: str
    base_url: str = ""
    api_key_env: str = ""
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    temperature: float = DEFAULT_TEMPERATURE
    max_tokens: int = DEFAULT_MAX_TOKENS
    extra_headers: dict[str, str] = field(default_factory=dict)
    anthropic_version: str = "2023-06-01"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LLMProfile":
        """Build a profile from a JSON dict."""
        return cls(
            name=str(data["name"]),
            provider=ProviderType(str(data.get("provider", ProviderType.OPENAI_COMPAT.value))),
            model=str(data.get("model", "")).strip(),
            base_url=str(data.get("base_url", "")).strip(),
            api_key_env=str(data.get("api_key_env", "")).strip(),
            timeout_seconds=int(data.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)),
            temperature=float(data.get("temperature", DEFAULT_TEMPERATURE)),
            max_tokens=int(data.get("max_tokens", DEFAULT_MAX_TOKENS)),
            extra_headers=dict(data.get("extra_headers", {})),
            anthropic_version=str(data.get("anthropic_version", "2023-06-01")).strip() or "2023-06-01",
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the profile to JSON."""
        return {
            "name": self.name,
            "provider": self.provider.value,
            "model": self.model,
            "base_url": self.base_url,
            "api_key_env": self.api_key_env,
            "timeout_seconds": self.timeout_seconds,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "extra_headers": self.extra_headers,
            "anthropic_version": self.anthropic_version,
        }


@dataclass
class LLMProjectConfig:
    """Project-level config stored in `.harness/llm.json`."""

    version: int = 1
    active_profile: str = "openai_compat"
    profiles: list[LLMProfile] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LLMProjectConfig":
        """Build config from a JSON dict."""
        profiles = [LLMProfile.from_dict(item) for item in data.get("profiles", [])]
        return cls(
            version=int(data.get("version", 1)),
            active_profile=str(data.get("active_profile", "openai_compat")),
            profiles=profiles,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON."""
        return {
            "version": self.version,
            "active_profile": self.active_profile,
            "profiles": [profile.to_dict() for profile in self.profiles],
        }


@dataclass
class LLMConfig:
    """Resolved runtime config for a concrete provider."""

    profile: str = "openai_compat"
    provider: ProviderType = ProviderType.OPENAI_COMPAT
    model: str = "gpt-5.4"
    api_key: str = ""
    api_key_env: str = "SFAH_OPENAI_COMPAT_API_KEY"
    base_url: str = "https://api.openai.com/v1"
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    temperature: float = DEFAULT_TEMPERATURE
    max_tokens: int = DEFAULT_MAX_TOKENS
    extra_headers: dict[str, str] = field(default_factory=dict)
    anthropic_version: str = "2023-06-01"

    @property
    def is_configured(self) -> bool:
        """Whether this runtime config is ready for remote calls."""
        if self.provider == ProviderType.MOCK:
            return True
        return bool(self.api_key)

    def describe(self) -> str:
        """Human-readable model and endpoint summary."""
        if self.base_url:
            return f"{self.model} @ {self.base_url}"
        return self.model

    def masked_key(self) -> str:
        """Safe API key display for CLI output."""
        if self.provider == ProviderType.MOCK:
            return "mock"
        if not self.api_key:
            return "未配置"
        if len(self.api_key) <= 8:
            return "*" * len(self.api_key)
        return f"{self.api_key[:4]}...{self.api_key[-4:]}"

    def to_status(self) -> dict[str, Any]:
        """Normalize status fields for CLI output."""
        return {
            "profile": self.profile,
            "provider": self.provider.value,
            "configured": self.is_configured,
            "summary": self.describe(),
            "api_key": self.masked_key(),
            "api_key_env": self.api_key_env or "n/a",
            "base_url": self.base_url or "n/a",
            "model": self.model,
        }

    @classmethod
    def from_env(cls, start_dir=None, profile_name: str | None = None) -> "LLMConfig":
        """Backward-compatible helper for loading the active project profile."""
        from .config import LLMRegistry

        return LLMRegistry.load(start_dir).resolve_profile(profile_name)
