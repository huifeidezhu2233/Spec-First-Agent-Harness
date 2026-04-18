"""Spec-first 工作流与工件管理。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from sfah.io_utils import read_text_file, write_text_file
from sfah.llm import LLMGenerationError, build_default_provider
from sfah.models import Priority, Task
from sfah.planner import PlanGenerator


class WorkflowStage(Enum):
    """工作流阶段。"""

    INIT = "INIT"
    DISCOVERED = "DISCOVERED"
    SPEC_DRAFTED = "SPEC_DRAFTED"
    SPEC_APPROVED = "SPEC_APPROVED"
    PLAN_DRAFTED = "PLAN_DRAFTED"
    PLAN_APPROVED = "PLAN_APPROVED"
    TASKS_READY = "TASKS_READY"

    @classmethod
    def from_string(cls, value: str) -> "WorkflowStage":
        """从字符串恢复阶段。"""
        return cls[value.upper()]


@dataclass
class DiscoveryResult:
    """Discovery 阶段产物。"""

    goal: str
    context: str
    constraints: list[str]
    keywords: list[str]
    features: list[str]
    assumptions: list[str]
    open_questions: list[str]
    success_signals: list[str]
    risks: list[str]

    def to_dict(self) -> dict[str, Any]:
        """序列化结果。"""
        return {
            "goal": self.goal,
            "context": self.context,
            "constraints": self.constraints,
            "keywords": self.keywords,
            "features": self.features,
            "assumptions": self.assumptions,
            "open_questions": self.open_questions,
            "success_signals": self.success_signals,
            "risks": self.risks,
        }


class WorkflowStateStore:
    """管理 spec-first 工作流状态。"""

    def __init__(self, harness_dir: Path):
        self.harness_dir = Path(harness_dir)
        self.state_file = self.harness_dir / "workflow.json"
        self.harness_dir.mkdir(parents=True, exist_ok=True)
        if not self.state_file.exists():
            self.save(self.default_state())

    def default_state(self) -> dict[str, Any]:
        """返回默认工作流状态。"""
        return {
            "goal": "",
            "stage": WorkflowStage.INIT.value,
            "context": "",
            "constraints": [],
            "keywords": [],
            "features": [],
            "assumptions": [],
            "open_questions": [],
            "success_signals": [],
            "risks": [],
            "spec_approved": False,
            "plan_approved": False,
            "artifacts": {},
            "updated_at": datetime.now().isoformat(),
        }

    def load(self) -> dict[str, Any]:
        """读取状态。"""
        with open(self.state_file, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if "stage" not in data:
            data["stage"] = WorkflowStage.INIT.value
        return data

    def save(self, state: dict[str, Any]) -> None:
        """保存状态。"""
        state["updated_at"] = datetime.now().isoformat()
        with open(self.state_file, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, ensure_ascii=False)

    def update(self, **changes: Any) -> dict[str, Any]:
        """更新部分状态。"""
        state = self.load()
        state.update(changes)
        self.save(state)
        return state

    def set_discovery(self, result: DiscoveryResult) -> dict[str, Any]:
        """写入 discovery 阶段信息。"""
        state = self.load()
        state.update(result.to_dict())
        state["stage"] = WorkflowStage.DISCOVERED.value
        self.save(state)
        return state

    def mark_artifact(self, artifact_name: str, path: Path, stage: WorkflowStage) -> dict[str, Any]:
        """记录工件生成。"""
        state = self.load()
        artifacts = state.setdefault("artifacts", {})
        artifacts[artifact_name] = {
            "path": str(path),
            "generated_at": datetime.now().isoformat(),
        }
        state["stage"] = stage.value
        self.save(state)
        return state

    def approve_spec(self) -> dict[str, Any]:
        """批准 spec。"""
        return self.update(spec_approved=True, stage=WorkflowStage.SPEC_APPROVED.value)

    def approve_plan(self) -> dict[str, Any]:
        """批准 plan。"""
        return self.update(plan_approved=True, stage=WorkflowStage.PLAN_APPROVED.value)

    def mark_tasks_ready(self, task_count: int) -> dict[str, Any]:
        """标记任务已生成。"""
        return self.update(stage=WorkflowStage.TASKS_READY.value, task_count=task_count)

    def current_stage(self) -> WorkflowStage:
        """返回当前阶段。"""
        state = self.load()
        return WorkflowStage.from_string(state.get("stage", WorkflowStage.INIT.value))


class ArtifactStore:
    """管理 markdown 工件文件。"""

    ARTIFACT_FILES = {
        "discovery": "discovery.md",
        "spec": "spec.md",
        "plan": "plan.md",
        "tasks": "tasks.md",
    }

    def __init__(self, harness_dir: Path):
        self.harness_dir = Path(harness_dir)
        self.harness_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, artifact_name: str) -> Path:
        """返回工件路径。"""
        return self.harness_dir / self.ARTIFACT_FILES[artifact_name]

    def exists(self, artifact_name: str) -> bool:
        """工件是否存在。"""
        return self.path_for(artifact_name).exists()

    def save(self, artifact_name: str, content: str) -> Path:
        """保存工件。"""
        path = self.path_for(artifact_name)
        write_text_file(path, content)
        return path

    def load(self, artifact_name: str) -> str:
        """读取工件内容。"""
        return read_text_file(self.path_for(artifact_name))


class SpecWorkflowService:
    """生成 discovery/spec/plan/tasks 工件。"""

    FEATURE_LIBRARY = {
        "认证": ["账号建模与凭证校验", "登录/注册流程", "权限与会话控制"],
        "授权": ["权限边界梳理", "角色/权限映射", "敏感操作保护"],
        "API": ["接口契约定义", "参数验证与错误处理", "响应格式统一"],
        "REST": ["接口契约定义", "资源路由设计", "状态码与错误语义"],
        "数据库": ["数据模型设计", "持久化与查询封装", "迁移与初始化"],
        "前端": ["页面与交互骨架", "状态反馈与边界处理", "可访问性与易用性"],
        "React": ["组件拆分", "状态与交互管理", "边界态与可访问性"],
        "自动化": ["任务输入输出定义", "执行流程编排", "结果验证与告警"],
        "测试": ["单元测试覆盖", "集成验证", "回归检查"],
    }

    DEFAULT_FEATURES = [
        "核心流程落地",
        "边界情况与错误处理",
        "验证与交付",
    ]

    def __init__(self, llm_provider=None):
        self.plan_generator = PlanGenerator()
        self.llm_provider = llm_provider or build_default_provider()
        self._generation_sources: dict[str, str] = {}
        self._generation_notes: dict[str, str] = {}

    def provider_status(self) -> dict[str, Any]:
        """返回当前 provider 状态。"""
        if hasattr(self.llm_provider, "status"):
            return self.llm_provider.status()
        return {
            "profile": "custom",
            "provider": "custom",
            "configured": self.llm_provider.is_configured(),
            "summary": self.llm_provider.describe(),
            "api_key": "n/a",
            "api_key_env": "n/a",
            "base_url": "n/a",
            "model": "n/a",
        }

    def generation_source(self, artifact_name: str) -> str:
        """返回指定工件的生成来源。"""
        return self._generation_sources.get(artifact_name, "rule-based")

    def generation_note(self, artifact_name: str) -> str:
        """返回指定工件的补充说明。"""
        return self._generation_notes.get(artifact_name, "")

    def _record_generation(self, artifact_name: str, source: str, note: str = "") -> None:
        """记录工件生成方式。"""
        self._generation_sources[artifact_name] = source
        if note:
            self._generation_notes[artifact_name] = note

    def build_discovery(
        self,
        goal: str,
        context: str = "",
        constraints: Iterable[str] | None = None,
    ) -> DiscoveryResult:
        """基于用户目标生成 discovery 结果。"""
        constraints_list = [item for item in (constraints or []) if item]
        if self.llm_provider.is_configured():
            try:
                result = self._build_discovery_with_llm(goal, context, constraints_list)
                self._record_generation("discovery", "llm")
                return result
            except LLMGenerationError as exc:
                self._record_generation("discovery", "fallback", str(exc))

        result = self._build_discovery_fallback(goal, context, constraints_list)
        if "discovery" not in self._generation_sources:
            self._record_generation("discovery", "rule-based")
        return result

    def _build_discovery_fallback(
        self,
        goal: str,
        context: str,
        constraints_list: list[str],
    ) -> DiscoveryResult:
        """本地规则版 discovery。"""
        parsed = self.plan_generator.parse_user_input(goal)
        normalized_goal = parsed.get("goal", goal).strip()
        keywords = self.plan_generator.extract_keywords(f"{normalized_goal} {context}")
        features = self._infer_features(normalized_goal, context, keywords)
        assumptions = self._build_assumptions(context, constraints_list, features)
        open_questions = self._build_open_questions(constraints_list, keywords)
        success_signals = self._build_success_signals(features)
        risks = self._build_risks(features, constraints_list)

        return DiscoveryResult(
            goal=normalized_goal,
            context=context.strip(),
            constraints=constraints_list,
            keywords=keywords,
            features=features,
            assumptions=assumptions,
            open_questions=open_questions,
            success_signals=success_signals,
            risks=risks,
        )

    def _build_discovery_with_llm(
        self,
        goal: str,
        context: str,
        constraints_list: list[str],
    ) -> DiscoveryResult:
        """通过 LLM 生成结构化 discovery。"""
        system_prompt = (
            "你是一个 spec-first agent harness 的产品分析师。"
            "请用中文输出严格 JSON，不要输出 markdown，不要补充解释。"
        )
        user_prompt = f"""
