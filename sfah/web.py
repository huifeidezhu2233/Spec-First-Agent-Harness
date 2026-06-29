"""Local web workbench for Spec-First Agent Harness."""

from __future__ import annotations

import argparse
import json
import mimetypes
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from sfah.executor import TaskExecutionService
from sfah.history import HistoryManager
from sfah.io_utils import read_text_file, write_text_file
from sfah.llm import LLMProfile, LLMRegistry, ProviderType, build_default_provider
from sfah.models import Priority, Task, TaskStatus
from sfah.store import TaskStore
from sfah.workflow import ArtifactStore, DiscoveryResult, SpecWorkflowService, WorkflowStage, WorkflowStateStore


UI_DIR = Path(__file__).parent / "ui"
ARTIFACT_NAMES = {"discovery", "spec", "plan", "tasks"}
STAGE_LABELS = {
    WorkflowStage.INIT.value: "尚未开始",
    WorkflowStage.DISCOVERED.value: "已理解目标",
    WorkflowStage.SPEC_DRAFTED.value: "规格草稿",
    WorkflowStage.SPEC_APPROVED.value: "规格已确认",
    WorkflowStage.PLAN_DRAFTED.value: "计划草稿",
    WorkflowStage.PLAN_APPROVED.value: "计划已确认",
    WorkflowStage.TASKS_READY.value: "任务已准备",
}
LLM_STEP_LABELS = {
    "discovery": "理解目标",
    "spec": "规格说明",
    "plan": "执行计划",
    "tasks": "任务拆解",
    "execution": "执行任务",
    "review": "检查结果",
    "auto": "全自动运行",
}
PROVIDER_DEFAULTS = {
    ProviderType.OPENAI_COMPAT.value: {
        "model": "gpt-5.4",
        "base_url": "https://api.openai.com/v1",
    },
    ProviderType.ANTHROPIC.value: {
        "model": "claude-3-7-sonnet-latest",
        "base_url": "https://api.anthropic.com",
    },
    ProviderType.MOCK.value: {
        "model": "mock-spec-first-harness",
        "base_url": "mock://local",
    },
}


def ensure_project_config(root_dir: Path) -> None:
    """Ensure the harness metadata and LLM profiles exist."""
    LLMRegistry.load(start_dir=root_dir).ensure_project_config()


def dotenv_path(root_dir: Path) -> Path:
    """Return the local dotenv file path."""
    return root_dir / ".env"


def read_dotenv(root_dir: Path) -> dict[str, str]:
    """Read a small dotenv file."""
    path = dotenv_path(root_dir)
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", maxsplit=1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def write_dotenv_value(root_dir: Path, key: str, value: str) -> None:
    """Create or update one dotenv value."""
    path = dotenv_path(root_dir)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    output: list[str] = []
    found = False
    for line in lines:
        if line.strip().startswith(f"{key}="):
            output.append(f"{key}={value}")
            found = True
        else:
            output.append(line)
    if not found:
        if output and output[-1].strip():
            output.append("")
        output.append(f"{key}={value}")
    path.write_text("\n".join(output) + "\n", encoding="utf-8")


def step_profile_name(step_name: str) -> str:
    """Return the UI-managed profile name for a step."""
    return f"ui_{step_name}"


def step_api_key_env(step_name: str) -> str:
    """Return the dotenv key used for a step-specific API key."""
    normalized = "".join(char if char.isalnum() else "_" for char in step_name.upper())
    return f"SFAH_STEP_{normalized}_API_KEY"


def harness_dir(root_dir: Path) -> Path:
    """Return the harness metadata directory for the served project."""
    return root_dir / ".harness"


def plans_file(root_dir: Path) -> Path:
    """Return the human-readable task plan file."""
    return root_dir / "Plans.md"


