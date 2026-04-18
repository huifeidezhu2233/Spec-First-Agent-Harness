"""测试 spec-first CLI 工作流。"""

import pytest
from click.testing import CliRunner

from sfah.cli import main
from sfah.store import TaskStore


@pytest.fixture
def runner():
    """创建 CLI runner。"""
    return CliRunner()


class TestSpecFirstWorkflowCLI:
    """测试从 spec 到 tasks 的 CLI 闭环。"""

    def test_spec_create_generates_artifacts(self, runner, tmp_path, monkeypatch):
        """spec create 应生成 discovery 和 spec 工件。"""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(main, ["spec", "create", "--goal", "实现用户登录 API"])

        assert result.exit_code == 0
        assert (tmp_path / ".harness" / "spec.md").exists()
        assert (tmp_path / ".harness" / "discovery.md").exists()

    def test_plan_create_requires_approved_spec(self, runner, tmp_path, monkeypatch):
        """plan create 应要求先批准 spec。"""
        monkeypatch.chdir(tmp_path)
        runner.invoke(main, ["spec", "create", "--goal", "实现用户登录 API"])
        result = runner.invoke(main, ["plan", "create"])

        assert result.exit_code == 0
        assert "未批准" in result.output or "approve" in result.output.lower()

    def test_tasks_generate_after_approved_plan(self, runner, tmp_path, monkeypatch):
        """批准后的 plan 应能生成任务。"""
        monkeypatch.chdir(tmp_path)

        assert runner.invoke(main, ["spec", "create", "--goal", "实现用户登录 API"]).exit_code == 0
        assert runner.invoke(main, ["spec", "approve"]).exit_code == 0
        assert runner.invoke(main, ["plan", "create"]).exit_code == 0
        assert runner.invoke(main, ["plan", "approve"]).exit_code == 0

        result = runner.invoke(main, ["tasks", "generate"])
        assert result.exit_code == 0

        store = TaskStore(tmp_path / ".harness")
        assert len(store.load_tasks()) > 0
        assert (tmp_path / "Plans.md").exists()

    def test_root_status_shows_stage(self, runner, tmp_path, monkeypatch):
        """status 应展示当前工作流阶段。"""
        monkeypatch.chdir(tmp_path)
        runner.invoke(main, ["spec", "create", "--goal", "实现用户登录 API"])

        result = runner.invoke(main, ["status"])
        assert result.exit_code == 0
        assert "阶段" in result.output

    def test_execute_alias_exists(self, runner):
        """execute 作为 work 别名应存在。"""
        result = runner.invoke(main, ["execute", "--help"])
        assert result.exit_code == 0
        assert "execute" in result.output.lower()

    def test_llm_status_reads_dotenv(self, runner, tmp_path, monkeypatch):
        """llm status 应展示 provider 配置。"""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text("HARNESS_LLM_API_KEY=sk-test\n", encoding="utf-8")

        result = runner.invoke(main, ["llm", "status"])

        assert result.exit_code == 0
        assert "已配置：是" in result.output
        assert "gpt-5.4" in result.output

    def test_flow_run_auto_approve_generates_tasks(self, runner, tmp_path, monkeypatch):
        """flow run --auto-approve 应直接产出任务图。"""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(main, ["flow", "run", "--goal", "实现用户登录 API", "--auto-approve"])

        assert result.exit_code == 0
        assert (tmp_path / ".harness" / "tasks.md").exists()
        assert (tmp_path / "Plans.md").exists()

    def test_llm_add_profile_command(self, runner, tmp_path, monkeypatch):
        """应能通过 CLI 新增 profile。"""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(
            main,
            [
                "llm",
                "add-profile",
                "--name",
                "relay",
                "--provider",
                "openai_compat",
                "--model",
                "gpt-5.4",
                "--base-url",
                "https://relay.example/v1",
                "--api-key-env",
                "RELAY_API_KEY",
            ],
        )

        assert result.exit_code == 0
        assert "relay" in result.output

