"""Provider implementations for structured LLM generation."""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

import httpx

from .models import LLMConfig, ProviderType


class LLMGenerationError(RuntimeError):
    """Raised when the provider cannot return a usable completion."""


class LLMProvider(Protocol):
    """Duck-typed provider interface used by the workflow service."""

    config: LLMConfig

    def is_configured(self) -> bool: ...
    def describe(self) -> str: ...
    def status(self) -> dict[str, Any]: ...
    def generate_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]: ...
    def generate_markdown(self, system_prompt: str, user_prompt: str) -> str: ...
    def generate_text(self, system_prompt: str, user_prompt: str) -> str: ...


class BaseProvider:
    """Common status helpers shared by all providers."""

    def __init__(self, config: LLMConfig):
        self.config = config

    def is_configured(self) -> bool:
        """Whether this provider can perform a remote call."""
        return self.config.is_configured

    def describe(self) -> str:
        """Human-readable summary."""
        return self.config.describe()

    def status(self) -> dict[str, Any]:
        """Return normalized CLI status fields."""
        return self.config.to_status()

    def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        """Generate plain text."""
        return self.generate_markdown(system_prompt, user_prompt).strip()

    def _extract_json_object(self, content: str) -> str:
        """Extract the first JSON object from a mixed response."""
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or start >= end:
            raise LLMGenerationError("无法从响应中解析 JSON。")
        return content[start : end + 1]

    def _strip_code_fences(self, content: str) -> str:
        """Remove triple-backtick fences if present."""
        if content.startswith("```"):
            lines = content.splitlines()
            if len(lines) >= 3 and lines[-1].strip() == "```":
                return "\n".join(lines[1:-1]).strip()
        return content


