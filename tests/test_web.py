"""Tests for the local web workbench facade."""

from pathlib import Path

from sfah.web import HarnessWebApp


def test_web_app_generates_artifacts_and_tasks(tmp_path):
    """The web facade should drive the existing harness workflow."""
    app = HarnessWebApp(tmp_path)

    app.generate_discovery({"goal": "实现一个支持邮箱密码登录的 API", "context": "使用现有 Python 服务"})
    app.generate_spec({})
    app.approve_spec()
    app.generate_plan()
    app.approve_plan()
    result = app.generate_tasks()
    status = app.status()

    assert result["task_count"] >= 1
    assert status["workflow"]["stage"] == "TASKS_READY"
    assert status["artifacts"]["discovery"]["exists"] is True
    assert status["artifacts"]["spec"]["exists"] is True
    assert status["artifacts"]["plan"]["exists"] is True
    assert status["artifacts"]["tasks"]["exists"] is True
    assert status["tasks"]


def test_save_artifact_creates_snapshot_when_content_changes(tmp_path):
    """Editing an artifact from the UI should preserve the previous version."""
    app = HarnessWebApp(tmp_path)

    app.generate_discovery({"goal": "实现审计日志"})
    first = app.get_artifact("discovery")["content"]
    saved = app.save_artifact("discovery", first + "\n补充一条人工修改。\n")

    assert saved["snapshot"]
    assert (tmp_path / ".harness" / "snapshots").exists()
    assert app.status()["snapshots"][0]["artifact"] == "discovery"


def test_rollback_artifact_restores_snapshot(tmp_path):
    """The web facade should restore a previous artifact version."""
    app = HarnessWebApp(tmp_path)

    app.generate_discovery({"goal": "实现审计日志"})
    original = app.get_artifact("discovery")["content"]
    saved = app.save_artifact("discovery", original + "\n人工修改。\n")
    app.rollback_artifact({"name": "discovery", "snapshot": Path(saved["snapshot"]).name})

    assert app.get_artifact("discovery")["content"] == original


def test_review_plan_reports_missing_artifacts(tmp_path):
    """Plan review should return Chinese issues instead of raising."""
    app = HarnessWebApp(tmp_path)

    result = app.review_plan()

    assert result["verdict"] == "需要修改"
    assert result["issues"]


def test_step_llm_settings_are_persisted_and_used(tmp_path):
    """A step-specific model setting should drive that step's generation."""
    app = HarnessWebApp(tmp_path)

    settings = app.save_step_llm(
        {
            "step": "plan",
            "provider": "mock",
            "model": "mock-spec-first-harness",
            "base_url": "mock://local",
        }
    )
    app.generate_discovery({"goal": "实现一个支持邮箱密码登录的 API"})
    app.generate_spec({})
    app.approve_spec()
    app.generate_plan()

    assert any(step["step"] == "plan" and step["profile"] == "ui_plan" for step in settings["steps"])
    assert "聚焦最小闭环" in app.get_artifact("plan")["content"]


def test_step_llm_api_key_is_written_to_dotenv(tmp_path):
    """Saving a step API key should make it available to runtime config."""
    app = HarnessWebApp(tmp_path)

    app.save_step_llm(
        {
            "step": "spec",
            "provider": "openai_compat",
            "model": "test-model",
            "base_url": "https://relay.example/v1",
            "api_key": "sk-step-test",
        }
    )

    assert "SFAH_STEP_SPEC_API_KEY=sk-step-test" in (tmp_path / ".env").read_text(encoding="utf-8")
    assert app.llm_settings()["steps"][1]["configured"] is True


def test_auto_run_completes_workflow(tmp_path):
    """Auto run should move from an empty project to executed tasks."""
    app = HarnessWebApp(tmp_path)

    result = app.auto_run({"goal": "实现一个支持邮箱密码登录的 API", "execute": True, "max_cycles": 30})
    status = app.status()

    assert result["status"] == "已完成"
    assert status["workflow"]["stage"] == "TASKS_READY"
    assert status["stats"]["total"] > 0
    assert status["stats"]["todo"] == 0