请根据以下输入生成 discovery 结果，并只返回一个 JSON object。

目标:
{goal}

上下文:
{context or "暂无补充上下文"}

约束:
{json.dumps(constraints_list, ensure_ascii=False)}

JSON schema:
{{
  "goal": "更清晰、可执行的目标描述",
  "context": "补充后的上下文摘要",
  "constraints": ["约束1"],
  "keywords": ["关键词1", "关键词2"],
  "features": ["建议纳入的能力1", "能力2"],
  "assumptions": ["默认假设1"],
  "open_questions": ["待确认问题1"],
  "success_signals": ["成功信号1"],
  "risks": ["风险1"]
}}

要求:
- keywords 输出 3-8 个。
- features 输出 3-6 个，必须与目标直接相关。
- assumptions/open_questions/success_signals 各输出 3-6 条。
- risks 输出 2-5 条。
- 如果输入不足，请通过假设和待确认问题体现，而不是胡乱扩展范围。
""".strip()
        payload = self.llm_provider.generate_json(system_prompt, user_prompt)
        return self._normalize_discovery_payload(goal, context, constraints_list, payload)

    def render_discovery_markdown(self, result: DiscoveryResult) -> str:
        """渲染 discovery 工件。"""
        lines = [
            "# Discovery",
            "",
            "## 目标",
            result.goal,
            "",
            "## 已知上下文",
            result.context or "暂无补充上下文。",
            "",
            "## 建议纳入的能力范围",
        ]
        lines.extend(f"- {feature}" for feature in result.features)
        lines.extend(["", "## 默认假设"])
        lines.extend(f"- {item}" for item in result.assumptions)
        lines.extend(["", "## 待确认问题"])
        lines.extend(f"- {item}" for item in result.open_questions)
        lines.extend(["", "## 成功信号"])
        lines.extend(f"- {item}" for item in result.success_signals)
        lines.extend(["", "## 风险"])
        lines.extend(f"- {item}" for item in result.risks)

        if result.constraints:
            lines.extend(["", "## 约束", *[f"- {item}" for item in result.constraints]])

        return "\n".join(lines) + "\n"

    def render_spec_markdown(self, result: DiscoveryResult) -> str:
        """渲染 spec 工件。"""
        if self.llm_provider.is_configured():
            try:
                content = self._render_spec_markdown_with_llm(result)
                self._record_generation("spec", "llm")
                return content
            except LLMGenerationError as exc:
                self._record_generation("spec", "fallback", str(exc))

        content = self._render_spec_markdown_fallback(result)
        if "spec" not in self._generation_sources:
            self._record_generation("spec", "rule-based")
        return content

    def _render_spec_markdown_fallback(self, result: DiscoveryResult) -> str:
        """本地规则版 spec。"""
        lines = [
            "# 规格说明",
            "",
            "## 背景",
            f"当前目标是：{result.goal}",
            "",
            "## 目标",
            f"- 交付一个围绕\"{result.goal}\"的可执行方案。",
            "- 保持范围聚焦，优先完成核心路径。",
            "- 为后续 plan 与 tasks 提供稳定输入。",
            "",
            "## 范围内",
        ]
        lines.extend(f"- {feature}" for feature in result.features)
        lines.extend(
            [
                "",
                "## 范围外",
                "- 未经确认的扩展功能",
                "- 与当前目标无直接关系的性能极限优化",
                "- 需要额外基础设施支持但尚未确认的能力",
                "",
                "## 功能需求",
            ]
        )

        for index, feature in enumerate(result.features, start=1):
            lines.extend(
                [
                    f"### FR-{index}: {feature}",
                    f"- 系统应支持与\"{feature}\"相关的最小闭环。",
                    f"- 交付结果应能被验证，并与总体目标\"{result.goal}\"保持一致。",
                    f"- 需要覆盖与\"{feature}\"直接相关的错误处理或边界条件。",
                    "",
                ]
            )

        lines.extend(["## 验收标准"])
        lines.extend(f"- {item}" for item in result.success_signals)
        lines.extend(["", "## 假设"])
        lines.extend(f"- {item}" for item in result.assumptions)
        lines.extend(["", "## 待确认问题"])
        lines.extend(f"- {item}" for item in result.open_questions)
        lines.extend(["", "## 风险"])
        lines.extend(f"- {item}" for item in result.risks)

        if result.constraints:
            lines.extend(["", "## 约束", *[f"- {item}" for item in result.constraints]])

        return "\n".join(lines) + "\n"

    def _render_spec_markdown_with_llm(self, result: DiscoveryResult) -> str:
        """通过 LLM 渲染 spec。"""
        system_prompt = (
            "你是一个资深工程规划助手。"
            "请根据 discovery 结果输出中文 markdown 规格说明，只返回 markdown。"
        )
        user_prompt = f"""
