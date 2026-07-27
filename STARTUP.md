# Spec-First-Agent-Harness 启动说明

本文说明如何在本地创建虚拟环境、安装依赖、配置模型参数并启动项目。

## 1. 环境要求

- Python 3.11 或更高版本
- Windows PowerShell、CMD、Git Bash 或其他终端

## 2. 创建虚拟环境

在项目根目录执行：

```powershell
python -m venv Spec-First-Agent-Harness
```

激活环境：

```powershell
.\Spec-First-Agent-Harness\Scripts\activate
```

如果使用 macOS 或 Linux：

```bash
python -m venv Spec-First-Agent-Harness
source Spec-First-Agent-Harness/bin/activate
```

## 3. 安装依赖

```powershell
python -m ensurepip --upgrade
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

安装完成后可以检查入口命令：

```powershell
sfah-cli --help
python -m sfah --help
```

## 4. 配置环境变量

复制示例配置：

```powershell
Copy-Item .env.example .env
```

如果使用 macOS 或 Linux：

```bash
cp .env.example .env
```

打开 `.env`，按你的模型服务填写：

```env
SFAH_ACTIVE_LLM_PROFILE=openai_compat
SFAH_OPENAI_COMPAT_API_KEY=your_api_key
SFAH_OPENAI_COMPAT_BASE_URL=https://api.openai.com/v1
SFAH_OPENAI_COMPAT_MODEL=gpt-5.4
SFAH_OPENAI_COMPAT_TIMEOUT_SECONDS=90
```

如果暂时没有 API Key，可以先使用 mock 模式。

## 5. 初始化项目

```powershell
sfah-cli init
```

查看模型配置状态：

```powershell
sfah-cli llm status
sfah-cli llm profiles
```

切换到 mock 模式：

```powershell
sfah-cli llm use mock
```

## 6. 运行完整流程

```powershell
sfah-cli flow run --goal "实现一个支持邮箱密码登录的 API" --auto-approve
```

常用命令：

```powershell
sfah-cli status
sfah-cli spec show
sfah-cli plan show
sfah-cli tasks generate
sfah-cli execute all
sfah-cli review plan
```

## 7. 运行测试

```powershell
python -m pytest -q -o addopts=""
```

## 8. 生成文件位置

项目运行后主要生成以下文件：

- `.harness/discovery.md`
- `.harness/spec.md`
- `.harness/plan.md`
- `.harness/tasks.md`
- `.harness/executions/task-*.md`
- `Plans.md`

这些文件用于记录需求、规格、计划、任务拆解和执行结果。
