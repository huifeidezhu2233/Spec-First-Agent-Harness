# CLI Reference

## Top-level

```bash
python -m sfah --help
sfah-cli init
sfah-cli status
```

## `llm`

```bash
sfah-cli llm init
sfah-cli llm status
sfah-cli llm profiles
sfah-cli llm show [profile]
sfah-cli llm use <profile>
sfah-cli llm add-profile --name ... --provider ... --model ...
sfah-cli llm remove-profile <profile>
sfah-cli llm test
```

## `discover`

```bash
sfah-cli discover start --goal "..."
sfah-cli discover show
```

## `spec`

```bash
sfah-cli spec create --goal "..."
sfah-cli spec show
sfah-cli spec approve
```

## `plan`

```bash
sfah-cli plan create
sfah-cli plan approve
sfah-cli plan show
sfah-cli plan show 3
sfah-cli plan add
sfah-cli plan update 3 --status WIP
sfah-cli plan sync
sfah-cli plan list
sfah-cli plan stats
```

## `tasks`

```bash
sfah-cli tasks generate
sfah-cli tasks generate --replace
sfah-cli tasks show
```

## `flow`

```bash
sfah-cli flow run --goal "实现一个支持邮箱密码登录的 API"
sfah-cli flow run --goal "..." --auto-approve
sfah-cli flow run --goal "..." --auto-approve --replace-tasks --execute
```

## `execute` / `work`

两组命令等价，`execute` 更适合对外表达，`work` 作为兼容别名保留。

```bash
sfah-cli execute solo 1
sfah-cli execute parallel
sfah-cli execute all
sfah-cli execute all 1-3
sfah-cli execute status
```

## `review`

```bash
sfah-cli review plan
sfah-cli review code src/auth.py
sfah-cli review code --all
sfah-cli review last
```


