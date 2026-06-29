# Quick Start

这份文档用最短路径带你把项目跑起来。当前推荐入口是浏览器工作台，命令行保留为兼容和自动化方式。

## 安装

```bash
pip install -e ".[dev]"
```

启动本地工作台：

```bash
python -m sfah.web --host 127.0.0.1 --port 8765
```

然后打开：

```text
http://127.0.0.1:8765
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
python -m sfah.web --host 127.0.0.1 --port 8765
```

打开工作台后，在界面里输入目标并依次点击“理解目标”“生成规格”“确认规格说明”“生成计划”“确认执行计划”“拆解任务”“执行待办任务”。

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

## 兼容命令行方式

如果你需要脚本化执行，仍然可以使用 CLI：

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



