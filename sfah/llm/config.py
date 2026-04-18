"""LLM profile loading and project configuration."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .models import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    DEFAULT_TIMEOUT_SECONDS,
    LLMConfig,
    LLMProfile,
    LLMProjectConfig,
    ProviderType,
)


def _parse_dotenv(dotenv_path: Path | None) -> dict[str, str]:
    """Parse a small `.env` file without external dependencies."""
    if dotenv_path is None or not dotenv_path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", maxsplit=1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def _find_project_root(start_dir: Path | None = None) -> Path:
    """Find the current project root."""
    current = (start_dir or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    return current


def _find_dotenv(start_dir: Path | None = None) -> Path | None:
    """Search for `.env` from the current directory upwards."""
    current = _find_project_root(start_dir)
    for candidate in [current, *current.parents]:
        dotenv_path = candidate / ".env"
        if dotenv_path.exists():
            return dotenv_path
    return None


def _profile_env_prefix(profile_name: str) -> str:
    """Convert a profile name to an environment variable prefix."""
    normalized = []
    for char in profile_name.upper():
        normalized.append(char if char.isalnum() else "_")
    return "SFAH_PROFILE_" + "".join(normalized)


def _profile_env_name(profile_name: str) -> str:
    """Convert a profile name to a shorter environment variable prefix."""
    normalized = []
    for char in profile_name.upper():
        normalized.append(char if char.isalnum() else "_")
    return "SFAH_" + "".join(normalized)


def _default_project_config() -> LLMProjectConfig:
    """Built-in config used when `.harness/llm.json` is missing."""
    return LLMProjectConfig(
        version=1,
        active_profile="openai_compat",
        profiles=[
            LLMProfile(
                name="openai_compat",
                provider=ProviderType.OPENAI_COMPAT,
                model="gpt-5.4",
                base_url="https://api.openai.com/v1",
                api_key_env="SFAH_OPENAI_COMPAT_API_KEY",
                timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
                temperature=DEFAULT_TEMPERATURE,
                max_tokens=DEFAULT_MAX_TOKENS,
            ),
            LLMProfile(
                name="anthropic",
                provider=ProviderType.ANTHROPIC,
                model="claude-3-7-sonnet-latest",
                base_url="https://api.anthropic.com",
                api_key_env="SFAH_ANTHROPIC_API_KEY",
                timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
                temperature=DEFAULT_TEMPERATURE,
                max_tokens=DEFAULT_MAX_TOKENS,
                anthropic_version="2023-06-01",
            ),
            LLMProfile(
                name="mock",
                provider=ProviderType.MOCK,
                model="mock-spec-first-harness",
                base_url="mock://local",
                api_key_env="",
                timeout_seconds=30,
                temperature=0.0,
                max_tokens=1024,
            ),
        ],
    )


@dataclass
class LLMRegistry:
    """Project-scoped LLM profile registry."""

    root_dir: Path
    dotenv_values: dict[str, str]
    project_config: LLMProjectConfig

    @classmethod
    def load(cls, start_dir: Path | None = None) -> "LLMRegistry":
        """Load registry from the current project."""
        root_dir = _find_project_root(start_dir)
        dotenv_values = _parse_dotenv(_find_dotenv(root_dir))
        config_path = root_dir / ".harness" / "llm.json"

        if config_path.exists():
            data = json.loads(config_path.read_text(encoding="utf-8"))
            project_config = LLMProjectConfig.from_dict(data)
        else:
            project_config = _default_project_config()

        active_override = os.environ.get("SFAH_ACTIVE_LLM_PROFILE") or dotenv_values.get("SFAH_ACTIVE_LLM_PROFILE")
        if active_override:
            project_config.active_profile = active_override

        return cls(root_dir=root_dir, dotenv_values=dotenv_values, project_config=project_config)

    @property
    def harness_dir(self) -> Path:
        """Return the project metadata directory."""
        return self.root_dir / ".harness"

    @property
    def config_path(self) -> Path:
        """Return `.harness/llm.json`."""
        return self.harness_dir / "llm.json"

    def ensure_project_config(self, force: bool = False) -> Path:
        """Create `.harness/llm.json` from defaults if needed."""
        self.harness_dir.mkdir(parents=True, exist_ok=True)
        if force or not self.config_path.exists():
            self.config_path.write_text(
                json.dumps(self.project_config.to_dict(), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        return self.config_path

    def save(self) -> Path:
        """Persist the current config."""
        self.harness_dir.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(self.project_config.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return self.config_path

    def list_profiles(self) -> list[LLMProfile]:
        """Return all configured profiles."""
        return self.project_config.profiles

    def get_profile(self, name: str | None = None) -> LLMProfile | None:
        """Get a profile by name or return the active one."""
        target = name or self.project_config.active_profile
        for profile in self.project_config.profiles:
            if profile.name == target:
                return profile
        return None

    def set_active_profile(self, name: str) -> LLMProfile:
        """Update the active profile name and save config."""
        profile = self.get_profile(name)
        if profile is None:
            available = ", ".join(item.name for item in self.list_profiles())
            raise ValueError(f"未找到 profile: {name}。可用 profile: {available}")
        self.project_config.active_profile = name
        self.save()
        return profile

    def upsert_profile(self, profile: LLMProfile, make_active: bool = False) -> LLMProfile:
        """Create or replace a profile definition."""
        for index, existing in enumerate(self.project_config.profiles):
            if existing.name == profile.name:
                self.project_config.profiles[index] = profile
                break
        else:
            self.project_config.profiles.append(profile)

        if make_active:
            self.project_config.active_profile = profile.name

        self.save()
        return profile

    def remove_profile(self, name: str) -> LLMProfile:
        """Remove a profile by name."""
        profile = self.get_profile(name)
        if profile is None:
            available = ", ".join(item.name for item in self.list_profiles())
            raise ValueError(f"未找到 profile: {name}。可用 profile: {available}")
        if len(self.project_config.profiles) == 1:
            raise ValueError("至少需要保留一个 profile。")

        self.project_config.profiles = [item for item in self.project_config.profiles if item.name != name]
        if self.project_config.active_profile == name:
            self.project_config.active_profile = self.project_config.profiles[0].name

        self.save()
        return profile

    def resolve_profile(self, name: str | None = None) -> LLMConfig:
        """Resolve the runtime config for a profile."""
        profile = self.get_profile(name)
        if profile is None:
            available = ", ".join(item.name for item in self.list_profiles())
            raise ValueError(f"未找到 profile: {name or self.project_config.active_profile}。可用 profile: {available}")

        def resolve_env(key: str, default: str = "") -> str:
            return os.environ.get(key) or self.dotenv_values.get(key) or default

        def resolve_many(*keys: str, default: str = "") -> str:
            for key in keys:
                value = resolve_env(key)
                if value:
                    return value
            return default

        prefix = _profile_env_prefix(profile.name)
        short_prefix = _profile_env_name(profile.name)
        api_key = resolve_env(profile.api_key_env) if profile.api_key_env else ""
        api_key = api_key or resolve_many(f"{short_prefix}_API_KEY")

        if profile.name == "openai_compat":
            api_key = api_key or resolve_many("HARNESS_LLM_API_KEY")
            base_url = resolve_many(
                f"{prefix}_BASE_URL",
                f"{short_prefix}_BASE_URL",
                "HARNESS_LLM_BASE_URL",
                default=profile.base_url,
            )
            model = resolve_many(
                f"{prefix}_MODEL",
                f"{short_prefix}_MODEL",
                "HARNESS_LLM_MODEL",
                default=profile.model,
            )
            timeout_value = resolve_many(
                f"{prefix}_TIMEOUT_SECONDS",
                f"{short_prefix}_TIMEOUT_SECONDS",
                "HARNESS_LLM_TIMEOUT_SECONDS",
                default=str(profile.timeout_seconds),
            )
        else:
            base_url = resolve_many(f"{prefix}_BASE_URL", f"{short_prefix}_BASE_URL", default=profile.base_url)
            model = resolve_many(f"{prefix}_MODEL", f"{short_prefix}_MODEL", default=profile.model)
            timeout_value = resolve_many(
                f"{prefix}_TIMEOUT_SECONDS",
                f"{short_prefix}_TIMEOUT_SECONDS",
                default=str(profile.timeout_seconds),
            )

        temperature_value = resolve_many(
            f"{prefix}_TEMPERATURE",
            f"{short_prefix}_TEMPERATURE",
            default=str(profile.temperature),
        )
        max_tokens_value = resolve_many(
            f"{prefix}_MAX_TOKENS",
            f"{short_prefix}_MAX_TOKENS",
            default=str(profile.max_tokens),
        )

        try:
            timeout_seconds = max(10, int(timeout_value))
        except ValueError:
            timeout_seconds = profile.timeout_seconds

        try:
            temperature = float(temperature_value)
        except ValueError:
            temperature = profile.temperature

        try:
            max_tokens = max(128, int(max_tokens_value))
        except ValueError:
            max_tokens = profile.max_tokens

        return LLMConfig(
            profile=profile.name,
            provider=profile.provider,
            model=model.strip() or profile.model,
            api_key=api_key.strip(),
            api_key_env=profile.api_key_env,
            base_url=base_url.rstrip("/") if base_url else "",
            timeout_seconds=timeout_seconds,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_headers=profile.extra_headers,
            anthropic_version=profile.anthropic_version,
        )
