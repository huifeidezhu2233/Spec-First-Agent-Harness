"""CLI 入口点。"""

from __future__ import annotations

from pathlib import Path

import click

from sfah import __version__
from sfah.executor import ExecutionMode, TaskExecutionService, select_execution_mode
from sfah.history import HistoryManager
from sfah.io_utils import console_supports_unicode, read_text_file, safe_console_text, write_text_file
from sfah.llm import LLMProfile, LLMRegistry, ProviderType, build_default_provider
from sfah.models import Priority, Task, TaskStatus
from sfah.reviewer import ReviewerAgent
from sfah.store import TaskStore
from sfah.workflow import ArtifactStore, SpecWorkflowService, WorkflowStage, WorkflowStateStore


UNICODE_UI = console_supports_unicode()
REVIEW_EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".harness",
    "htmlcov",
    "build",
    "dist",
    "node_modules",
    "tests",
}


def echo(message: str = "") -> None:
    """统一处理 CLI 输出，避免编码错误。"""
    click.echo(safe_console_text(message))


def get_harness_dir() -> Path:
    """获取 .harness 目录。"""
    return Path.cwd() / ".harness"


def get_plans_file() -> Path:
    """获取 Plans.md 文件路径。"""
    return Path.cwd() / "Plans.md"


def initialize_project_config(force: bool = False) -> Path:
    """初始化项目级 metadata 和 LLM profile 配置。"""
    harness_dir = get_harness_dir()
    harness_dir.mkdir(parents=True, exist_ok=True)
    registry = LLMRegistry.load()
    return registry.ensure_project_config(force=force)


