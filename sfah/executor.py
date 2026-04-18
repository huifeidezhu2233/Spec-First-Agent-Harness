"""Task execution and artifact recording."""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

from sfah.io_utils import write_text_file
from sfah.models import Task, TaskStatus


class ExecutionMode(Enum):
    """执行模式枚举"""
    SOLO = "SOLO"
    PARALLEL = "PARALLEL"


@dataclass
class ExecutionResult:
    """执行结果"""
    task_id: int
    task_title: str
    success: bool
    output: str = ""
    error: str = ""
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "task_id": self.task_id,
            "task_title": self.task_title,
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
        }


class WorkerAgent:
    """工作 Agent - 执行单个任务"""

    def __init__(self, task: Task, llm_provider=None, work_dir: str = ""):
        """初始化 Worker Agent

        Args:
            task: 要执行的任务
        """
        self.task = task
        self.llm_provider = llm_provider
        self.work_dir = work_dir
        self.status = "idle"
        self.output: List[str] = []
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None

    def capture_output(self, line: str):
        """捕获输出行

        Args:
            line: 输出行
        """
        self.output.append(line)

    def update_status(self, status: str):
        """更新状态

        Args:
            status: 新状态
        """
        self.status = status

    def execute(self) -> ExecutionResult:
        """执行任务

        Returns:
            执行结果
        """
        self.started_at = datetime.now()
        self.update_status("running")
        self.capture_output(f"开始执行任务：{self.task.title}")

        try:
            # 模拟任务执行
            self._execute_task()
            success = True
        except Exception as e:
            self.capture_output(f"错误：{str(e)}")
            success = False

        self.completed_at = datetime.now()
        self.update_status("completed")

        duration = (self.completed_at - self.started_at).total_seconds()

        return ExecutionResult(
            task_id=self.task.id,
            task_title=self.task.title,
            success=success,
            output="\n".join(self.output),
            started_at=self.started_at,
            completed_at=self.completed_at,
            duration_seconds=duration
        )

    def _execute_task(self):
        """执行任务逻辑（基础实现）"""
        self.capture_output(f"任务描述：{self.task.description or '无'}")
        if self.task.acceptance_criteria:
            self.capture_output("验收标准:")
            for criterion in self.task.acceptance_criteria:
                self.capture_output(f"  - {criterion}")
        self.capture_output("")
        self.capture_output("建议执行步骤:")
        for line in self._build_execution_brief().splitlines():
            self.capture_output(line)

    def _build_execution_brief(self) -> str:
        """生成任务执行说明。"""
        if self.llm_provider and self.llm_provider.is_configured():
            try:
                return self.llm_provider.generate_markdown(
                    "你是一个谨慎的工程执行助手。请输出中文 markdown，帮助开发者完成单个任务。",
                    (
                        "请为下面的任务生成一份可执行的实施说明。\n\n"
                        f"任务标题: {self.task.title}\n"
                        f"任务描述: {self.task.description or '无'}\n"
                        f"验收标准: {self.task.acceptance_criteria}\n"
                        f"工作目录: {self.work_dir or '当前项目根目录'}\n\n"
                        "要求:\n"
                        "- 包含 `## 实施步骤`、`## 建议改动点`、`## 验证方式`\n"
                        "- 输出要聚焦当前任务，不要扩展范围\n"
                        "- 不要输出代码块围栏\n"
                    ),
                ).strip()
            except Exception as exc:  # pragma: no cover - 容错输出
                return self._fallback_execution_brief(f"LLM 生成失败，已回退到本地执行模板：{exc}")

        return self._fallback_execution_brief()

    def _fallback_execution_brief(self, prefix: str = "") -> str:
        """生成本地规则版执行说明。"""
        lines: List[str] = []
        if prefix:
            lines.append(prefix)
            lines.append("")
        lines.extend(
            [
                "## 实施步骤",
                "1. 先确认当前任务涉及的输入、输出和边界条件。",
                "2. 围绕核心路径完成实现，再补齐错误处理和异常路径。",
                "3. 对照验收标准逐项检查，避免把未确认的扩展内容带入本次任务。",
                "",
                "## 建议改动点",
                f"- 优先围绕“{self.task.title}”直接相关的模块推进改动。",
                f"- 工作目录：{self.work_dir or '当前项目根目录'}",
                "- 如果需要新增文件，先保持结构最小化，再逐步扩展。",
                "",
                "## 验证方式",
                "- 检查任务描述和验收标准是否都能被观察到。",
                "- 补充最小必要的验证步骤或测试，确保输出可复查。",
            ]
        )
        return "\n".join(lines)