def task_to_dict(task: Task) -> dict[str, Any]:
    """Convert a task into UI-friendly JSON."""
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "status": task.status.value,
        "priority": task.priority.value,
        "acceptance_criteria": task.acceptance_criteria,
        "dependencies": task.dependencies,
        "estimated_effort": task.estimated_effort,
        "actual_effort": task.actual_effort,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "block_reason": task.block_reason,
    }


def execution_files(root_dir: Path) -> list[dict[str, str]]:
    """List saved execution artifacts."""
    execution_dir = harness_dir(root_dir) / "executions"
    if not execution_dir.exists():
        return []
    files = []
    for path in sorted(execution_dir.glob("task-*.md")):
        files.append(
            {
                "name": path.name,
                "path": str(path),
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
            }
        )
    return files


def snapshot_files(root_dir: Path, artifact_name: str | None = None) -> list[dict[str, str]]:
    """List saved artifact snapshots."""
    snapshots_dir = harness_dir(root_dir) / "snapshots"
    if not snapshots_dir.exists():
        return []
    pattern = f"{artifact_name}-*.md" if artifact_name else "*.md"
    files = []
    for path in sorted(snapshots_dir.glob(pattern), reverse=True):
        files.append(
            {
                "name": path.name,
                "artifact": path.name.split("-", maxsplit=1)[0],
                "path": str(path),
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
            }
        )
    return files


def snapshot_artifact(root_dir: Path, artifact_name: str, content: str) -> Path:
    """Save a previous artifact version before overwriting it."""
    snapshots_dir = harness_dir(root_dir) / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = snapshots_dir / f"{artifact_name}-{timestamp}.md"
    write_text_file(path, content)
    return path


def sync_plans_file(root_dir: Path, tasks: list[Task]) -> None:
    """Write a readable Plans.md from stored tasks."""
    status_map = {
        TaskStatus.TODO: "[ ]",
        TaskStatus.WIP: "[~]",
        TaskStatus.DONE: "[x]",
        TaskStatus.BLOCKED: "[!]",
    }
    groups = [
        ("### Required（必需）", [task for task in tasks if task.priority == Priority.REQUIRED]),
        ("### Recommended（推荐）", [task for task in tasks if task.priority == Priority.RECOMMENDED]),
        ("### Optional（可选）", [task for task in tasks if task.priority == Priority.OPTIONAL]),
    ]
    lines = ["# 计划", "", "## Tasks", ""]
    for heading, grouped in groups:
        if not grouped:
            continue
        lines.extend([heading, ""])
        for task in grouped:
            lines.append(f"- {status_map.get(task.status, '[ ]')} **Task {task.id}**: {task.title}")
            if task.description:
                lines.append(f"  {task.description}")
            for criterion in task.acceptance_criteria:
                lines.append(f"  - AC: {criterion}")
            lines.append(f"  - Estimate: {task.estimated_effort}")
            if task.dependencies:
                lines.append(f"  - Depends on: {task.dependencies}")
            lines.append("")
    write_text_file(plans_file(root_dir), "\n".join(lines))


def discovery_from_state(state: dict[str, Any]) -> DiscoveryResult:
    """Rebuild a DiscoveryResult from persisted workflow state."""
    return DiscoveryResult(
        goal=state.get("goal", ""),
        context=state.get("context", ""),
        constraints=list(state.get("constraints", [])),
        keywords=list(state.get("keywords", [])),
        features=list(state.get("features", [])),
        assumptions=list(state.get("assumptions", [])),
        open_questions=list(state.get("open_questions", [])),
        success_signals=list(state.get("success_signals", [])),
        risks=list(state.get("risks", [])),
    )


