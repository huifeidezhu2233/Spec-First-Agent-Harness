# Architecture

`Spec-First Agent Harness` 的核心思路是：先把目标变成稳定工件，再把工件变成可执行任务。

## 流程总览

```text
Intent
  -> Discovery
  -> Spec
  -> Plan
  -> Tasks
  -> Execute
  -> Review
```

## 组件划分

### 1. CLI 层

文件：

- `sfah/cli.py`

职责：

- 解析命令行输入
- 协调 workflow、store、history、reviewer
- 提供 `init / status / flow / llm / spec / plan / tasks / execute / review` 命令

### 2. Workflow 层

文件：

- `sfah/workflow.py`

职责：

- 将用户意图转成 `discovery/spec/plan/tasks` 四类工件
- 维护 `workflow.json` 阶段状态
- 在有 LLM 时优先走结构化生成；失败时回退到本地规则

### 3. LLM Runtime 层

目录：

- `sfah/llm/`

职责：

- 管理项目级 profile
- 解析 `.env` 和 `.harness/llm.json`
- 适配 OpenAI-compatible、Anthropic、Mock provider
- 统一处理 JSON / Markdown / text 生成

### 4. Task State 层

文件：

- `sfah/models.py`
- `sfah/store.py`
- `sfah/history.py`

职责：

- 维护 `Task / Priority / TaskStatus`
- 持久化任务图和执行状态
- 记录流程事件、任务事件和执行产物事件

### 5. Execution 层

文件：

- `sfah/executor.py`

职责：

- 按 `Solo / Parallel` 模式推进任务
- 为每个任务生成实施说明
- 把执行结果保存到 `.harness/executions/`

### 6. Review 层

文件：

- `sfah/reviewer.py`

职责：

- 对代码或计划做质量门检查
- 输出 `APPROVE / REQUEST_CHANGES`
- 提供安全、性能、质量、可访问性、AI 残留五类规则

## 关键设计点

### Artifact-driven

所有核心阶段都落地为文件，而不是只保留在会话上下文里。这使得你可以：

- 审改上一步产物
- 回放工作流
- 让不同角色在不同阶段接手

### Human-in-the-loop

`spec` 和 `plan` 都支持“先生成、再批准”的门控方式，避免需求尚未收敛时就开始拆任务。

### Profile-based LLM access

LLM 能力不是写死在代码里的，而是通过项目级 profile 解析。这样同一个项目可以针对不同团队或不同环境切换模型与供应商。

### Fallback-first robustness

如果远端模型调用失败，workflow 不会直接中断，而是回退到本地规则生成，保证流程仍可继续。

## 数据目录

`.harness/` 下的关键文件：

- `workflow.json`：流程阶段与工件索引
- `state.json`：任务状态
- `events.json`：事件历史
- `discovery.md / spec.md / plan.md / tasks.md`：核心工件
- `executions/task-*.md`：执行说明与结果

## 为什么执行层要生成 execution artifacts

很多 workflow 在任务拆分之后就断掉了。这里的执行层会把“任务”继续转成：

- 实施步骤
- 建议改动点
- 验证方式
- 执行记录

这样流程就不会停留在纸面任务，而是能继续往实现推进。