请基于下面的 discovery 数据生成 spec。

Discovery:
{json.dumps(result.to_dict(), ensure_ascii=False, indent=2)}

要求:
- 标题使用 `# 规格说明`
- 必须包含：`## 背景`、`## 目标`、`## 范围内`、`## 范围外`、`## 功能需求`、`## 验收标准`、`## 假设`、`## 待确认问题`、`## 风险`
- 功能需求使用 `### FR-1` 这种编号
- 输出尽量具体，避免空话
- 如果有约束，追加 `## 约束`
- 不要输出代码块围栏
""".strip()
        return self.llm_provider.generate_markdown(system_prompt, user_prompt)

    def render_plan_markdown(self, workflow_state: dict[str, Any]) -> str:
        """根据当前工作流状态渲染执行计划。"""
        if self.llm_provider.is_configured():
            try:
                content = self._render_plan_markdown_with_llm(workflow_state)
                self._record_generation("plan", "llm")
                return content
            except LLMGenerationError as exc:
                self._record_generation("plan", "fallback", str(exc))

        content = self._render_plan_markdown_fallback(workflow_state)
        if "plan" not in self._generation_sources:
            self._record_generation("plan", "rule-based")
        return content

    def _render_plan_markdown_fallback(self, workflow_state: dict[str, Any]) -> str:
        """本地规则版 plan。"""
        goal = workflow_state.get("goal", "").strip() or "未命名目标"
        features = workflow_state.get("features", []) or self.DEFAULT_FEATURES
        risks = workflow_state.get("risks", [])

        lines = [
            "# 执行计划",
            "",
            "## 目标对齐",
            f"- 主目标: {goal}",
            "- 先固定范围与契约，再进入实现和验证。",
            "- 每个阶段都要有可审阅的产物，避免直接跳到最终实现。",
            "",
            "## 实施策略",
            "- 先建立骨架与关键边界，再逐项完成核心能力。",
            "- 将高风险项提前暴露，避免在后期集中返工。",
            "- 用 review 作为阶段性质量门，而不是收尾动作。",
            "",
            "## 阶段划分",
            "### Milestone 1: 范围与契约固定",
            "- 对齐输入输出、边界条件与验收口径。",
            "- 确认哪些能力必须先落地，哪些可以延后。",
            "",
        ]

        for index, feature in enumerate(features, start=2):
            lines.extend(
                [
                    f"### Milestone {index}: {feature}",
                    f"- 实现与\"{feature}\"直接相关的最小能力闭环。",
                    "- 补齐该阶段需要的边界处理、数据流与错误反馈。",
                    "",
                ]
            )

        lines.extend(
            [
                f"### Milestone {len(features) + 2}: 验证与收尾",
                "- 对核心流程进行验证并补齐必要测试。",
                "- 同步文档/示例/操作说明，确保可交付。",
                "",
                "## 验证策略",
                "- 关键路径至少有一条从输入到输出的完整验证路径。",
                "- 对高风险区域优先做 review 或回归检查。",
                "- 计划完成后需确认任务拆分能独立执行且依赖关系清晰。",
            ]
        )

        if risks:
            lines.extend(["", "## 风险与缓解"])
            lines.extend(f"- {risk}" for risk in risks)

        return "\n".join(lines) + "\n"

    def _render_plan_markdown_with_llm(self, workflow_state: dict[str, Any]) -> str:
        """通过 LLM 渲染 plan。"""
        system_prompt = (
            "你是一个 spec-first harness 的实施规划助手。"
            "请输出中文 markdown 执行计划，只返回 markdown。"
        )
        user_prompt = f"""