class ExecutionArtifactStore:
    """持久化执行产物与日志。"""

    def __init__(self, harness_dir: Path):
        self.execution_dir = Path(harness_dir) / "executions"
        self.execution_dir.mkdir(parents=True, exist_ok=True)

    def save(self, task: Task, result: ExecutionResult) -> Path:
        """保存单个任务的执行说明。"""
        path = self.execution_dir / f"task-{task.id}.md"
        lines = [
            f"# Task {task.id} Execution",
            "",
            f"- 标题：{task.title}",
            f"- 状态：{'success' if result.success else 'failed'}",
            f"- 开始时间：{result.started_at.isoformat() if result.started_at else 'n/a'}",
            f"- 完成时间：{result.completed_at.isoformat() if result.completed_at else 'n/a'}",
            f"- 耗时（秒）：{result.duration_seconds:.2f}",
            "",
            "## 任务描述",
            task.description or "无",
            "",
            "## 验收标准",
        ]

        if task.acceptance_criteria:
            lines.extend(f"- {criterion}" for criterion in task.acceptance_criteria)
        else:
            lines.append("- 无")

        lines.extend(
            [
                "",
                "## 执行输出",
                result.output or "无",
            ]
        )
        if result.error:
            lines.extend(["", "## 错误", result.error])

        write_text_file(path, "\n".join(lines) + "\n")
        return path


def select_execution_mode(tasks: List[Task]) -> ExecutionMode:
    """根据任务数量选择执行模式

    规则:
    - 1-2 个任务 → Solo (最小开销)
    - 3+ 个任务 → Parallel (Worker 分离)

    Args:
        tasks: 任务列表

    Returns:
        执行模式
    """
    if len(tasks) <= 2:
        return ExecutionMode.SOLO
    else:
        return ExecutionMode.PARALLEL


class ExecutionEngine:
    """执行引擎 - 协调任务执行"""

    def __init__(self, work_dir: str):
        """初始化执行引擎

        Args:
            work_dir: 工作目录
        """
        self.work_dir = work_dir
        self.mode: Optional[ExecutionMode] = None
        self.executed_tasks: List[ExecutionResult] = []

    def set_mode(self, mode: ExecutionMode):
        """设置执行模式

        Args:
            mode: 执行模式
        """
        self.mode = mode

    def prepare_batches(self, tasks: List[Task]) -> List[List[Task]]:
        """准备执行批次

        根据依赖关系将任务分组到批次中。
        无依赖的任务在同一批次，有依赖的任务在后续批次。

        Args:
            tasks: 任务列表

        Returns:
            批次列表
        """
        if not tasks:
            return []

        # 根据模式决定批次策略
        if self.mode == ExecutionMode.SOLO or len(tasks) <= 2:
            # Solo 模式：每个任务独立批次
            return [[task] for task in tasks]

        # Parallel 模式：按依赖关系分组
        batches = []
        remaining = tasks.copy()
        completed_ids = set()

        while remaining:
            # 找出所有依赖已满足的任务
            ready = [
                t for t in remaining
                if all(dep in completed_ids for dep in t.dependencies)
            ]

            if not ready:
                # 剩余的都有未满足的依赖，可能是循环依赖
                # 将它们放入最后的批次
                batches.append(remaining)
                break

            batches.append(ready)
            completed_ids.update(t.id for t in ready)
            remaining = [t for t in remaining if t not in ready]

        return batches


class SoloExecutor:
    """Solo 执行器 - 顺序执行任务"""

    def __init__(self, work_dir: str, llm_provider=None):
        """初始化 Solo 执行器

        Args:
            work_dir: 工作目录
        """
        self.work_dir = work_dir
        self.llm_provider = llm_provider

    def execute(self, task: Task) -> ExecutionResult:
        """执行单个任务

        Args:
            task: 任务

        Returns:
            执行结果
        """
        worker = WorkerAgent(task, llm_provider=self.llm_provider, work_dir=self.work_dir)
        return worker.execute()


class ParallelExecutor:
    """Parallel 执行器 - 并行执行任务"""

    def __init__(self, work_dir: str, llm_provider=None):
        """初始化 Parallel 执行器

        Args:
            work_dir: 工作目录
        """
        self.work_dir = work_dir
        self.llm_provider = llm_provider

    def execute_batch(self, tasks: List[Task]) -> List[ExecutionResult]:
        """并行执行一批任务

        Args:
            tasks: 任务列表

        Returns:
            执行结果列表
        """
        results = []

        # 为每个任务创建 worker
        workers = [WorkerAgent(task, llm_provider=self.llm_provider, work_dir=self.work_dir) for task in tasks]

        # 顺序执行（基础实现，后续可改为异步并行）
        for worker in workers:
            result = worker.execute()
            results.append(result)

        return results


