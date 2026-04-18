# Quick Start

这份文档用最短路径带你把项目跑起来。

## 安装

```bash
pip install -e ".[dev]"
```

或者直接用模块方式运行：

```bash
python -m sfah --help
```

## 初始化

```bash
sfah-cli init
```

执行后会生成：

- `.harness/llm.json`
- 后续运行需要的 `.harness/` 状态目录

## 本地无 key 跑通

如果你只是想体验完整流程，不想先接入远端模型：

```bash
sfah-cli llm use mock
sfah-cli flow run --goal "实现一个支持邮箱密码登录的 API" --auto-approve
sfah-cli plan list
sfah-cli execute all
sfah-cli review plan
```

## 接入真实模型

复制环境变量模板：

```bash
cp .env.example .env
```

Windows PowerShell 可用：

```powershell
Copy-Item .env.example .env
```

示例：

```env
SFAH_ACTIVE_LLM_PROFILE=openai_compat
SFAH_OPENAI_COMPAT_API_KEY=your_api_key
SFAH_OPENAI_COMPAT_BASE_URL=https://api.openai.com/v1
SFAH_OPENAI_COMPAT_MODEL=gpt-5.4
```

检查配置：

```bash
sfah-cli llm status
sfah-cli llm test
```

## 逐阶段交互

如果你想在每一步都人工确认：

```bash
sfah-cli discover start --goal "实现一个支持邮箱密码登录的 API"
sfah-cli discover show

sfah-cli spec create
sfah-cli spec show
sfah-cli spec approve

sfah-cli plan create
sfah-cli plan show
sfah-cli plan approve

sfah-cli tasks generate
sfah-cli tasks show
sfah-cli plan list

sfah-cli execute all
sfah-cli review plan
```

## 运行后会看到什么

工件目录：

- `.harness/discovery.md`
- `.harness/spec.md`
- `.harness/plan.md`
- `.harness/tasks.md`
- `.harness/workflow.json`
- `.harness/state.json`
- `.harness/events.json`
- `.harness/executions/task-*.md`

对外可读任务总览：

- `Plans.md`

## 常见问题

### 1. 没有 API key 可以用吗？

可以。切换到 `mock` profile 即可。

### 2. 不想用 `sfah-cli` 命令怎么办？

可以直接用：

```bash
python -m sfah <subcommand>
```

### 3. `execute` 会直接写完业务代码吗？

当前执行层重点是任务编排、实施说明生成和执行记录落盘。它适合作为实现阶段的控制层，而不是直接替代完整的代码代理。