请基于下面的 workflow state 生成执行计划。

Workflow state:
{json.dumps(self._compact_workflow_state(workflow_state), ensure_ascii=False, indent=2)}

要求:
- 标题使用 `# 执行计划`
- 必须包含：`## 目标对齐`、`## 实施策略`、`## 阶段划分`、`## 验证策略`
- 阶段划分至少包含 3 个 Milestone，突出先收敛范围、再实现、最后验证
- 如果存在风险，追加 `## 风险与缓解`
- 内容要能直接支撑后续 tasks 拆分
- 不要输出代码块围栏
""".strip()
        return self.llm_provider.generate_markdown(system_prompt, user_prompt)

    def build_tasks(self, workflow_state: dict[str, Any], start_id: int = 1) -> list[Task]:
        """根据工作流状态生成任务列表。"""
        if self.llm_provider.is_configured():
            try:
                tasks = self._build_tasks_with_llm(workflow_state, start_id)
                self._record_generation("tasks", "llm")
                return tasks
            except LLMGenerationError as exc:
                self._record_generation("tasks", "fallback", str(exc))

        tasks = self._build_tasks_fallback(workflow_state, start_id)
        if "tasks" not in self._generation_sources:
            self._record_generation("tasks", "rule-based")
        return tasks

    def _build_tasks_fallback(self, workflow_state: dict[str, Any], start_id: int = 1) -> list[Task]:
        """本地规则版任务拆分。"""
        goal = workflow_state.get("goal", "").strip() or "未命名目标"
        features = workflow_state.get("features", []) or self.DEFAULT_FEATURES
        tasks: list[Task] = []

        foundation_task = Task(
            id=start_id,
            title="固定范围与实现边界",
            description=f"根据 spec 与 plan 固定 {goal} 的输入输出、边界与验收口径。",
            priority=Priority.REQUIRED,
            acceptance_criteria=[
                "关键输入输出已明确",
                "边界条件已记录",
                "后续任务可基于统一口径展开",
            ],
            estimated_effort=2,
        )
        tasks.append(foundation_task)

        current_id = start_id + 1
        feature_task_ids: list[int] = []
        for feature in features:
            feature_task = Task(
                id=current_id,
                title=f"实现{feature}",
                description=f"围绕目标\"{goal}\"实现 {feature} 的最小闭环。",
                priority=Priority.REQUIRED,
                acceptance_criteria=self.plan_generator.generate_acceptance_criteria(
                    f"实现{feature}",
                    f"{goal} {feature}",
                ),
                estimated_effort=self.plan_generator.estimate_effort(f"{goal} {feature}"),
                dependencies=[foundation_task.id],
            )
            tasks.append(feature_task)
            feature_task_ids.append(current_id)
            current_id += 1

        validation_task = Task(
            id=current_id,
            title="补齐验证与回归检查",
            description="覆盖关键路径、错误路径，并确保主要能力可被验收。",
            priority=Priority.RECOMMENDED,
            acceptance_criteria=[
                "关键路径具备验证手段",
                "高风险点有回归检查",
                "review 阶段可基于验证结果继续推进",
            ],
            estimated_effort=2,
            dependencies=feature_task_ids or [foundation_task.id],
        )
        tasks.append(validation_task)
        current_id += 1

        documentation_task = Task(
            id=current_id,
            title="整理交付说明与后续事项",
            description="同步使用方式、剩余风险与可选增强项，形成可交付闭环。",
            priority=Priority.OPTIONAL,
            acceptance_criteria=[
                "核心使用方式已记录",
                "剩余风险已说明",
                "后续增强方向清晰",
            ],
            estimated_effort=1,
            dependencies=[validation_task.id],
        )
        tasks.append(documentation_task)

        return tasks

    def _build_tasks_with_llm(self, workflow_state: dict[str, Any], start_id: int = 1) -> list[Task]:
        """通过 LLM 生成结构化任务。"""
        system_prompt = (
            "你是一个工程任务拆解助手。"
            "请输出严格 JSON，不要输出 markdown，不要补充解释。"
        )
        user_prompt = f"""
