"""LLM profile and configuration tests."""

from sfah.llm import LLMConfig, LLMProfile, LLMRegistry, ProviderType


class TestLLMConfig:
    """测试 provider 配置。"""

    def test_from_env_reads_dotenv_file(self, tmp_path, monkeypatch):
        """应能从 .env 加载默认配置。"""
        (tmp_path / ".env").write_text(
            "\n".join(
                [
                    "HARNESS_LLM_API_KEY=sk-test-key",
                    "HARNESS_LLM_BASE_URL=https://example.com/v1",
                    "HARNESS_LLM_MODEL=test-model",
                    "HARNESS_LLM_TIMEOUT_SECONDS=45",
                ]
            ),
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("HARNESS_LLM_API_KEY", raising=False)
        monkeypatch.delenv("HARNESS_LLM_BASE_URL", raising=False)
        monkeypatch.delenv("HARNESS_LLM_MODEL", raising=False)
        monkeypatch.delenv("HARNESS_LLM_TIMEOUT_SECONDS", raising=False)

        config = LLMConfig.from_env()

        assert config.api_key == "sk-test-key"
        assert config.base_url == "https://example.com/v1"
        assert config.model == "test-model"
        assert config.timeout_seconds == 45

    def test_environment_variables_override_dotenv(self, tmp_path, monkeypatch):
        """环境变量应覆盖 .env。"""
        (tmp_path / ".env").write_text("HARNESS_LLM_MODEL=from-dotenv", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("HARNESS_LLM_MODEL", "from-env")

        config = LLMConfig.from_env()

        assert config.model == "from-env"

    def test_project_prefixed_environment_variables_are_supported(self, tmp_path, monkeypatch):
        """应支持项目前缀环境变量。"""
        (tmp_path / ".env").write_text(
            "\n".join(
                [
                    "SFAH_OPENAI_COMPAT_API_KEY=sk-project-key",
                    "SFAH_OPENAI_COMPAT_BASE_URL=https://relay.example/v1",
                    "SFAH_OPENAI_COMPAT_MODEL=relay-model",
                ]
            ),
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)

        config = LLMConfig.from_env()

        assert config.api_key == "sk-project-key"
        assert config.base_url == "https://relay.example/v1"
        assert config.model == "relay-model"


class TestLLMRegistry:
    """测试项目级 profile 管理。"""

    def test_registry_can_upsert_and_remove_profile(self, tmp_path):
        """应支持新增和删除 profile。"""
        (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\nversion='0.1.0'\n", encoding="utf-8")
        registry = LLMRegistry.load(tmp_path)
        registry.ensure_project_config()

        registry.upsert_profile(
            LLMProfile(
                name="relay",
                provider=ProviderType.OPENAI_COMPAT,
                model="gpt-5.4",
                base_url="https://relay.example/v1",
                api_key_env="RELAY_API_KEY",
            ),
            make_active=True,
        )

        assert registry.get_profile("relay") is not None
        assert registry.project_config.active_profile == "relay"

        removed = registry.remove_profile("relay")
        assert removed.name == "relay"
        assert registry.get_profile("relay") is None