def parse_headers(header_values: tuple[str, ...]) -> dict[str, str]:
    """解析形如 `Key=Value` 的 header 选项。"""
    headers: dict[str, str] = {}
    for raw_header in header_values:
        if "=" not in raw_header:
            raise click.ClickException(f"无效的 header：{raw_header}。请使用 Key=Value 格式。")
        key, value = raw_header.split("=", maxsplit=1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise click.ClickException(f"无效的 header：{raw_header}。Header 名称不能为空。")
        headers[key] = value
    return headers


def icon(name: str) -> str:
    """根据终端能力返回可显示图标。"""
    unicode_icons = {
        "required": "🔴",
        "recommended": "🟡",
        "optional": "🟢",
        "critical": "🔴",
        "major": "🟡",
        "minor": "🟢",
        "info": "ℹ️",
        "success": "✅",
        "error": "❌",
    }
    ascii_icons = {
        "required": "[R]",
        "recommended": "[M]",
        "optional": "[O]",
        "critical": "[!]",
        "major": "[*]",
        "minor": "[-]",
        "info": "[i]",
        "success": "[OK]",
        "error": "[X]",
    }
    mapping = unicode_icons if UNICODE_UI else ascii_icons
    return mapping.get(name, "")


def priority_marker(priority: Priority) -> str:
    """返回优先级标记。"""
    return {
        Priority.REQUIRED: icon("required"),
        Priority.RECOMMENDED: icon("recommended"),
        Priority.OPTIONAL: icon("optional"),
    }.get(priority, "")


def severity_marker(severity: str) -> str:
    """返回严重程度标记。"""
    return {
        "CRITICAL": icon("critical"),
        "MAJOR": icon("major"),
        "MINOR": icon("minor"),
        "INFO": icon("info"),
    }.get(severity, "")


def ensure_harness_dir_exists() -> bool:
    """检查 .harness 目录是否存在。"""
    if not get_harness_dir().exists():
        echo("错误：未找到 .harness 目录。请先创建计划或生成 spec。")
        return False
    return True


def ensure_stage(required_stage: WorkflowStage) -> bool:
    """检查当前阶段是否达到要求。"""
    workflow_store = WorkflowStateStore(get_harness_dir())
    current_stage = workflow_store.current_stage()
    ordering = {
        WorkflowStage.INIT: 0,
        WorkflowStage.DISCOVERED: 1,
        WorkflowStage.SPEC_DRAFTED: 2,
        WorkflowStage.SPEC_APPROVED: 3,
        WorkflowStage.PLAN_DRAFTED: 4,
        WorkflowStage.PLAN_APPROVED: 5,
        WorkflowStage.TASKS_READY: 6,
    }

    if ordering[current_stage] < ordering[required_stage]:
        echo(f"错误：当前阶段为 {current_stage.value}，需要至少达到 {required_stage.value}。")
        return False
    return True


def sync_plans_file(tasks: list[Task]) -> None:
    """同步 Plans.md 文件。"""
    plans_file = get_plans_file()
    required = [task for task in tasks if task.priority == Priority.REQUIRED]
    recommended = [task for task in tasks if task.priority == Priority.RECOMMENDED]
    optional = [task for task in tasks if task.priority == Priority.OPTIONAL]

    def format_task(task: Task) -> str:
        status_map = {
            TaskStatus.TODO: "[ ]",
            TaskStatus.WIP: "[~]",
            TaskStatus.DONE: "[x]",
            TaskStatus.BLOCKED: "[!]",
        }
        lines = [f"- {status_map.get(task.status, '[ ]')} **Task {task.id}**: {task.title}"]
        if task.description:
            lines.append(f"  {task.description}")
        for criterion in task.acceptance_criteria:
            lines.append(f"  - AC: {criterion}")
        lines.append(f"  - Estimate: {task.estimated_effort}")
        if task.dependencies:
            lines.append(f"  - Depends on: {task.dependencies}")
        return "\n".join(lines)

    content = ["# 计划", "", "## Tasks", ""]
    for heading, group in [
        ("### Required（必需）", required),
        ("### Recommended（推荐）", recommended),
        ("### Optional（可选）", optional),
    ]:
        if not group:
            continue
        content.extend([heading, ""])
        for task in group:
            content.extend([format_task(task), ""])

    write_text_file(plans_file, "\n".join(content))


def echo_generation_details(workflow_service: SpecWorkflowService, artifact_names: list[str]) -> None:
    """输出工件生成来源。"""
    labels = {
        "llm": "LLM provider",
        "rule-based": "本地规则",
        "fallback": "LLM 失败后回退到本地规则",
    }
    for artifact_name in artifact_names:
        source = workflow_service.generation_source(artifact_name)
        if not source:
            continue
        echo(f"  - {artifact_name}: {labels.get(source, source)}")
        note = workflow_service.generation_note(artifact_name)
        if note and source == "fallback":
            echo(f"    原因：{note}")


def parse_task_spec(store: TaskStore, task_spec: tuple[str, ...], execute_all: bool) -> list[int]:
    """解析任务规格。"""
    if execute_all or not task_spec:
        return [task.id for task in store.get_tasks_by_status(TaskStatus.TODO)]

    task_ids: list[int] = []
    for spec in task_spec:
        if "-" in spec:
            start, end = spec.split("-", maxsplit=1)
            task_ids.extend(range(int(start), int(end) + 1))
        else:
            task_ids.append(int(spec))
    return task_ids


def collect_review_files(base_dir: Path) -> list[str]:
    """递归收集适合审查的 Python 源码文件。"""
    files: list[str] = []
    for path in sorted(base_dir.rglob("*.py")):
        if any(part in REVIEW_EXCLUDED_DIRS for part in path.parts):
            continue
        if path.is_file():
            files.append(str(path))
    return files


def summarize_results(results) -> None:
    """输出执行结果统计。"""
    success_count = sum(1 for result in results if result.success)
    fail_count = len(results) - success_count
    echo("\n执行完成:")
    echo(f"  成功：{success_count}")
    echo(f"  失败：{fail_count}")


def execute_tasks_common(task_ids: list[int] | None = None, force_parallel: bool = False) -> None:
    """统一执行任务逻辑。"""
    harness_dir = get_harness_dir()
    store = TaskStore(harness_dir)
    tasks_to_execute = (
        store.get_tasks_by_status(TaskStatus.TODO) if task_ids is None else [store.get_task(task_id) for task_id in task_ids]
    )
    tasks_to_execute = [task for task in tasks_to_execute if task is not None]

    if not tasks_to_execute:
        echo("没有任务可执行。")
        return

    mode = ExecutionMode.PARALLEL if force_parallel else select_execution_mode(tasks_to_execute)
    mode_name = "Parallel" if mode == ExecutionMode.PARALLEL else "Solo"
    echo(f"=== 执行 {len(tasks_to_execute)} 个任务 ({mode_name} 模式) ===\n")

    service = TaskExecutionService(harness_dir)
    if mode == ExecutionMode.PARALLEL:
        results = service.execute_task_parallel([task.id for task in tasks_to_execute])
    else:
        results = service.execute_tasks([task.id for task in tasks_to_execute])

    history = HistoryManager(harness_dir)
    history.log_workflow_event(
        "execute_completed",
        mode=mode.value,
        task_count=len(tasks_to_execute),
        success_count=sum(1 for result in results if result.success),
    )
    summarize_results(results)


@click.group()
@click.version_option(version=__version__)
def main():
    """Spec-First Agent Harness."""


@main.command(name="init")
@click.option("--force", is_flag=True, help="覆盖并重新生成默认 LLM profile 配置")
def init_project(force: bool):
    """初始化当前工作区。"""
    config_path = initialize_project_config(force=force)
    echo("=== 项目初始化完成 ===\n")
    echo(f"元数据目录：{get_harness_dir()}")
    echo(f"LLM 配置：{config_path}")
    echo("建议在当前仓库内优先使用 `python -m sfah ...`，安装后再使用 `sfah-cli ...`。")
    echo("\n下一步：")
    echo("  1. 复制 `.env.example` 为 `.env` 并填入你的 API Key")
    echo("  2. 运行 `python -m sfah llm profiles` 或 `sfah-cli llm profiles` 查看可用 profile")
    echo("  3. 运行 `python -m sfah flow run --goal \"...\" --auto-approve` 开始一次完整流程")


@main.command(name="status")
def root_status():
    """显示整体工作流状态。"""
    initialize_project_config()
    harness_dir = get_harness_dir()
    workflow_store = WorkflowStateStore(harness_dir)
    workflow_service = SpecWorkflowService()
    store = TaskStore(harness_dir)
    state = workflow_store.load()
    stats = store.get_statistics()
    artifacts = ArtifactStore(harness_dir)
    provider_status = workflow_service.provider_status()

    echo("=== 工作流状态 ===\n")
    echo(f"阶段：{state.get('stage', WorkflowStage.INIT.value)}")
    echo(f"目标：{state.get('goal') or '未设置'}")
    echo(f"Spec 已批准：{'是' if state.get('spec_approved') else '否'}")
    echo(f"Plan 已批准：{'是' if state.get('plan_approved') else '否'}")
    echo("")
    echo("LLM Provider:")
    echo(f"  Profile：{provider_status.get('profile', 'n/a')}")
    echo(f"  Provider：{provider_status.get('provider', 'n/a')}")
    echo(f"  已配置：{'是' if provider_status['configured'] else '否'}")
    echo(f"  模型：{provider_status['summary']}")
    echo(f"  API Key：{provider_status['api_key']}")
    echo(f"  API Key Env：{provider_status.get('api_key_env', 'n/a')}")
    echo("")
    echo("工件:")
    for artifact_name in ["discovery", "spec", "plan", "tasks"]:
        path = artifacts.path_for(artifact_name)
        status_text = "已生成" if path.exists() else "未生成"
        echo(f"  - {artifact_name}: {status_text}")

    echo("")
    echo("任务概览:")
    echo(f"  总数：{stats['total']}")
    echo(f"  TODO：{stats['todo']}")
    echo(f"  WIP：{stats['wip']}")
    echo(f"  DONE：{stats['done']}")
    echo(f"  BLOCKED：{stats['blocked']}")


@main.group()
def discover():
    """Discovery 阶段命令。"""


@discover.command("start")
@click.option("--goal", "-g", help="用户目标")
@click.option("--context", "-c", default="", help="补充上下文")
@click.option("--constraint", "-k", multiple=True, help="约束条件，可重复传入")
def discover_start(goal: str | None, context: str, constraint: tuple[str, ...]):
    """生成 discovery 工件。"""
    initialize_project_config()
    if not goal:
        goal = click.prompt("请描述你的目标")

    harness_dir = get_harness_dir()
    workflow_service = SpecWorkflowService()
    workflow_store = WorkflowStateStore(harness_dir)
    artifact_store = ArtifactStore(harness_dir)
    history = HistoryManager(harness_dir)

    result = workflow_service.build_discovery(goal=goal, context=context, constraints=constraint)
    artifact_path = artifact_store.save("discovery", workflow_service.render_discovery_markdown(result))
    workflow_store.set_discovery(result)
    workflow_store.mark_artifact("discovery", artifact_path, WorkflowStage.DISCOVERED)
    history.log_workflow_event(
        "discovery_generated",
        goal=result.goal,
        artifact=str(artifact_path),
        source=workflow_service.generation_source("discovery"),
    )

    echo(f"已生成 discovery 工件：{artifact_path.name}")
    echo_generation_details(workflow_service, ["discovery"])
    echo("建议先审阅 discovery，再运行 `sfah-cli spec create` 生成规格。")


@discover.command("show")
def discover_show():
    """显示 discovery 工件。"""
    artifact_store = ArtifactStore(get_harness_dir())
    if not artifact_store.exists("discovery"):
        echo("尚未生成 discovery.md。先运行 `sfah-cli discover start`。")
        return
    echo(artifact_store.load("discovery"))


@main.group()
def spec():
    """Spec 阶段命令。"""


@main.group()
def flow():
    """端到端流程命令。"""


@main.group()
def llm():
    """LLM provider 命令。"""


@flow.command("run")
@click.option("--goal", "-g", required=True, help="用户目标")
@click.option("--context", "-c", default="", help="补充上下文")
@click.option("--constraint", "-k", multiple=True, help="约束条件，可重复传入")
@click.option("--auto-approve", is_flag=True, help="自动批准 spec 和 plan，并生成 tasks")
@click.option("--replace-tasks", is_flag=True, help="若已有任务则覆盖重建")
@click.option("--execute", "execute_after", is_flag=True, help="生成任务后立即执行所有 TODO 任务")
def flow_run(
    goal: str,
    context: str,
    constraint: tuple[str, ...],
    auto_approve: bool,
    replace_tasks: bool,
    execute_after: bool,
):
    """根据目标跑一遍完整 spec-first 流程。"""
    initialize_project_config()
    harness_dir = get_harness_dir()
    workflow_service = SpecWorkflowService()
    workflow_store = WorkflowStateStore(harness_dir)
    artifact_store = ArtifactStore(harness_dir)
    history = HistoryManager(harness_dir)
    store = TaskStore(harness_dir)

    result = workflow_service.build_discovery(goal=goal, context=context, constraints=constraint)
    discovery_path = artifact_store.save("discovery", workflow_service.render_discovery_markdown(result))
    spec_path = artifact_store.save("spec", workflow_service.render_spec_markdown(result))
    workflow_store.set_discovery(result)
    workflow_store.mark_artifact("discovery", discovery_path, WorkflowStage.DISCOVERED)
    workflow_store.mark_artifact("spec", spec_path, WorkflowStage.SPEC_DRAFTED)
    history.log_workflow_event(
        "flow_run_spec_generated",
        goal=result.goal,
        discovery_source=workflow_service.generation_source("discovery"),
        spec_source=workflow_service.generation_source("spec"),
    )

    echo("=== Flow Run ===\n")
    echo(f"已生成 discovery 和 spec，当前目标：{result.goal}")
    echo_generation_details(workflow_service, ["discovery", "spec"])

    if not auto_approve:
        echo("\n当前为人工审阅模式。下一步：")
        echo("  1. `sfah-cli spec show` 查看 spec")
        echo("  2. `sfah-cli spec approve`")
        echo("  3. `sfah-cli plan create`")
        return

    workflow_store.approve_spec()
    history.log_workflow_event("flow_run_spec_approved", artifact=str(spec_path))

    plan_content = workflow_service.render_plan_markdown(workflow_store.load())
    plan_path = artifact_store.save("plan", plan_content)
    workflow_store.mark_artifact("plan", plan_path, WorkflowStage.PLAN_DRAFTED)
    workflow_store.approve_plan()
    history.log_workflow_event(
        "flow_run_plan_generated",
        artifact=str(plan_path),
        source=workflow_service.generation_source("plan"),
    )
    echo_generation_details(workflow_service, ["plan"])

    existing_tasks = store.load_tasks()
    if existing_tasks and not replace_tasks:
        echo("\n已生成 plan，但当前已有任务列表。")
        echo("使用 `sfah-cli tasks generate --replace` 或重新运行 `sfah-cli flow run --replace-tasks` 覆盖任务。")
        return

    generated_tasks = workflow_service.build_tasks(workflow_store.load(), start_id=1)
    store.save_tasks(generated_tasks)
    sync_plans_file(generated_tasks)
    tasks_path = artifact_store.save("tasks", workflow_service.render_tasks_markdown(generated_tasks))
    workflow_store.mark_artifact("tasks", tasks_path, WorkflowStage.TASKS_READY)
    workflow_store.mark_tasks_ready(len(generated_tasks))
    for task in generated_tasks:
        history.log_task_created(task)
    history.log_workflow_event(
        "flow_run_tasks_generated",
        artifact=str(tasks_path),
        task_count=len(generated_tasks),
        source=workflow_service.generation_source("tasks"),
    )
    echo_generation_details(workflow_service, ["tasks"])
    echo(f"\n已完成工件生成，共得到 {len(generated_tasks)} 个任务。")

    if execute_after:
        echo("\n开始执行所有 TODO 任务...\n")
        execute_tasks_common()


@llm.command("init")
@click.option("--force", is_flag=True, help="覆盖并重新生成默认 LLM profile 配置")
def llm_init(force: bool):
    """初始化 `.harness/llm.json`。"""
    config_path = initialize_project_config(force=force)
    echo(f"已初始化 LLM profile 配置：{config_path}")


@llm.command("status")
def llm_status():
    """显示 LLM provider 配置。"""
    initialize_project_config()
    provider_status = SpecWorkflowService().provider_status()
    registry = LLMRegistry.load()

    echo("=== LLM Provider ===\n")
    echo(f"配置文件：{registry.config_path}")
    echo(f"Active Profile：{provider_status.get('profile', 'n/a')}")
    echo(f"Provider：{provider_status.get('provider', 'n/a')}")
    echo(f"已配置：{'是' if provider_status['configured'] else '否'}")
    echo(f"模型：{provider_status['summary']}")
    echo(f"API Key：{provider_status['api_key']}")
    echo(f"API Key Env：{provider_status.get('api_key_env', 'n/a')}")
    if not provider_status["configured"]:
        echo("\n提示：在当前目录或上级目录放置 `.env`，并填入 active profile 对应的 key。")


@llm.command("profiles")
def llm_profiles():
    """列出全部 LLM profile。"""
    initialize_project_config()
    registry = LLMRegistry.load()

    echo("=== LLM Profiles ===\n")
    for profile in registry.list_profiles():
        resolved = registry.resolve_profile(profile.name)
        marker = "*" if profile.name == registry.project_config.active_profile else " "
        echo(f"{marker} {profile.name}")
        echo(f"  provider: {profile.provider.value}")
        echo(f"  model: {resolved.model}")
        echo(f"  base_url: {resolved.base_url or 'n/a'}")
        echo(f"  configured: {'是' if resolved.is_configured else '否'}")
        echo(f"  api_key_env: {resolved.api_key_env or 'n/a'}")
        echo("")


@llm.command("show")
@click.argument("profile_name", required=False)
def llm_show(profile_name: str | None):
    """显示单个 profile 的完整配置。"""
    initialize_project_config()
    registry = LLMRegistry.load()
    profile = registry.get_profile(profile_name)
    if profile is None:
        available = ", ".join(item.name for item in registry.list_profiles())
        raise click.ClickException(f"未找到 profile：{profile_name or registry.project_config.active_profile}。可用 profile: {available}")

    resolved = registry.resolve_profile(profile.name)
    echo("=== Profile Detail ===\n")
    echo(f"name: {profile.name}")
    echo(f"provider: {profile.provider.value}")
    echo(f"model: {resolved.model}")
    echo(f"base_url: {resolved.base_url or 'n/a'}")
    echo(f"configured: {'是' if resolved.is_configured else '否'}")
    echo(f"api_key_env: {resolved.api_key_env or 'n/a'}")
    echo(f"temperature: {resolved.temperature}")
    echo(f"max_tokens: {resolved.max_tokens}")
    echo(f"timeout_seconds: {resolved.timeout_seconds}")
    if resolved.extra_headers:
        echo("headers:")
        for key, value in resolved.extra_headers.items():
            echo(f"  {key}: {value}")


@llm.command("add-profile")
@click.option("--name", required=True, help="profile 名称")
@click.option(
    "--provider",
    "provider_name",
    required=True,
    type=click.Choice([item.value for item in ProviderType], case_sensitive=False),
    help="provider 类型",
)
@click.option("--model", required=True, help="模型名称")
@click.option("--base-url", default="", help="provider base URL")
@click.option("--api-key-env", default="", help="API key 对应的环境变量名")
@click.option("--timeout", "timeout_seconds", type=int, default=90, show_default=True, help="请求超时秒数")
@click.option("--temperature", type=float, default=0.2, show_default=True, help="默认温度")
@click.option("--max-tokens", type=int, default=4096, show_default=True, help="最大输出 token")
@click.option("--header", "header_values", multiple=True, help="附加 header，格式为 Key=Value")
@click.option("--activate", is_flag=True, help="创建后立即切换为 active profile")
def llm_add_profile(
    name: str,
    provider_name: str,
    model: str,
    base_url: str,
    api_key_env: str,
    timeout_seconds: int,
    temperature: float,
    max_tokens: int,
    header_values: tuple[str, ...],
    activate: bool,
):
    """新增或覆盖一个 profile。"""
    initialize_project_config()
    registry = LLMRegistry.load()
    profile = LLMProfile(
        name=name.strip(),
        provider=ProviderType(provider_name.lower()),
        model=model.strip(),
        base_url=base_url.strip(),
        api_key_env=api_key_env.strip(),
        timeout_seconds=max(10, timeout_seconds),
        temperature=temperature,
        max_tokens=max(128, max_tokens),
        extra_headers=parse_headers(header_values),
    )
    registry.upsert_profile(profile, make_active=activate)
    echo(f"已保存 profile：{profile.name} ({profile.provider.value})")
    if activate:
        echo("已设为当前 active profile。")


@llm.command("remove-profile")
@click.argument("profile_name")
def llm_remove_profile(profile_name: str):
    """移除一个 profile。"""
    initialize_project_config()
    registry = LLMRegistry.load()
    profile = registry.remove_profile(profile_name)
    echo(f"已删除 profile：{profile.name}")


@llm.command("use")
@click.argument("profile_name")
def llm_use(profile_name: str):
    """切换 active profile。"""
    initialize_project_config()
    registry = LLMRegistry.load()
    profile = registry.set_active_profile(profile_name)
    echo(f"已切换 active profile：{profile.name} ({profile.provider.value})")


@llm.command("test")
@click.option("--profile", "profile_name", help="指定 profile；默认使用当前 active profile")
@click.option(
    "--prompt",
    default="Summarize what a spec-first agent harness does in one sentence.",
    show_default=True,
    help="测试提示词",
)
def llm_test(profile_name: str | None, prompt: str):
    """发送一条简单请求验证 LLM 配置。"""
    initialize_project_config()
    provider = build_default_provider(profile_name=profile_name)
    status = provider.status()
    echo("=== LLM Test ===\n")
    echo(f"Profile：{status.get('profile', 'n/a')}")
    echo(f"Provider：{status.get('provider', 'n/a')}")
    echo(f"模型：{status.get('summary', 'n/a')}")
    if not provider.is_configured():
        echo("当前 profile 未配置完整 API Key，无法发起真实调用。")
        return

    result = provider.generate_text(
        "You are a concise assistant. Reply in 1-2 short sentences.",
        prompt,
    )
    echo("\n响应：")
    echo(result)


@spec.command("create")
@click.option("--goal", "-g", help="用户目标；未提供时尝试从 discovery 读取")
@click.option("--context", "-c", default="", help="补充上下文")
@click.option("--constraint", "-k", multiple=True, help="约束条件，可重复传入")
def create_spec(goal: str | None, context: str, constraint: tuple[str, ...]):
    """生成 spec 工件。"""
    initialize_project_config()
    harness_dir = get_harness_dir()
    workflow_service = SpecWorkflowService()
    workflow_store = WorkflowStateStore(harness_dir)
    artifact_store = ArtifactStore(harness_dir)
    history = HistoryManager(harness_dir)

    state = workflow_store.load()
    if not goal:
        goal = state.get("goal") or click.prompt("请描述你的目标")

    result = workflow_service.build_discovery(
        goal=goal,
        context=context or state.get("context", ""),
        constraints=constraint or tuple(state.get("constraints", [])),
    )
    discovery_path = artifact_store.save("discovery", workflow_service.render_discovery_markdown(result))
    spec_path = artifact_store.save("spec", workflow_service.render_spec_markdown(result))

    workflow_store.set_discovery(result)
    workflow_store.mark_artifact("discovery", discovery_path, WorkflowStage.DISCOVERED)
    workflow_store.mark_artifact("spec", spec_path, WorkflowStage.SPEC_DRAFTED)
    history.log_workflow_event(
        "spec_generated",
        goal=result.goal,
        artifact=str(spec_path),
        discovery_source=workflow_service.generation_source("discovery"),
        spec_source=workflow_service.generation_source("spec"),
    )

    echo(f"已生成 spec 工件：{spec_path.name}")
    echo_generation_details(workflow_service, ["discovery", "spec"])
    echo("请审改 spec 后运行 `sfah-cli spec approve` 进入下一阶段。")


@spec.command("show")
def show_spec():
    """显示 spec 工件。"""
    artifact_store = ArtifactStore(get_harness_dir())
    if not artifact_store.exists("spec"):
        echo("尚未生成 spec.md。先运行 `sfah-cli spec create`。")
        return
    echo(artifact_store.load("spec"))


@spec.command("approve")
def approve_spec():
    """批准 spec 工件。"""
    artifact_store = ArtifactStore(get_harness_dir())
    workflow_store = WorkflowStateStore(get_harness_dir())
    history = HistoryManager(get_harness_dir())

    if not artifact_store.exists("spec"):
        echo("错误：尚未生成 spec.md。")
        return

    workflow_store.approve_spec()
    history.log_workflow_event("spec_approved", artifact=str(artifact_store.path_for("spec")))
    echo("已批准 spec。现在可以运行 `sfah-cli plan create`。")


@main.group()
def plan():
    """计划管理命令。"""


@plan.command()
def create():
    """创建执行计划。"""
    initialize_project_config()
    harness_dir = get_harness_dir()
    workflow_store = WorkflowStateStore(harness_dir)
    artifact_store = ArtifactStore(harness_dir)
    history = HistoryManager(harness_dir)

    if not artifact_store.exists("spec"):
        echo("错误：尚未生成 spec。请先运行 `sfah-cli spec create`。")
        return
    if not workflow_store.load().get("spec_approved"):
        echo("错误：spec 还未批准。请先运行 `sfah-cli spec approve`。")
        return

    state = workflow_store.load()
    workflow_service = SpecWorkflowService()
    plan_content = workflow_service.render_plan_markdown(state)
    plan_path = artifact_store.save("plan", plan_content)
    workflow_store.mark_artifact("plan", plan_path, WorkflowStage.PLAN_DRAFTED)
    history.log_workflow_event(
        "plan_generated",
        goal=state.get("goal", ""),
        artifact=str(plan_path),
        source=workflow_service.generation_source("plan"),
    )

    echo(f"已生成 plan 工件：{plan_path.name}")
    echo_generation_details(workflow_service, ["plan"])
    echo("请审改 plan 后运行 `sfah-cli plan approve`。")


@plan.command("approve")
def approve_plan():
    """批准计划工件。"""
    artifact_store = ArtifactStore(get_harness_dir())
    workflow_store = WorkflowStateStore(get_harness_dir())
    history = HistoryManager(get_harness_dir())

    if not artifact_store.exists("plan"):
        echo("错误：尚未生成 plan.md。")
        return

    workflow_store.approve_plan()
    history.log_workflow_event("plan_approved", artifact=str(artifact_store.path_for("plan")))
    echo("已批准 plan。现在可以运行 `sfah-cli tasks generate`。")


@plan.command("show")
@click.argument("task_id", type=int, required=False)
def show(task_id: int | None):
    """显示任务详情或计划工件。"""
    if task_id is None:
        artifact_store = ArtifactStore(get_harness_dir())
        if not artifact_store.exists("plan"):
            echo("尚未生成 plan.md。")
            return
        echo(artifact_store.load("plan"))
        return

    harness_dir = get_harness_dir()
    store = TaskStore(harness_dir)
    task = store.get_task(task_id)
    if not task:
        echo(f"未找到任务 #{task_id}")
        return

    echo(f"\n=== 任务 #{task_id}: {task.title} ===\n")
    echo(f"状态：{task.status.value}")
    echo(f"优先级：{task.priority.value}")
    echo(f"估算工作量：{task.estimated_effort}")
    if task.actual_effort:
        echo(f"实际工作量：{task.actual_effort}")
    echo(f"\n描述:\n{task.description or '无'}\n")
    if task.acceptance_criteria:
        echo("验收标准:")
        for criterion in task.acceptance_criteria:
            echo(f"  - {criterion}")
        echo("")
    if task.dependencies:
        echo(f"依赖：{task.dependencies}")
        echo("")


@plan.command()
@click.argument("task_id", type=int)
@click.option("--status", "-s", type=click.Choice(["TODO", "WIP", "DONE", "BLOCKED"], case_sensitive=False), required=True)
@click.option("--reason", "-r", help="阻塞原因（当状态为 BLOCKED 时）")
def update(task_id: int, status: str, reason: str | None):
    """更新任务状态。"""
    harness_dir = get_harness_dir()
    store = TaskStore(harness_dir)
    history = HistoryManager(harness_dir)

    task = store.get_task(task_id)
    if not task:
        echo(f"未找到任务 #{task_id}")
        return

    old_status = task.status
    task.status = TaskStatus.from_string(status)

    if task.status == TaskStatus.BLOCKED and reason:
        task.block(reason)
    elif task.status == TaskStatus.DONE:
        task.complete()
    elif task.status == TaskStatus.WIP:
        task.start()

    store.update_task(task)
    history.log_task_updated(task, ["status"])
    echo(f"任务 #{task_id} 状态已更新：{old_status.value} -> {task.status.value}")


@plan.command()
def sync():
    """同步 Plans.md 和状态。"""
    harness_dir = get_harness_dir()
    store = TaskStore(harness_dir)
    tasks = store.load_tasks()
    sync_plans_file(tasks)
    echo(f"已同步 {len(tasks)} 个任务到 Plans.md")


@plan.command()
@click.option("--title", "-t", help="任务标题")
@click.option("--description", "-d", help="任务描述")
@click.option("--priority", "-p", type=click.Choice(["REQUIRED", "RECOMMENDED", "OPTIONAL"], case_sensitive=False), default="REQUIRED")
@click.option("--estimate", "-e", type=int, default=1, help="估算工作量 (1-5)")
def add(title: str | None, description: str | None, priority: str, estimate: int):
    """添加新任务（交互式或参数式）。"""
    harness_dir = get_harness_dir()
    store = TaskStore(harness_dir)
    history = HistoryManager(harness_dir)

    if not title:
        title = click.prompt("任务标题")
        description = click.prompt("任务描述（可选）", default="")
        priority = click.prompt("优先级", type=click.Choice(["REQUIRED", "RECOMMENDED", "OPTIONAL"]), default="REQUIRED")
        estimate = click.prompt("估算工作量 (1-5)", type=int, default=1)

    task_id = store.get_next_task_id()
    task = Task(
        id=task_id,
        title=title,
        description=description or "",
        priority=Priority.from_string(priority),
        estimated_effort=estimate,
    )
    store.add_task(task)
    history.log_task_created(task)
    echo(f"已添加任务 #{task_id}: {task.title}")


@plan.command("list")
def list_tasks():
    """列出所有任务。"""
    harness_dir = get_harness_dir()
    store = TaskStore(harness_dir)
    tasks = store.load_tasks()
    if not tasks:
        echo("没有任务。使用 `sfah-cli plan add` 添加任务。")
        return

    echo("\n=== 任务列表 ===\n")
    for task in tasks:
        status_icon = {
            TaskStatus.TODO: "[ ]",
            TaskStatus.WIP: "[~]",
            TaskStatus.DONE: "[x]",
            TaskStatus.BLOCKED: "[!]",
        }.get(task.status, "[ ]")
        echo(f"{status_icon} {task.id}. {task.title} {priority_marker(task.priority)}")
        if task.description:
            echo(f"    {task.description}")
        echo("")


@plan.command("stats")
def statistics():
    """显示任务统计。"""
    harness_dir = get_harness_dir()
    store = TaskStore(harness_dir)
    stats = store.get_statistics()

    echo("\n=== 任务统计 ===\n")
    echo(f"总数：{stats['total']}")
    echo(f"待办 (TODO): {stats['todo']}")
    echo(f"进行中 (WIP): {stats['wip']}")
    echo(f"已完成 (DONE): {stats['done']}")
    echo(f"被阻塞 (BLOCKED): {stats['blocked']}")
    echo(f"\n进度：{stats['progress_percent']}%")


@main.group()
def tasks():
    """任务拆解命令。"""


@tasks.command("generate")
@click.option("--replace", is_flag=True, help="覆盖当前任务列表")
def generate_tasks(replace: bool):
    """根据批准后的计划生成任务列表。"""
    initialize_project_config()
    harness_dir = get_harness_dir()
    workflow_store = WorkflowStateStore(harness_dir)
    artifact_store = ArtifactStore(harness_dir)
    service = SpecWorkflowService()
    store = TaskStore(harness_dir)
    history = HistoryManager(harness_dir)

    state = workflow_store.load()
    if not state.get("plan_approved"):
        echo("错误：plan 还未批准。请先运行 `sfah-cli plan approve`。")
        return

    existing_tasks = store.load_tasks()
    if existing_tasks and not replace:
        echo("错误：当前已有任务。若要重建，请使用 `sfah-cli tasks generate --replace`。")
        return

    generated_tasks = service.build_tasks(state, start_id=1)
    store.save_tasks(generated_tasks)
    sync_plans_file(generated_tasks)

    tasks_markdown = service.render_tasks_markdown(generated_tasks)
    tasks_path = artifact_store.save("tasks", tasks_markdown)
    workflow_store.mark_artifact("tasks", tasks_path, WorkflowStage.TASKS_READY)
    workflow_store.mark_tasks_ready(len(generated_tasks))

    for task in generated_tasks:
        history.log_task_created(task)
    history.log_workflow_event(
        "tasks_generated",
        artifact=str(tasks_path),
        task_count=len(generated_tasks),
        source=service.generation_source("tasks"),
    )

    echo(f"已生成 {len(generated_tasks)} 个任务，并同步到 Plans.md。")
    echo_generation_details(service, ["tasks"])


@tasks.command("show")
def show_tasks_artifact():
    """显示 tasks 工件。"""
    artifact_store = ArtifactStore(get_harness_dir())
    if not artifact_store.exists("tasks"):
        echo("尚未生成 tasks.md。先运行 `sfah-cli tasks generate`。")
        return
    echo(artifact_store.load("tasks"))


@main.group()
def work():
    """任务执行命令。"""


@work.command()
@click.argument("task_id", type=int)
def solo(task_id: int):
    """以 Solo 模式执行单个任务。"""
    if not ensure_harness_dir_exists():
        return

    harness_dir = get_harness_dir()
    store = TaskStore(harness_dir)
    task = store.get_task(task_id)
    if not task:
        echo(f"错误：未找到任务 #{task_id}")
        return

    echo(f"=== 执行任务 #{task_id}: {task.title} (Solo 模式) ===\n")
    service = TaskExecutionService(harness_dir)
    result = service.execute_task_solo(task_id)
    HistoryManager(harness_dir).log_workflow_event("execute_solo", task_id=task_id, success=result.success)

    if result.success:
        echo(f"{icon('success')} 任务执行成功")
        echo(f"\n执行输出:\n{result.output}")
    else:
        echo(f"{icon('error')} 任务执行失败")
        echo(f"\n错误：{result.error}")
        echo(f"\n执行输出:\n{result.output}")


@work.command()
def parallel():
    """以 Parallel 模式执行所有 TODO 任务。"""
    if not ensure_harness_dir_exists():
        return
    execute_tasks_common(force_parallel=True)


@work.command(name="all")
@click.argument("task_spec", nargs=-1)
@click.option("--all", "execute_all_flag", is_flag=True, help="执行所有 TODO 任务")
def work_all(task_spec: tuple[str, ...], execute_all_flag: bool):
    """执行任务。"""
    if not ensure_harness_dir_exists():
        return

    task_store = TaskStore(get_harness_dir())
    task_ids = parse_task_spec(task_store, task_spec, execute_all_flag)
    execute_tasks_common(task_ids or None)


@work.command(name="status")
def work_status():
    """显示执行状态。"""
    if not ensure_harness_dir_exists():
        return

    harness_dir = get_harness_dir()
    store = TaskStore(harness_dir)
    history = HistoryManager(harness_dir)
    workflow_state = WorkflowStateStore(harness_dir).load()
    stats = store.get_statistics()
    recent_events = history.get_recent_events(8)

    echo("\n=== 执行状态 ===\n")
    echo(f"阶段：{workflow_state.get('stage', WorkflowStage.INIT.value)}")
    echo(f"总任务数：{stats['total']}")
    echo(f"待执行：{stats['todo']}")
    echo(f"进行中：{stats['wip']}")
    echo(f"已完成：{stats['done']}")
    echo(f"被阻塞：{stats['blocked']}")
    echo(f"\n进度：{stats['progress_percent']}%")

    if recent_events:
        echo("\n最近事件:")
        for event in recent_events:
            timestamp = event.get("timestamp", "")[:19]
            event_type = event.get("event", "unknown")
            task_id = event.get("task_id")
            artifact = event.get("artifact")
            if task_id is not None:
                echo(f"  [{timestamp}] {event_type}: #{task_id} {event.get('task_title', '')}".rstrip())
            elif artifact:
                echo(f"  [{timestamp}] {event_type}: {artifact}")
            else:
                echo(f"  [{timestamp}] {event_type}")


@main.group(name="execute")
def execute_group():
    """执行命令（work 的别名）。"""


@execute_group.command("solo")
@click.argument("task_id", type=int)
def execute_solo(task_id: int):
    """别名：执行单个任务。"""
    solo.callback(task_id)  # type: ignore[attr-defined]


@execute_group.command("parallel")
def execute_parallel():
    """别名：并行执行任务。"""
    parallel.callback()  # type: ignore[attr-defined]


@execute_group.command("all")
@click.argument("task_spec", nargs=-1)
@click.option("--all", "execute_all_flag", is_flag=True, help="执行所有 TODO 任务")
def execute_all(task_spec: tuple[str, ...], execute_all_flag: bool):
    """别名：执行任务。"""
    work_all.callback(task_spec, execute_all_flag)  # type: ignore[attr-defined]


@execute_group.command("status")
def execute_status():
    """别名：显示执行状态。"""
    work_status.callback()  # type: ignore[attr-defined]


@main.group()
def review():
    """代码审查命令。"""


@review.command()
@click.argument("file_path", nargs=-1, required=False)
@click.option("--all", "review_all", is_flag=True, help="递归审查当前项目中的 Python 源码文件")
def code(file_path: tuple[str, ...], review_all: bool):
    """审查代码文件。"""
    if not file_path and not review_all:
        files = list(Path.cwd().glob("*.py"))
        if not files:
            files = [Path(path) for path in collect_review_files(Path.cwd())]
            if not files:
                echo("错误：未指定文件，且当前目录没有可审查的 Python 源码文件。")
                echo("使用 `sfah-cli review code <文件路径>` 指定文件。")
                return
        file_path = tuple(str(path) for path in files)

    if review_all:
        file_path = tuple(collect_review_files(Path.cwd()))
        if not file_path:
            echo("没有 Python 源码文件可审查。")
            return

    reviewer = ReviewerAgent()
    all_issues = []

    for fp in file_path:
        path = Path(fp)
        if not path.exists():
            echo(f"警告：文件不存在 {fp}")
            continue

        code_content = read_text_file(path)
        result = reviewer.review_code(code_content, fp)

        echo(f"\n=== 审查：{fp} ===")
        echo(f"判定：{result.verdict.value}")

        if result.issues:
            echo(f"\n发现 {len(result.issues)} 个问题:")
            for issue in result.issues:
                echo(f"\n  {severity_marker(issue.severity.value)} [{issue.severity.value}] {issue.category.value}")
                echo(f"     {issue.message}")
                echo(f"     {fp}:{issue.line}")
                if issue.suggestion:
                    echo(f"     建议：{issue.suggestion}")
        else:
            echo(f"  没有问题 {icon('success')}")

        all_issues.extend(result.issues)

    echo("\n=== 审查总结 ===")
    critical = sum(1 for issue in all_issues if issue.severity.value == "CRITICAL")
    major = sum(1 for issue in all_issues if issue.severity.value == "MAJOR")
    minor = sum(1 for issue in all_issues if issue.severity.value == "MINOR")
    info = sum(1 for issue in all_issues if issue.severity.value == "INFO")

    if critical or major:
        echo(f"需要修改：{critical} 个严重，{major} 个主要问题")
    else:
        echo(f"批准：{minor} 个次要，{info} 个提示")


@review.command()
@click.argument("plan_id", type=str, required=False)
def plan(plan_id: str | None):
    """审查计划与工作流状态。"""
    if not ensure_harness_dir_exists():
        return

    harness_dir = get_harness_dir()
    store = TaskStore(harness_dir)
    workflow_state = WorkflowStateStore(harness_dir).load()
    artifacts = ArtifactStore(harness_dir)
    tasks_list = store.load_tasks()

    echo("=== 计划审查 ===\n")
    issues: list[str] = []

    if not artifacts.exists("spec"):
        issues.append("尚未生成 spec.md")
    elif not workflow_state.get("spec_approved"):
        issues.append("spec 尚未批准")

    if artifacts.exists("plan") and not workflow_state.get("plan_approved"):
        issues.append("plan 尚未批准")

    if not tasks_list:
        issues.append("没有任务可审查")
    else:
        task_ids = {task.id for task in tasks_list}
        for task in tasks_list:
            for dep_id in task.dependencies:
                if dep_id not in task_ids:
                    issues.append(f"任务 {task.id} 依赖不存在的任务 {dep_id}")
            if not task.acceptance_criteria and task.priority == Priority.REQUIRED:
                issues.append(f"任务 {task.id} ({task.title}) 缺少验收标准")
            if task.dependencies and task.priority == Priority.REQUIRED:
                for dep_id in task.dependencies:
                    dep_task = store.get_task(dep_id)
                    if dep_task and dep_task.priority == Priority.OPTIONAL:
                        issues.append(f"Required 任务 {task.id} 依赖 Optional 任务 {dep_id}")

    if issues:
        echo(f"发现 {len(issues)} 个问题:\n")
        for issue in issues:
            echo(f"  - {issue}")
        return

    echo(f"计划审查通过 {icon('success')}")
    echo(f"总任务数：{len(tasks_list)}")
    echo(f"  Required: {sum(1 for task in tasks_list if task.priority == Priority.REQUIRED)}")
    echo(f"  Recommended: {sum(1 for task in tasks_list if task.priority == Priority.RECOMMENDED)}")
    echo(f"  Optional: {sum(1 for task in tasks_list if task.priority == Priority.OPTIONAL)}")


@review.command()
def last():
    """显示最近事件。"""
    if not ensure_harness_dir_exists():
        return

    history = HistoryManager(get_harness_dir())
    recent_events = history.get_recent_events(10)

    if not recent_events:
        echo("没有历史记录。")
        return

    echo("=== 最近事件 ===\n")
    for event in recent_events:
        timestamp = event.get("timestamp", "")[:19]
        event_type = event.get("event", "unknown")
        task_id = event.get("task_id")
        task_title = event.get("task_title", "")
        artifact = event.get("artifact")

        if task_id is not None:
            echo(f"[{timestamp}] {event_type}: #{task_id} {task_title}".rstrip())
        elif artifact:
            echo(f"[{timestamp}] {event_type}: {artifact}")
        else:
            echo(f"[{timestamp}] {event_type}")


if __name__ == "__main__":
    main()


