# LLM Profiles

项目通过 profile 管理 LLM 接入，而不是把 endpoint、model、api key 写死在代码里。

## 默认 profile

初始化后，`.harness/llm.json` 会包含三个默认 profile：

- `openai_compat`
- `anthropic`
- `mock`

查看它们：

```bash
sfah-cli llm profiles
sfah-cli llm show openai_compat
```

## 环境变量

推荐在项目根目录放置 `.env`。

### OpenAI-compatible

```env
SFAH_ACTIVE_LLM_PROFILE=openai_compat
SFAH_OPENAI_COMPAT_API_KEY=your_api_key
SFAH_OPENAI_COMPAT_BASE_URL=https://api.openai.com/v1
SFAH_OPENAI_COMPAT_MODEL=gpt-5.4
SFAH_OPENAI_COMPAT_TIMEOUT_SECONDS=90
```

### Anthropic

```env
SFAH_ACTIVE_LLM_PROFILE=anthropic
SFAH_ANTHROPIC_API_KEY=your_api_key
SFAH_ANTHROPIC_BASE_URL=https://api.anthropic.com
SFAH_ANTHROPIC_MODEL=claude-3-7-sonnet-latest
```

## 新增自定义 profile

例如添加一个新的 OpenAI-compatible relay：

```bash
sfah-cli llm add-profile ^
  --name my_relay ^
  --provider openai_compat ^
  --model gpt-5.4 ^
  --base-url https://your-relay.example/v1 ^
  --api-key-env MY_RELAY_API_KEY ^
  --activate
```

再在 `.env` 中补上：

```env
MY_RELAY_API_KEY=your_key_here
```

## 常用命令

```bash
sfah-cli llm profiles
sfah-cli llm show
sfah-cli llm use mock
sfah-cli llm test
sfah-cli llm remove-profile my_relay
```

## Profile 文件结构

`.harness/llm.json` 示例：

```json
{
  "version": 1,
  "active_profile": "openai_compat",
  "profiles": [
    {
      "name": "openai_compat",
      "provider": "openai_compat",
      "model": "gpt-5.4",
      "base_url": "https://api.openai.com/v1",
      "api_key_env": "SFAH_OPENAI_COMPAT_API_KEY",
      "timeout_seconds": 90,
      "temperature": 0.2,
      "max_tokens": 4096,
      "extra_headers": {}
    }
  ]
}
```

## 什么时候用 mock

`mock` 适合：

- 跑测试
- 演示整个 workflow
- 在没有真实 key 的环境下本地开发

切换方法：

```bash
sfah-cli llm use mock
```

## 回退机制

workflow 生成工件时遵循下面的顺序：

1. 当前 profile 已配置完整，先调用真实 provider
2. 如果远端调用失败，自动回退到本地规则
3. 继续生成 discovery/spec/plan/tasks，保证流程不中断

