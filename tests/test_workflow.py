"""测试 spec-first 工作流。"""

from sfah.llm import LLMConfig, LLMGenerationError
from sfah.models import Task
from sfah.workflow import SpecWorkflowService, WorkflowStage, WorkflowStateStore


class FakeWorkflowProvider:
    """用于 workflow 测试的 provider stub。"""

    def __init__(self):
        self.config = LLMConfig(api_key="sk-test", base_url="https://example.com/v1", model="gpt-5.4")

    def is_configured(self) -> bool:
        return True

    def describe(self) -> str:
        return self.config.describe()

    def generate_json(self, system_prompt: str, user_prompt: str):
        if "discovery" in user_prompt.lower():
            return {
                "goal": "实现用户登录 API",
                "context": "已有 Flask 服务，需要补登录接口。",
                "constraints": ["保持当前技术栈"],
                "keywords": ["登录", "API", "认证"],
                "features": ["登录接口", "凭证校验", "错误处理"],
                "assumptions": ["默认沿用现有 Flask 项目结构"],
                "open_questions": ["是否需要 JWT"],
                "success_signals": ["可以完成一次登录闭环"],
                "risks": ["未确认会话方案前容易返工"],
            }
        return {
            "tasks": [
                {
                    "id": 1,
                    "title": "固定登录接口契约",
                    "description": "确认输入输出和错误码。",
                    "priority": "REQUIRED",
                    "acceptance_criteria": ["请求参数明确", "错误码明确"],
                    "estimated_effort": 2,
                    "dependencies": [],
                },
                {
                    "id": 2,
                    "title": "实现登录处理逻辑",
                    "description": "完成凭证校验与响应。",
                    "priority": "REQUIRED",
                    "acceptance_criteria": ["登录成功路径可用", "失败路径可验证"],
                    "estimated_effort": 3,
                    "dependencies": [1],
                },
            ]
        }

    def generate_markdown(self, system_prompt: str, user_prompt: str) -> str:
        if "执行计划" in user_prompt:
            return "# 执行计划\n\n## 目标对齐\n- 对齐登录目标\n\n## 实施策略\n- 先定契约\n\n## 阶段划分\n### Milestone 1\n- 固定范围\n\n## 验证策略\n- 验证登录闭环\n"
        return "# 规格说明\n\n## 背景\n当前目标是实现登录。\n\n## 目标\n- 交付登录能力。\n\n## 范围内\n- 登录接口\n\n## 范围外\n- 社交登录\n\n## 功能需求\n### FR-1: 登录接口\n- 支持账号密码登录。\n\n## 验收标准\n- 可以登录。\n\n## 假设\n- 沿用现有服务。\n\n## 待确认问题\n- 是否需要 JWT。\n\n## 风险\n- 会话方案未定。\n"


class FailingPlanProvider(FakeWorkflowProvider):
    """让 plan 生成失败，验证回退逻辑。"""

    def generate_markdown(self, system_prompt: str, user_prompt: str) -> str:
        if "执行计划" in user_prompt:
            raise LLMGenerationError("provider unavailable")
        return super().generate_markdown(system_prompt, user_prompt)


class TestSpecWorkflowService:
    """测试工作流工件生成。"""

    def test_build_discovery_has_goal_and_features(self):
        """应生成带目标和特性的 discovery。"""
        service = SpecWorkflowService()
        result = service.build_discovery("实现用户登录 API")

        assert result.goal
        assert result.features
        assert any("登录" in feature or "接口" in feature or "认证" in feature for feature in result.features)

    def test_build_discovery_uses_llm_when_available(self):
        """配置 provider 时应优先使用 LLM 结果。"""
        service = SpecWorkflowService(llm_provider=FakeWorkflowProvider())
        result = service.build_discovery("实现用户登录 API")

        assert result.context == "已有 Flask 服务，需要补登录接口。"
        assert result.features[0] == "登录接口"
        assert service.generation_source("discovery") == "llm"

    def test_render_spec_markdown_contains_sections(self):
        """spec 工件应包含关键章节。"""
        service = SpecWorkflowService()
        discovery = service.build_discovery("实现用户登录 API")
        content = service.render_spec_markdown(discovery)

        assert "## 目标" in content
        assert "## 功能需求" in content
        assert "## 验收标准" in content

    def test_build_tasks_generates_dependency_chain(self):
        """任务拆分应具备基础依赖关系。"""
        service = SpecWorkflowService()
        state = {
            "goal": "实现用户登录 API",
            "features": ["接口契约定义", "登录/注册流程", "验证与交付"],
        }

        tasks = service.build_tasks(state)

        assert len(tasks) >= 4
        assert isinstance(tasks[0], Task)
        assert tasks[1].dependencies == [tasks[0].id]

    def test_build_tasks_uses_llm_payload(self):
        """配置 provider 时 tasks 应能使用 LLM 输出。"""
        service = SpecWorkflowService(llm_provider=FakeWorkflowProvider())
        tasks = service.build_tasks({"goal": "实现用户登录 API", "features": ["登录接口"]})

        assert len(tasks) == 2
        assert tasks[1].dependencies == [1]
        assert service.generation_source("tasks") == "llm"

    def test_render_plan_falls_back_when_llm_fails(self):
        """当 LLM 失败时应回退到本地规则。"""
        service = SpecWorkflowService(llm_provider=FailingPlanProvider())
        content = service.render_plan_markdown({"goal": "实现用户登录 API", "features": ["登录接口"]})

        assert "## 阶段划分" in content
        assert service.generation_source("plan") == "fallback"
        assert "provider unavailable" in service.generation_note("plan")


class TestWorkflowStateStore:
    """测试工作流状态存储。"""

    def test_default_stage_is_init(self, tmp_path):
        """默认阶段应为 INIT。"""
        store = WorkflowStateStore(tmp_path / ".harness")
        assert store.current_stage() == WorkflowStage.INIT

    def test_mark_spec_approval(self, tmp_path):
        """应能标记 spec 批准。"""
        store = WorkflowStateStore(tmp_path / ".harness")
        store.approve_spec()

        state = store.load()
        assert state["spec_approved"] is True
        assert state["stage"] == WorkflowStage.SPEC_APPROVED.value

