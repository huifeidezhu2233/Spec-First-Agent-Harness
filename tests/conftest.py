"""Shared pytest fixtures for harness tests."""

import os

import pytest


@pytest.fixture(autouse=True)
def clear_llm_environment(monkeypatch):
    """Keep tests deterministic by clearing external provider configuration."""
    for key in [
        "HARNESS_LLM_API_KEY",
        "HARNESS_LLM_BASE_URL",
        "HARNESS_LLM_MODEL",
        "HARNESS_LLM_TIMEOUT_SECONDS",
        "OPENAI_API_KEY",
    ]:
        monkeypatch.delenv(key, raising=False)

    for key in list(os.environ):
        if key.startswith("SFAH_"):
            monkeypatch.delenv(key, raising=False)

    # Force tests onto the default non-configured profile so local repo state
    # like `.harness/llm.json` never changes test behavior.
    monkeypatch.setenv("SFAH_ACTIVE_LLM_PROFILE", "openai_compat")
