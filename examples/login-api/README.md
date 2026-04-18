# Example: Login API

这个示例展示如何把一句需求逐步推进成 spec、plan、tasks 和 execution artifacts。

## 目标

```text
实现一个支持邮箱密码登录的 API，并补齐错误处理和最小验证路径
```

## 推荐命令

```bash
sfah-cli llm use mock
sfah-cli flow run --goal "实现一个支持邮箱密码登录的 API，并补齐错误处理和最小验证路径" --auto-approve
sfah-cli plan list
sfah-cli execute all
sfah-cli review plan
```

## 你会得到什么

### 工件

- `discovery.md`
- `spec.md`
- `plan.md`
- `tasks.md`

### 任务图

- 一组带依赖关系和验收标准的任务
- 自动同步的 `Plans.md`

### 执行记录

- `.harness/executions/task-1.md`
- `.harness/executions/task-2.md`
- ...

## 适合怎么用

这个示例很适合用来演示：

- 如何把模糊需求先收敛成 spec
- 如何在批准 spec 和 plan 后再拆任务
- 如何让任务执行阶段继续产出可交付的执行说明