class OpenAICompatibleProvider(BaseProvider):
    """OpenAI-compatible `/chat/completions` provider."""

    def generate_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """Generate JSON from a chat completion."""
        content = self._complete(system_prompt, user_prompt, expect_json=True)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return json.loads(self._extract_json_object(content))

    def generate_markdown(self, system_prompt: str, user_prompt: str) -> str:
        """Generate markdown content."""
        return self._complete(system_prompt, user_prompt, expect_json=False).strip() + "\n"

    def _complete(self, system_prompt: str, user_prompt: str, expect_json: bool) -> str:
        """Call the chat completions endpoint."""
        if not self.is_configured():
            raise LLMGenerationError(f"{self.config.api_key_env or 'API key'} 未配置。")

        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.config.temperature,
        }
        if expect_json:
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
            **self.config.extra_headers,
        }

        try:
            response = httpx.post(
                f"{self.config.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=self.config.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise LLMGenerationError(
                f"LLM 请求失败: HTTP {exc.response.status_code} - {exc.response.text}"
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMGenerationError(f"LLM 请求失败: {exc}") from exc

        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise LLMGenerationError("LLM 响应缺少 choices。")

        message = choices[0].get("message", {})
        content = self._coerce_message_content(message.get("content"))
        if not content:
            raise LLMGenerationError("LLM 响应内容为空。")
        return self._strip_code_fences(content.strip())

    def _coerce_message_content(self, content: Any) -> str:
        """Handle both string and list-based message formats."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("text"):
                    parts.append(str(item["text"]))
                elif isinstance(item, str):
                    parts.append(item)
            return "\n".join(parts)
        return ""


class AnthropicProvider(BaseProvider):
    """Anthropic `/v1/messages` provider."""

    def generate_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """Generate JSON using the Anthropic API."""
        content = self._complete(system_prompt, user_prompt).strip()
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return json.loads(self._extract_json_object(content))

    def generate_markdown(self, system_prompt: str, user_prompt: str) -> str:
        """Generate markdown content."""
        return self._complete(system_prompt, user_prompt).strip() + "\n"

    def _complete(self, system_prompt: str, user_prompt: str) -> str:
        """Call the Anthropic messages endpoint."""
        if not self.is_configured():
            raise LLMGenerationError(f"{self.config.api_key_env or 'API key'} 未配置。")

        base_url = self.config.base_url.rstrip("/")
        if base_url.endswith("/v1"):
            endpoint = f"{base_url}/messages"
        elif base_url.endswith("/messages"):
            endpoint = base_url
        else:
            endpoint = f"{base_url}/v1/messages"

        payload = {
            "model": self.config.model,
            "system": system_prompt,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "messages": [{"role": "user", "content": user_prompt}],
        }

        headers = {
            "x-api-key": self.config.api_key,
            "anthropic-version": self.config.anthropic_version,
            "content-type": "application/json",
            **self.config.extra_headers,
        }

        try:
            response = httpx.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=self.config.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise LLMGenerationError(
                f"Anthropic 请求失败: HTTP {exc.response.status_code} - {exc.response.text}"
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMGenerationError(f"Anthropic 请求失败: {exc}") from exc

        data = response.json()
        content_blocks = data.get("content") or []
        texts: list[str] = []
        for block in content_blocks:
            if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                texts.append(str(block["text"]))
        if not texts:
            raise LLMGenerationError("Anthropic 响应内容为空。")
        return self._strip_code_fences("\n".join(texts).strip())


class MockProvider(BaseProvider):
    """Local provider for demos, tests, and offline development."""

    def generate_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """Return deterministic structured content for known workflow prompts."""
        if "tasks" in user_prompt.lower() and '"tasks"' in user_prompt:
            goal = self._extract_field(user_prompt, r'"goal":\s*"([^"]+)"') or "未命名目标"
            start_id_match = re.search(r'"id":\s*(\d+)', user_prompt)
            start_id = int(start_id_match.group(1)) if start_id_match else 1
            return {
                "tasks": [
                    {
                        "id": start_id,
                        "title": "收敛范围与接口契约",
                        "description": f"围绕“{goal}”明确关键边界、输入输出和验收口径。",
                        "priority": "REQUIRED",
                        "acceptance_criteria": ["范围明确", "接口契约明确", "验收口径明确"],
                        "estimated_effort": 2,
                        "dependencies": [],
                    },
                    {
                        "id": start_id + 1,
                        "title": "实现核心能力闭环",
                        "description": f"实现“{goal}”最核心的一条业务闭环。",
                        "priority": "REQUIRED",
                        "acceptance_criteria": ["核心路径可运行", "异常路径可处理", "输出结果可验证"],
                        "estimated_effort": 3,
                        "dependencies": [start_id],
                    },
                ]
            }

        goal = self._extract_field(user_prompt, r"目标:\s*(.+)") or "未命名目标"
        return {
            "goal": goal.strip(),
            "context": "Mock provider generated this discovery result.",
            "constraints": [],
            "keywords": ["spec-first", "workflow", "agent harness"],
            "features": ["需求收敛", "计划生成", "任务拆解"],
            "assumptions": ["优先交付最小闭环", "沿用现有工作区与技术栈"],
            "open_questions": ["是否有必须对齐的技术边界？", "是否需要指定交付形式？"],
            "success_signals": ["生成可审阅工件", "任务拆解可执行", "流程状态可追踪"],
            "risks": ["需求不收敛会导致返工", "执行边界不明确会影响产出稳定性"],
        }

    def generate_markdown(self, system_prompt: str, user_prompt: str) -> str:
        """Return a deterministic markdown artifact."""
        if "执行计划" in user_prompt:
            return (
                "# 执行计划\n\n"
                "## 目标对齐\n- 聚焦最小闭环。\n\n"
                "## 实施策略\n- 先固定工件，再推进实现。\n\n"
                "## 阶段划分\n"
                "### Milestone 1: 收敛范围\n- 明确目标、边界和验收标准。\n\n"
                "### Milestone 2: 核心实现\n- 优先完成最关键的一条路径。\n\n"
                "### Milestone 3: 验证与交付\n- 检查关键路径与文档一致性。\n\n"
                "## 验证策略\n- 对工件和任务图进行一致性检查。\n"
            )

        return (
            "# 规格说明\n\n"
            "## 背景\n当前目标需要先收敛成可执行工件。\n\n"
            "## 目标\n- 交付可审阅的 spec。\n\n"
            "## 范围内\n- 需求收敛\n- 工件生成\n\n"
            "## 范围外\n- 非核心扩展\n\n"
            "## 功能需求\n### FR-1: 工件生成\n- 能够生成稳定的规格说明。\n\n"
            "## 验收标准\n- 规格可用于下一阶段。\n\n"
            "## 假设\n- 采用最小闭环策略。\n\n"
            "## 待确认问题\n- 是否有外部依赖边界？\n\n"
            "## 风险\n- 需求漂移会导致返工。\n"
        )

    def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        """Return a simple deterministic text snippet."""
        return f"Mock provider active for profile `{self.config.profile}`."

    def _extract_field(self, text: str, pattern: str) -> str:
        """Extract a single regex field from a prompt."""
        match = re.search(pattern, text)
        return match.group(1).strip() if match else ""


def build_provider(config: LLMConfig) -> LLMProvider:
    """Build a provider implementation for the given runtime config."""
    if config.provider == ProviderType.ANTHROPIC:
        return AnthropicProvider(config)
    if config.provider == ProviderType.MOCK:
        return MockProvider(config)
    return OpenAICompatibleProvider(config)