请基于下面的 workflow state 生成任务列表，只返回一个 JSON object。

Workflow state:
{json.dumps(self._compact_workflow_state(workflow_state), ensure_ascii=False, indent=2)}

JSON schema:
{{
  "tasks": [
    {{
      "id": {start_id},
      "title": "任务标题",
      "description": "任务描述",
      "priority": "REQUIRED",
      "acceptance_criteria": ["验收标准1", "验收标准2"],
      "estimated_effort": 2,
      "dependencies": []
    }}
  ]
}}

要求:
- 生成 4-8 个任务。
- id 从 {start_id} 开始递增且连续。
- dependencies 只能依赖更小的 id。
- priority 只能是 REQUIRED、RECOMMENDED、OPTIONAL。
- 至少包含一个范围收敛任务、一个验证任务、一个交付说明任务。
- estimated_effort 范围是 1-5。
- 验收标准每个任务 2-4 条。
""".strip()
        payload = self.llm_provider.generate_json(system_prompt, user_prompt)
        tasks = self._normalize_tasks_payload(payload, workflow_state, start_id)
        if not tasks:
            raise LLMGenerationError("LLM 返回的任务列表为空。")
        return tasks

    def render_tasks_markdown(self, tasks: list[Task]) -> str:
        """渲染 tasks 工件。"""
        lines = ["# 任务分解", "", "## Tasks", ""]
        groups = [
            ("### Required（必需）", [task for task in tasks if task.priority == Priority.REQUIRED]),
            ("### Recommended（推荐）", [task for task in tasks if task.priority == Priority.RECOMMENDED]),
            ("### Optional（可选）", [task for task in tasks if task.priority == Priority.OPTIONAL]),
        ]

        for title, grouped_tasks in groups:
            if not grouped_tasks:
                continue
            lines.extend([title, ""])
            for task in grouped_tasks:
                lines.append(f"- [ ] **Task {task.id}**: {task.title}")
                if task.description:
                    lines.append(f"  {task.description}")
                for criterion in task.acceptance_criteria:
                    lines.append(f"  - AC: {criterion}")
                lines.append(f"  - Estimate: {task.estimated_effort}")
                if task.dependencies:
                    lines.append(f"  - Depends on: {task.dependencies}")
                lines.append("")

        return "\n".join(lines) + "\n"

    def _normalize_discovery_payload(
        self,
        goal: str,
        context: str,
        constraints_list: list[str],
        payload: dict[str, Any],
    ) -> DiscoveryResult:
        """将 LLM 输出规范化为 DiscoveryResult。"""
        normalized_goal = str(payload.get("goal") or goal).strip()
        normalized_context = str(payload.get("context") or context).strip()
        keywords = self._normalize_string_list(payload.get("keywords")) or self.plan_generator.extract_keywords(
            f"{normalized_goal} {normalized_context}"
        )
        features = self._normalize_string_list(payload.get("features")) or self._infer_features(
            normalized_goal,
            normalized_context,
            keywords,
        )
        assumptions = self._normalize_string_list(payload.get("assumptions")) or self._build_assumptions(
            normalized_context,
            constraints_list,
            features,
        )
        open_questions = self._normalize_string_list(payload.get("open_questions")) or self._build_open_questions(
            constraints_list,
            keywords,
        )
        success_signals = self._normalize_string_list(payload.get("success_signals")) or self._build_success_signals(
            features
        )
        risks = self._normalize_string_list(payload.get("risks")) or self._build_risks(features, constraints_list)
        normalized_constraints = self._normalize_string_list(payload.get("constraints")) or constraints_list

        return DiscoveryResult(
            goal=normalized_goal,
            context=normalized_context,
            constraints=normalized_constraints,
            keywords=keywords[:8],
            features=features[:6],
            assumptions=assumptions[:6],
            open_questions=open_questions[:6],
            success_signals=success_signals[:6],
            risks=risks[:5],
        )

    def _normalize_tasks_payload(
        self,
        payload: dict[str, Any],
        workflow_state: dict[str, Any],
        start_id: int,
    ) -> list[Task]:
        """将 LLM 输出规范化为 Task 列表。"""
        payload_tasks = payload if isinstance(payload, list) else payload.get("tasks", [])
        if not isinstance(payload_tasks, list):
            raise LLMGenerationError("任务结果格式不正确。")

        tasks: list[Task] = []
        current_id = start_id
        goal = workflow_state.get("goal", "").strip() or "未命名目标"

        for raw_task in payload_tasks:
            if not isinstance(raw_task, dict):
                continue

            task_id = raw_task.get("id", current_id)
            if not isinstance(task_id, int) or task_id < start_id or any(task.id == task_id for task in tasks):
                task_id = current_id

            title = str(raw_task.get("title", "")).strip()
            if not title:
                continue

            priority_value = str(raw_task.get("priority", "REQUIRED")).upper()
            if priority_value not in {"REQUIRED", "RECOMMENDED", "OPTIONAL"}:
                priority_value = "REQUIRED"

            criteria = self._normalize_string_list(raw_task.get("acceptance_criteria"))
            if not criteria:
                criteria = self.plan_generator.generate_acceptance_criteria(title, f"{goal} {title}")[:3]

            estimate_value = raw_task.get("estimated_effort", 1)
            if not isinstance(estimate_value, int):
                try:
                    estimate_value = int(estimate_value)
                except (TypeError, ValueError):
                    estimate_value = 1
            estimate_value = min(5, max(1, estimate_value))

            dependencies = [
                dependency
                for dependency in self._normalize_int_list(raw_task.get("dependencies"))
                if dependency < task_id
            ]

            tasks.append(
                Task(
                    id=task_id,
                    title=title,
                    description=str(raw_task.get("description", "")).strip(),
                    priority=Priority.from_string(priority_value),
                    acceptance_criteria=criteria[:4],
                    estimated_effort=estimate_value,
                    dependencies=dependencies,
                )
            )
            current_id = max(current_id + 1, task_id + 1)

        return tasks

    def _compact_workflow_state(self, workflow_state: dict[str, Any]) -> dict[str, Any]:
        """压缩成更适合给 LLM 的 state。"""
        return {
            "goal": workflow_state.get("goal", ""),
            "context": workflow_state.get("context", ""),
            "constraints": workflow_state.get("constraints", []),
            "features": workflow_state.get("features", []),
            "assumptions": workflow_state.get("assumptions", []),
            "open_questions": workflow_state.get("open_questions", []),
            "success_signals": workflow_state.get("success_signals", []),
            "risks": workflow_state.get("risks", []),
        }

    def _normalize_string_list(self, value: Any) -> list[str]:
        """将任意值规范化为字符串列表。"""
        if isinstance(value, list):
            items = value
        elif isinstance(value, str):
            items = [part.strip(" -") for part in value.replace("；", "\n").replace(";", "\n").splitlines()]
        else:
            items = []

        normalized: list[str] = []
        for item in items:
            text = str(item).strip()
            if text and text not in normalized:
                normalized.append(text)
        return normalized

    def _normalize_int_list(self, value: Any) -> list[int]:
        """将任意值规范化为整数列表。"""
        if not isinstance(value, list):
            return []
        normalized: list[int] = []
        for item in value:
            try:
                parsed = int(item)
            except (TypeError, ValueError):
                continue
            if parsed not in normalized:
                normalized.append(parsed)
        return normalized

    def _infer_features(self, goal: str, context: str, keywords: list[str]) -> list[str]:
        """推断建议特性列表。"""
        features: list[str] = []

        for keyword in keywords:
            features.extend(self.FEATURE_LIBRARY.get(keyword, []))

        combined_text = f"{goal} {context}"
        if any(token in combined_text for token in ["登录", "注册", "认证"]):
            features.extend(self.FEATURE_LIBRARY["认证"])
        if any(token in combined_text for token in ["接口", "API", "REST"]):
            features.extend(self.FEATURE_LIBRARY["API"])
        if any(token in combined_text for token in ["页面", "前端", "组件", "UI"]):
            features.extend(self.FEATURE_LIBRARY["前端"])
        if "数据库" in combined_text:
            features.extend(self.FEATURE_LIBRARY["数据库"])
        if any(token in combined_text for token in ["测试", "验证", "review"]):
            features.extend(self.FEATURE_LIBRARY["测试"])

        if not features:
            features.extend(self.DEFAULT_FEATURES)

        unique: list[str] = []
        for item in features:
            if item not in unique:
                unique.append(item)
        return unique[:5]

    def _build_assumptions(
        self,
        context: str,
        constraints: list[str],
        features: list[str],
    ) -> list[str]:
        """生成默认假设。"""
        assumptions = [
            "默认先实现最小可行闭环，再决定是否扩展额外能力。",
            "默认沿用当前仓库已有的技术栈和组织方式，而不是引入大型新基础设施。",
        ]
        if not context:
            assumptions.append("当前未提供更细的业务背景，因此 spec 会优先强调边界与确认点。")
        if constraints:
            assumptions.append("给定约束会被视为优先级更高的决策输入。")
        if features:
            assumptions.append(f"初版将优先覆盖 {features[0]} 等核心能力。")
        return assumptions

    def _build_open_questions(
        self,
        constraints: list[str],
        keywords: list[str],
    ) -> list[str]:
        """生成待确认问题。"""
        questions = [
            "最重要的成功标准是什么，如何判断这次交付已经可接受？",
            "是否存在必须兼容的外部接口、历史数据或既有流程？",
            "哪些内容明确不在本次范围内，避免任务膨胀？",
        ]
        if not keywords:
            questions.append("目标更偏工具、内容还是自动化流程，需要进一步明确场景。")
        if not constraints:
            questions.append("是否有技术栈、时限、成本或依赖方面的硬性限制？")
        return questions

    def _build_success_signals(self, features: list[str]) -> list[str]:
        """生成成功信号。"""
        signals = [f"关键能力\"{feature}\"具备可演示或可验证的闭环。" for feature in features[:3]]
        signals.append("交付结果可以被 review，并能明确指出下一步行动。")
        return signals

    def _build_risks(self, features: list[str], constraints: list[str]) -> list[str]:
        """生成风险提示。"""
        risks = [
            "如果 spec 未收敛就直接拆任务，后续很容易返工。",
            "如果没有明确验收口径，执行阶段可能只完成了表面功能。",
        ]
        if len(features) >= 4:
            risks.append("当前覆盖面较广，建议优先锁定必须项，避免阶段一就范围失控。")
        if constraints:
            risks.append("存在显式约束时，任务拆分需要始终对齐这些边界。")
        return risks