class TaskExecutionService:
    """任务执行服务 - 高层 API"""

    def __init__(self, harness_dir: Path):
        """初始化任务执行服务

        Args:
            harness_dir: .harness 目录路径
        """
        self.harness_dir = harness_dir
        self.work_dir = str(harness_dir.parent)

        # 延迟导入避免循环依赖
        from sfah.store import TaskStore
        from sfah.history import HistoryManager
        from sfah.llm import build_default_provider
        self.store = TaskStore(harness_dir)
        self.history = HistoryManager(harness_dir)
        self.execution_artifacts = ExecutionArtifactStore(harness_dir)
        self.llm_provider = build_default_provider(start_dir=harness_dir.parent)

    def execute_tasks(self, task_ids: Optional[List[int]] = None) -> List[ExecutionResult]:
        """执行任务

        Args:
            task_ids: 任务 ID 列表，None 表示执行所有 TODO 状态的任务

        Returns:
            执行结果列表
        """
        # 如果没有指定任务 ID，获取所有 TODO 状态的任务
        if task_ids is None:
            tasks = self.store.get_tasks_by_status(TaskStatus.TODO)
        else:
            tasks = [self.store.get_task(tid) for tid in task_ids]
            tasks = [t for t in tasks if t is not None]

        if not tasks:
            return []

        # 自动选择执行模式
        mode = select_execution_mode(tasks)

        # 创建执行引擎
        engine = ExecutionEngine(self.work_dir)
        engine.set_mode(mode)

        # 准备批次
        batches = engine.prepare_batches(tasks)

        # 执行任务
        all_results = []

        if mode == ExecutionMode.SOLO:
            executor = SoloExecutor(self.work_dir, llm_provider=self.llm_provider)
            for batch in batches:
                for task in batch:
                    # 更新任务状态为进行中
                    task.start()
                    self.store.update_task(task)

                    # 执行任务
                    result = executor.execute(task)
                    all_results.append(result)
                    artifact_path = self.execution_artifacts.save(task, result)
                    self.history.log_workflow_event("execution_artifact_saved", task_id=task.id, artifact=str(artifact_path))

                    # 根据执行结果更新任务状态
                    if result.success:
                        task.complete()
                        self.store.update_task(task)
                        self.history.log_task_completed(task, int(result.duration_seconds / 60))
        else:
            executor = ParallelExecutor(self.work_dir, llm_provider=self.llm_provider)
            for batch in batches:
                # 更新任务状态为进行中
                for task in batch:
                    task.start()
                    self.store.update_task(task)

                # 执行批次
                results = executor.execute_batch(batch)
                all_results.extend(results)

                # 根据执行结果更新任务状态
                for task, result in zip(batch, results):
                    artifact_path = self.execution_artifacts.save(task, result)
                    self.history.log_workflow_event("execution_artifact_saved", task_id=task.id, artifact=str(artifact_path))
                    if result.success:
                        task.complete()
                    self.store.update_task(task)
                    if result.success:
                        self.history.log_task_completed(task, int(result.duration_seconds / 60))

        return all_results

    def execute_task_solo(self, task_id: int) -> ExecutionResult:
        """以 Solo 模式执行单个任务

        Args:
            task_id: 任务 ID

        Returns:
            执行结果
        """
        task = self.store.get_task(task_id)
        if not task:
            raise ValueError(f"任务 #{task_id} 不存在")

        # 更新任务状态为进行中
        task.start()
        self.store.update_task(task)

        # 执行任务
        executor = SoloExecutor(self.work_dir, llm_provider=self.llm_provider)
        result = executor.execute(task)
        artifact_path = self.execution_artifacts.save(task, result)
        self.history.log_workflow_event("execution_artifact_saved", task_id=task.id, artifact=str(artifact_path))

        # 根据执行结果更新任务状态
        if result.success:
            task.complete()
            self.store.update_task(task)
            self.history.log_task_completed(task, int(result.duration_seconds / 60))

        return result

    def execute_task_parallel(self, task_ids: List[int]) -> List[ExecutionResult]:
        """以 Parallel 模式执行多个任务

        Args:
            task_ids: 任务 ID 列表

        Returns:
            执行结果列表
        """
        tasks = [self.store.get_task(tid) for tid in task_ids]
        tasks = [t for t in tasks if t is not None]

        if not tasks:
            return []

        # 更新任务状态为进行中
        for task in tasks:
            task.start()
            self.store.update_task(task)

        # 执行任务
        executor = ParallelExecutor(self.work_dir, llm_provider=self.llm_provider)
        results = executor.execute_batch(tasks)

        # 根据执行结果更新任务状态
        for task, result in zip(tasks, results):
            artifact_path = self.execution_artifacts.save(task, result)
            self.history.log_workflow_event("execution_artifact_saved", task_id=task.id, artifact=str(artifact_path))
            if result.success:
                task.complete()
                self.store.update_task(task)
                self.history.log_task_completed(task, int(result.duration_seconds / 60))

        return results

