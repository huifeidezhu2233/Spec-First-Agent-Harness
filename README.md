# Spec-First Agent Harness

Spec-First Agent Harness is a CLI-first workflow engine for turning ambiguous goals into reviewable discovery, spec, plan, task, execution, and review artifacts. Instead of asking an LLM to jump directly from prompt to code, it helps teams lock scope first, add approval checkpoints, persist every stage to disk, and keep delivery traceable from intent to implementation.

`Intent -> Discovery -> Spec -> Plan -> Tasks -> Execute -> Review`

`Spec-First Agent Harness` 是一个面向软件交付流程的 `spec-first + llm + harness` 项目。它不让模型从一句需求直接跳到代码，而是先把目标收敛为可审阅的 `discovery / spec / plan / tasks` 工件，再进入执行与审查，让范围、审批点、状态流转和执行结果都能被持续追踪。

## 适合谁

- 想让 LLM 工作流先收敛需求与范围，再进入实现的开发者或团队
- 需要 `human-in-the-loop` 审批点、可回放工件和可追踪状态的工程流程
- 想把“一次性对话输出”沉淀成稳定 CLI 工作流的工具作者

## 它解决什么问题

很多 LLM 工作流会直接从一句需求跳到实现，结果往往是范围漂移、任务拆分混乱、执行不可追踪。`Spec-First Agent Harness` 选择先固定工件，再推进执行：

`Intent -> Discovery -> Spec -> Plan -> Tasks -> Execute -> Review`

每个阶段都会落盘成可读文件，并把状态写入 `.harness/`，因此你可以审改、回放和继续推进，而不是依赖一次性对话上下文。

## 核心能力

- `Spec-first workflow`：从目标生成 `discovery.md`、`spec.md`、`plan.md`、`tasks.md`
- `Human-in-the-loop`：支持在 `spec` 和 `plan` 阶段审批后再继续
- `Flexible LLM profiles`：支持 OpenAI-compatible、Anthropic 和本地 mock profile
- `Execution artifacts`：执行任务时为每个任务生成实施说明和执行记录
- `Rule-based review`：从安全、性能、代码质量、可访问性、AI 残留五个维度做审查
- `CLI-first`：所有能力都可以通过命令行跑通，适合本地开发和自动化脚本

## 快速开始

### 1. 安装

```bash
pip install -e ".[dev]"
```

推荐两种启动方式：

- 仓库内直接运行：`python -m sfah`
- 安装后运行：`sfah-cli`

不要把旧环境里的 `sfah` 或 `harness` 命令当作当前仓库入口。这个项目已经使用独立的 `sfah` Python 包和 `sfah-cli` 控制台命令来规避旧安装版本冲突。

### 2. 初始化当前项目

```bash
sfah-cli init
```

这会创建项目元数据目录 `.harness/`，并生成默认的 LLM profile 配置文件 `.harness/llm.json`。

### 3. 选择运行方式

#### 本地演示模式

不需要 API key，直接切到 mock profile：

```bash
sfah-cli llm use mock
```

#### 真实模型模式

复制环境变量模板并填写 key：

```bash
cp .env.example .env
```

Windows PowerShell 可用：

```powershell
Copy-Item .env.example .env
```

最小配置示例：

```env
SFAH_ACTIVE_LLM_PROFILE=openai_compat
SFAH_OPENAI_COMPAT_API_KEY=your_api_key
SFAH_OPENAI_COMPAT_BASE_URL=https://api.openai.com/v1
SFAH_OPENAI_COMPAT_MODEL=gpt-5.4
```

检查状态：

```bash
sfah-cli llm status
sfah-cli llm profiles
```

### 4. 跑一遍完整流程

```bash
sfah-cli flow run --goal "实现一个支持邮箱密码登录的 API" --auto-approve
```

生成后你会得到：

- `.harness/discovery.md`
- `.harness/spec.md`
- `.harness/plan.md`
- `.harness/tasks.md`
- `Plans.md`

如果你希望把流程拆开、逐步审阅，可以用下面的分阶段命令：

```bash
sfah-cli discover start --goal "实现一个支持邮箱密码登录的 API"
sfah-cli spec create
sfah-cli spec show
sfah-cli spec approve
sfah-cli plan create
sfah-cli plan show
sfah-cli plan approve
sfah-cli tasks generate
sfah-cli plan list
sfah-cli execute all
sfah-cli review plan
```

## 执行阶段会产出什么

`execute`/`work` 命令不会直接假装“自动写完整项目”，而是把每个任务变成一份明确的实施说明和执行记录，输出到：

- `.harness/executions/task-1.md`
- `.harness/executions/task-2.md`
- ...

这些文件会包含：

- 当前任务描述
- 验收标准
- 建议实施步骤
- 建议改动点
- 验证方式
- 执行输出和结果状态

这让整个流程从“需求生成”真正延伸到“实现落地准备与执行记录”。

## 项目结构

```text
Spec-First Agent Harness/
├── sfah/
│   ├── cli.py               # CLI 入口
│   ├── workflow.py          # Discovery / Spec / Plan / Tasks 工件生成
│   ├── llm/                 # Profile、provider、解析与请求封装
│   ├── executor.py          # 执行协调与 execution artifacts
│   ├── reviewer.py          # 规则式审查引擎
│   ├── store.py             # 任务状态持久化
│   ├── history.py           # 事件与流程记录
│   └── models.py            # Task / Review 等核心数据模型
├── tests/                   # 单元测试与 CLI 测试
├── docs/
│   ├── quickstart.md
│   ├── architecture.md
│   ├── llm-profiles.md
│   └── cli.md
├── examples/
│   └── login-api/
│       └── README.md
├── .env.example
├── pyproject.toml
└── README.md
```

## 重要命令

- `sfah-cli init`：初始化当前目录
- `sfah-cli status`：查看整体状态、工件和任务概况
- `sfah-cli llm profiles`：列出所有 profile
- `sfah-cli llm add-profile ...`：新增或覆盖一个 LLM profile
- `sfah-cli flow run --goal "..." --auto-approve`：一条命令生成 discovery/spec/plan/tasks
- `sfah-cli execute all`：执行当前 TODO 任务并生成 execution artifacts
- `sfah-cli review plan`：检查 spec/plan/tasks 的一致性
- `sfah-cli review code --all`：递归审查当前项目源码中的 Python 文件

## 文档

- [快速开始](./docs/quickstart.md)
- [架构说明](./docs/architecture.md)
- [LLM Profile 说明](./docs/llm-profiles.md)
- [CLI 参考](./docs/cli.md)
- [登录 API 示例](./examples/login-api/README.md)

## 开发与测试

```bash
python -m pytest -q -o addopts=""
python -m sfah --help
```

## 许可证

MIT