class HarnessWebApp:
    """Small application facade used by the HTTP handler."""

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir.resolve()
        ensure_project_config(self.root_dir)

    @property
    def harness_dir(self) -> Path:
        return harness_dir(self.root_dir)

    def registry(self) -> LLMRegistry:
        """Load the current LLM registry."""
        return LLMRegistry.load(start_dir=self.root_dir)

    def provider_for_step(self, step_name: str):
        """Build the provider configured for a workflow step."""
        registry = self.registry()
        return build_default_provider(start_dir=self.root_dir, profile_name=registry.profile_for_step(step_name))

    def status(self) -> dict[str, Any]:
        workflow_store = WorkflowStateStore(self.harness_dir)
        artifact_store = ArtifactStore(self.harness_dir)
        task_store = TaskStore(self.harness_dir)
        history = HistoryManager(self.harness_dir)
        state = workflow_store.load()
        provider_status = SpecWorkflowService(llm_provider=self.provider_for_step("auto")).provider_status()
        artifacts: dict[str, dict[str, Any]] = {}
        for name in sorted(ARTIFACT_NAMES):
            path = artifact_store.path_for(name)
            artifacts[name] = {
                "exists": path.exists(),
                "path": str(path),
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat() if path.exists() else None,
            }

        stage = state.get("stage", WorkflowStage.INIT.value)
        return {
            "project_root": str(self.root_dir),
            "harness_dir": str(self.harness_dir),
            "workflow": state,
            "stage_label": STAGE_LABELS.get(stage, stage),
            "artifacts": artifacts,
            "tasks": [task_to_dict(task) for task in task_store.load_tasks()],
            "stats": task_store.get_statistics(),
            "events": history.get_recent_events(20),
            "executions": execution_files(self.root_dir),
            "snapshots": snapshot_files(self.root_dir),
            "provider": provider_status,
            "llm_settings": self.llm_settings(),
            "auto_run": self.auto_status(),
        }

    def llm_settings(self) -> dict[str, Any]:
        """Return profiles and per-step model settings."""
        registry = self.registry()
        dotenv_values = read_dotenv(self.root_dir)
        profiles = []
        for profile in registry.list_profiles():
            resolved = registry.resolve_profile(profile.name)
            profiles.append(
                {
                    **profile.to_dict(),
                    "configured": resolved.is_configured,
                    "masked_key": resolved.masked_key(),
                    "summary": resolved.describe(),
                }
            )

        steps = []
        for step_name, label in LLM_STEP_LABELS.items():
            profile_name = registry.profile_for_step(step_name)
            resolved = registry.resolve_profile(profile_name)
            steps.append(
                {
                    "step": step_name,
                    "label": label,
                    "profile": profile_name,
                    "inherits_default": step_name not in registry.project_config.step_profiles,
                    "provider": resolved.provider.value,
                    "model": resolved.model,
                    "base_url": resolved.base_url,
                    "configured": resolved.is_configured,
                    "masked_key": resolved.masked_key(),
                    "api_key_env": resolved.api_key_env,
                    "has_local_key": bool(resolved.api_key_env and dotenv_values.get(resolved.api_key_env)),
                }
            )

        return {
            "active_profile": registry.project_config.active_profile,
            "profiles": profiles,
            "steps": steps,
            "providers": [
                {"value": ProviderType.OPENAI_COMPAT.value, "label": "OpenAI 兼容"},
                {"value": ProviderType.ANTHROPIC.value, "label": "Anthropic"},
                {"value": ProviderType.MOCK.value, "label": "本地模拟"},
            ],
            "provider_defaults": PROVIDER_DEFAULTS,
        }

    def save_step_llm(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Persist a step-specific provider/model/API setting."""
        step_name = str(payload.get("step") or "").strip()
        if step_name not in LLM_STEP_LABELS:
            raise ValueError("未知步骤。")

        if payload.get("inherit_default"):
            registry = self.registry()
            registry.clear_step_profile(step_name)
            HistoryManager(self.harness_dir).log_workflow_event("ui_llm_step_reset", step=step_name)
            return self.llm_settings()

        provider_value = str(payload.get("provider") or ProviderType.MOCK.value)
        provider = ProviderType(provider_value)
        defaults = PROVIDER_DEFAULTS[provider.value]
        model = str(payload.get("model") or defaults["model"]).strip()
        base_url = str(payload.get("base_url") or defaults["base_url"]).strip()
        api_key = str(payload.get("api_key") or "").strip()
        profile_name = step_profile_name(step_name)
        api_key_env = "" if provider == ProviderType.MOCK else step_api_key_env(step_name)

        registry = self.registry()
        registry.upsert_profile(
            LLMProfile(
                name=profile_name,
                provider=provider,
                model=model,
                base_url=base_url,
                api_key_env=api_key_env,
                timeout_seconds=int(payload.get("timeout_seconds") or 90),
                temperature=float(payload.get("temperature") or 0.2),
                max_tokens=int(payload.get("max_tokens") or 4096),
            )
        )
        registry.set_step_profile(step_name, profile_name)
        if api_key_env and api_key:
            write_dotenv_value(self.root_dir, api_key_env, api_key)
        HistoryManager(self.harness_dir).log_workflow_event(
            "ui_llm_step_saved",
            step=step_name,
            profile=profile_name,
            provider=provider.value,
            model=model,
        )
        return self.llm_settings()

    def get_artifact(self, name: str) -> dict[str, Any]:
        if name not in ARTIFACT_NAMES:
            raise ValueError("未知工件。")
        artifact_store = ArtifactStore(self.harness_dir)
        path = artifact_store.path_for(name)
        return {
            "name": name,
            "exists": path.exists(),
            "path": str(path),
            "content": read_text_file(path) if path.exists() else "",
        }

    def save_artifact(self, name: str, content: str) -> dict[str, Any]:
        if name not in ARTIFACT_NAMES:
            raise ValueError("未知工件。")
        artifact_store = ArtifactStore(self.harness_dir)
        history = HistoryManager(self.harness_dir)
        old_content = artifact_store.load(name) if artifact_store.exists(name) else ""
        snapshot_path = None
        if old_content and old_content != content:
            snapshot_path = snapshot_artifact(self.root_dir, name, old_content)
        path = artifact_store.save(name, content)
        history.log_workflow_event(
            "artifact_saved_from_ui",
            artifact=str(path),
            artifact_name=name,
            snapshot=str(snapshot_path) if snapshot_path else "",
        )
        return {"path": str(path), "snapshot": str(snapshot_path) if snapshot_path else ""}

    def rollback_artifact(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Restore an artifact from a saved snapshot."""
        name = str(payload.get("name") or "")
        snapshot_name = str(payload.get("snapshot") or "")
        if name not in ARTIFACT_NAMES:
            raise ValueError("未知工件。")
        if not snapshot_name:
            raise ValueError("请选择要恢复的快照。")

        snapshots_dir = self.harness_dir / "snapshots"
        snapshot_path = (snapshots_dir / snapshot_name).resolve()
        if not str(snapshot_path).startswith(str(snapshots_dir.resolve())) or not snapshot_path.exists():
            raise ValueError("快照不存在。")

        artifact_store = ArtifactStore(self.harness_dir)
        current = artifact_store.load(name) if artifact_store.exists(name) else ""
        before_rollback = snapshot_artifact(self.root_dir, name, current) if current else None
        content = read_text_file(snapshot_path)
        path = artifact_store.save(name, content)
        HistoryManager(self.harness_dir).log_workflow_event(
            "artifact_rolled_back_from_ui",
            artifact=str(path),
            artifact_name=name,
            snapshot=str(snapshot_path),
            before_rollback=str(before_rollback) if before_rollback else "",
        )
        return {"path": str(path), "snapshot": str(snapshot_path), "before_rollback": str(before_rollback) if before_rollback else ""}

    def generate_discovery(self, payload: dict[str, Any]) -> dict[str, Any]:
        goal = str(payload.get("goal") or "").strip()
        if not goal:
            raise ValueError("请先填写目标。")
        context = str(payload.get("context") or "").strip()
        constraints = payload.get("constraints") or []
        if isinstance(constraints, str):
            constraints = [line.strip() for line in constraints.splitlines() if line.strip()]

        service = SpecWorkflowService(llm_provider=self.provider_for_step("discovery"))
        workflow_store = WorkflowStateStore(self.harness_dir)
        artifact_store = ArtifactStore(self.harness_dir)
        history = HistoryManager(self.harness_dir)
        result = service.build_discovery(goal=goal, context=context, constraints=constraints)
        path = artifact_store.save("discovery", service.render_discovery_markdown(result))
        workflow_store.set_discovery(result)
        workflow_store.mark_artifact("discovery", path, WorkflowStage.DISCOVERED)
        history.log_workflow_event(
            "ui_discovery_generated",
            goal=result.goal,
            artifact=str(path),
            source=service.generation_source("discovery"),
        )
        return {"artifact": str(path), "source": service.generation_source("discovery")}

    def generate_spec(self, payload: dict[str, Any]) -> dict[str, Any]:
        workflow_store = WorkflowStateStore(self.harness_dir)
        state = workflow_store.load()
        if not state.get("goal"):
            self.generate_discovery(payload)
            state = workflow_store.load()
        service = SpecWorkflowService(llm_provider=self.provider_for_step("spec"))
        artifact_store = ArtifactStore(self.harness_dir)
        history = HistoryManager(self.harness_dir)
        discovery = discovery_from_state(state)
        path = artifact_store.save("spec", service.render_spec_markdown(discovery))
        workflow_store.mark_artifact("spec", path, WorkflowStage.SPEC_DRAFTED)
        history.log_workflow_event("ui_spec_generated", artifact=str(path), source=service.generation_source("spec"))
        return {"artifact": str(path), "source": service.generation_source("spec")}

    def approve_spec(self) -> dict[str, Any]:
        artifact_store = ArtifactStore(self.harness_dir)
        if not artifact_store.exists("spec"):
            raise ValueError("还没有规格说明，请先生成。")
        workflow_store = WorkflowStateStore(self.harness_dir)
        workflow_store.approve_spec()
        HistoryManager(self.harness_dir).log_workflow_event("ui_spec_approved", artifact=str(artifact_store.path_for("spec")))
        return {"stage": WorkflowStage.SPEC_APPROVED.value}

    def generate_plan(self) -> dict[str, Any]:
        workflow_store = WorkflowStateStore(self.harness_dir)
        state = workflow_store.load()
        if not state.get("spec_approved"):
            raise ValueError("请先确认规格说明，再生成执行计划。")
        service = SpecWorkflowService(llm_provider=self.provider_for_step("plan"))
        artifact_store = ArtifactStore(self.harness_dir)
        history = HistoryManager(self.harness_dir)
        path = artifact_store.save("plan", service.render_plan_markdown(state))
        workflow_store.mark_artifact("plan", path, WorkflowStage.PLAN_DRAFTED)
        history.log_workflow_event("ui_plan_generated", artifact=str(path), source=service.generation_source("plan"))
        return {"artifact": str(path), "source": service.generation_source("plan")}

    def approve_plan(self) -> dict[str, Any]:
        artifact_store = ArtifactStore(self.harness_dir)
        if not artifact_store.exists("plan"):
            raise ValueError("还没有执行计划，请先生成。")
        workflow_store = WorkflowStateStore(self.harness_dir)
        workflow_store.approve_plan()
        HistoryManager(self.harness_dir).log_workflow_event("ui_plan_approved", artifact=str(artifact_store.path_for("plan")))
        return {"stage": WorkflowStage.PLAN_APPROVED.value}

    def generate_tasks(self, replace: bool = True) -> dict[str, Any]:
        workflow_store = WorkflowStateStore(self.harness_dir)
        state = workflow_store.load()
        if not state.get("plan_approved"):
            raise ValueError("请先确认执行计划，再拆解任务。")

        service = SpecWorkflowService(llm_provider=self.provider_for_step("tasks"))
        artifact_store = ArtifactStore(self.harness_dir)
        task_store = TaskStore(self.harness_dir)
        history = HistoryManager(self.harness_dir)
        if task_store.load_tasks() and not replace:
            raise ValueError("当前已有任务。如需重建，请允许覆盖。")

        tasks = service.build_tasks(state, start_id=1)
        task_store.save_tasks(tasks)
        sync_plans_file(self.root_dir, tasks)
        path = artifact_store.save("tasks", service.render_tasks_markdown(tasks))
        workflow_store.mark_artifact("tasks", path, WorkflowStage.TASKS_READY)
        workflow_store.mark_tasks_ready(len(tasks))
        for task in tasks:
            history.log_task_created(task)
        history.log_workflow_event(
            "ui_tasks_generated",
            artifact=str(path),
            task_count=len(tasks),
            source=service.generation_source("tasks"),
        )
        return {"artifact": str(path), "task_count": len(tasks), "source": service.generation_source("tasks")}

    def execute_tasks(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw_ids = payload.get("task_ids") or []
        task_ids = [int(item) for item in raw_ids] if raw_ids else None
        service = TaskExecutionService(self.harness_dir, llm_provider=self.provider_for_step("execution"))
        results = service.execute_tasks(task_ids)
        HistoryManager(self.harness_dir).log_workflow_event(
            "ui_execute_completed",
            task_count=len(results),
            success_count=sum(1 for result in results if result.success),
        )
        return {"results": [result.to_dict() for result in results]}

    def events(self) -> dict[str, Any]:
        history = HistoryManager(self.harness_dir)
        return {"events": history.get_recent_events(50)}

    def auto_status_file(self) -> Path:
        """Return the persisted auto-run status file."""
        return self.harness_dir / "auto-run.json"

    def auto_status(self) -> dict[str, Any]:
        """Read the latest auto-run status."""
        path = self.auto_status_file()
        if not path.exists():
            return {
                "status": "未运行",
                "message": "还没有启动全自动运行。",
                "events": [],
            }
        return json.loads(read_text_file(path))

    def save_auto_status(self, status: dict[str, Any]) -> None:
        """Persist auto-run status."""
        write_text_file(self.auto_status_file(), json.dumps(status, ensure_ascii=False, indent=2) + "\n")

    def auto_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Run the workflow end-to-end with checkpoints and local fallback."""
        goal = str(payload.get("goal") or "").strip()
        context = str(payload.get("context") or "").strip()
        execute_tasks = bool(payload.get("execute", True))
        max_cycles = int(payload.get("max_cycles") or 20)
        events: list[dict[str, Any]] = []

        def note(step: str, message: str) -> None:
            event = {"time": datetime.now().isoformat(), "step": step, "message": message}
            events.append(event)
            self.save_auto_status({"status": "运行中", "message": message, "events": events})

        HistoryManager(self.harness_dir).log_workflow_event("ui_auto_run_started", max_cycles=max_cycles)
        note("start", "全自动运行已启动。")

        final_status = "已完成"
        final_message = "全自动运行完成。"
        try:
            for cycle in range(1, max_cycles + 1):
                workflow_store = WorkflowStateStore(self.harness_dir)
                artifact_store = ArtifactStore(self.harness_dir)
                task_store = TaskStore(self.harness_dir)
                state = workflow_store.load()
                note("cycle", f"第 {cycle} 轮检查当前进度。")

                if not state.get("goal"):
                    if not goal:
                        raise ValueError("请先填写目标，才能启动全自动运行。")
                    self.generate_discovery({"goal": goal, "context": context})
                    note("discovery", "已理解目标。")
                    continue

                if not artifact_store.exists("spec"):
                    self.generate_spec({"goal": state.get("goal") or goal, "context": state.get("context") or context})
                    note("spec", "已生成规格说明。")
                    continue

                if not state.get("spec_approved"):
                    self.approve_spec()
                    note("spec", "已自动确认规格说明。")
                    continue

                if not artifact_store.exists("plan"):
                    self.generate_plan()
                    note("plan", "已生成执行计划。")
                    continue

                if not workflow_store.load().get("plan_approved"):
                    self.approve_plan()
                    note("plan", "已自动确认执行计划。")
                    continue

                if not task_store.load_tasks():
                    self.generate_tasks(replace=True)
                    note("tasks", "已拆解任务。")
                    continue

                review = self.review_plan()
                if review["issues"]:
                    final_status = "需要处理"
                    final_message = "自动检查发现问题，请先处理后继续。"
                    note("review", final_message)
                    break
                note("review", "计划检查通过。")

                todo_tasks = task_store.get_tasks_by_status(TaskStatus.TODO)
                if execute_tasks and todo_tasks:
                    self.execute_tasks({"task_ids": [task.id for task in todo_tasks]})
                    note("execution", f"已执行 {len(todo_tasks)} 个待办任务。")
                    continue

                final_status = "已完成"
                final_message = "工作流已自动推进完成。"
                note("done", final_message)
                break
            else:
                final_status = "继续中"
                final_message = f"已运行 {max_cycles} 轮，仍有后续事项。可以再次点击继续。"
                note("limit", final_message)
        except Exception as exc:
            final_status = "需要处理"
            final_message = str(exc)
            note("error", final_message)

        result = {"status": final_status, "message": final_message, "events": events}
        self.save_auto_status(result)
        HistoryManager(self.harness_dir).log_workflow_event("ui_auto_run_finished", status=final_status, message=final_message)
        return result

    def review_plan(self) -> dict[str, Any]:
        """Review spec, plan, and tasks for consistency."""
        task_store = TaskStore(self.harness_dir)
        workflow_state = WorkflowStateStore(self.harness_dir).load()
        artifacts = ArtifactStore(self.harness_dir)
        tasks = task_store.load_tasks()
        issues: list[str] = []

        if not artifacts.exists("spec"):
            issues.append("尚未生成规格说明。")
        elif not workflow_state.get("spec_approved"):
            issues.append("规格说明还没有确认通过。")

        if artifacts.exists("plan") and not workflow_state.get("plan_approved"):
            issues.append("执行计划还没有确认通过。")
        elif not artifacts.exists("plan"):
            issues.append("尚未生成执行计划。")

        if not tasks:
            issues.append("还没有任务可检查。")
        else:
            task_ids = {task.id for task in tasks}
            for task in tasks:
                for dependency in task.dependencies:
                    if dependency not in task_ids:
                        issues.append(f"任务 {task.id} 依赖了不存在的任务 {dependency}。")
                if task.priority == Priority.REQUIRED and not task.acceptance_criteria:
                    issues.append(f"必需任务 {task.id} 缺少验收标准。")
                for dependency in task.dependencies:
                    dependency_task = task_store.get_task(dependency)
                    if dependency_task and task.priority == Priority.REQUIRED and dependency_task.priority == Priority.OPTIONAL:
                        issues.append(f"必需任务 {task.id} 依赖了可选任务 {dependency}。")

        HistoryManager(self.harness_dir).log_workflow_event("ui_review_plan", issue_count=len(issues))
        return {
            "verdict": "需要修改" if issues else "检查通过",
            "issues": issues,
            "task_count": len(tasks),
        }


class HarnessRequestHandler(BaseHTTPRequestHandler):
    """HTTP handler serving static UI and JSON APIs."""

    app: HarnessWebApp

    def log_message(self, format: str, *args: Any) -> None:
        """Keep server logs readable for interactive use."""
        print(f"[sfah-web] {self.address_string()} - {format % args}")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path.startswith("/api/"):
                self.handle_api_get(parsed.path, parse_qs(parsed.query))
                return
            self.serve_static(parsed.path)
        except Exception as exc:
            self.send_json({"ok": False, "message": str(exc)}, status=500)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            payload = self.read_json()
            self.handle_api_post(parsed.path, payload)
        except Exception as exc:
            self.send_json({"ok": False, "message": str(exc)}, status=500)

    def handle_api_get(self, path: str, query: dict[str, list[str]]) -> None:
        if path == "/api/status":
            self.send_ok(self.app.status())
            return
        if path == "/api/artifact":
            name = (query.get("name") or [""])[0]
            self.send_ok(self.app.get_artifact(name))
            return
        if path == "/api/events":
            self.send_ok(self.app.events())
            return
        if path == "/api/snapshots":
            name = (query.get("name") or [""])[0] or None
            self.send_ok({"snapshots": snapshot_files(self.app.root_dir, name)})
            return
        if path == "/api/llm-settings":
            self.send_ok(self.app.llm_settings())
            return
        if path == "/api/auto-status":
            self.send_ok(self.app.auto_status())
            return
        self.send_json({"ok": False, "message": "未知接口。"}, status=404)

    def handle_api_post(self, path: str, payload: dict[str, Any]) -> None:
        routes = {
            "/api/artifact": lambda: self.app.save_artifact(str(payload.get("name") or ""), str(payload.get("content") or "")),
            "/api/artifact/rollback": lambda: self.app.rollback_artifact(payload),
            "/api/discovery": lambda: self.app.generate_discovery(payload),
            "/api/spec": lambda: self.app.generate_spec(payload),
            "/api/spec/approve": self.app.approve_spec,
            "/api/plan": self.app.generate_plan,
            "/api/plan/approve": self.app.approve_plan,
            "/api/tasks": lambda: self.app.generate_tasks(bool(payload.get("replace", True))),
            "/api/execute": lambda: self.app.execute_tasks(payload),
            "/api/review/plan": self.app.review_plan,
            "/api/llm-step": lambda: self.app.save_step_llm(payload),
            "/api/auto-run": lambda: self.app.auto_run(payload),
        }
        action = routes.get(path)
        if action is None:
            self.send_json({"ok": False, "message": "未知接口。"}, status=404)
            return
        self.send_ok(action())

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw else {}

    def send_ok(self, data: Any, message: str = "操作完成。") -> None:
        self.send_json({"ok": True, "message": message, "data": data})

    def send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_static(self, request_path: str) -> None:
        relative = request_path.lstrip("/") or "index.html"
        if relative.startswith("ui/"):
            relative = relative[3:]
        static_path = (UI_DIR / relative).resolve()
        if not str(static_path).startswith(str(UI_DIR.resolve())) or not static_path.exists() or static_path.is_dir():
            static_path = UI_DIR / "index.html"
        body = static_path.read_bytes()
        content_type = mimetypes.guess_type(static_path.name)[0] or "application/octet-stream"
        if static_path.suffix in {".html", ".css", ".js"}:
            content_type += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_server(host: str, port: int, root_dir: Path) -> None:
    """Start the local harness web workbench."""
    app = HarnessWebApp(root_dir=root_dir)
    handler = type("BoundHarnessRequestHandler", (HarnessRequestHandler,), {"app": app})
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Spec-First Agent Harness 工作台已启动: http://{host}:{port}")
    print(f"项目目录: {app.root_dir}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在关闭工作台...")
    finally:
        server.server_close()


def main() -> None:
    """CLI entrypoint for the web workbench."""
    parser = argparse.ArgumentParser(description="启动 Spec-First Agent Harness 本地工作台")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8765, help="监听端口")
    parser.add_argument("--root", default=".", help="项目根目录")
    args = parser.parse_args()
    run_server(args.host, args.port, Path(args.root))


if __name__ == "__main__":
    main()
