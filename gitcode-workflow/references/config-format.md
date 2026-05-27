# 配置格式

默认路径：

```text
~/.config/gitcode-workflow/config.json
```

该文件用于管理设备级的稳定默认配置。

## 推荐优先级

1. 显式 CLI 参数
2. 环境变量
3. 本配置文件
4. 内置默认值

## 本 Skill 的安全约束

- 优先使用 `GITCODE_TOKEN` 或其它配置化的 token 环境变量。
- **不要**将 API token 持久化到 `config.json`。
- 该配置文件应放在仓库外部。
- 配置中仅存储 `ssh.private_key_path` 与 `ssh.public_key_path` 路径。
- **不要**在 JSON 中存储私钥明文内容。
- 若历史配置仍包含 `gitcode.token`，应视为已废弃并迁移出配置文件。

## 支持的字段

```json
{
  "git": {
    "user_name": "x-dc-xoder",
    "user_email": "x.dc0521@gmail.com",
    "config_scope": "local",
    "default_branch": "master",
    "commit_rules_path": "docs/rules/Git-Commit.md",
    "remote_name": "gitcode"
  },
  "gitcode": {
    "api_base": "https://api.gitcode.com/api/v5",
    "token_env_name": "GITCODE_TOKEN",
    "namespace": ""
  },
  "ssh": {
    "private_key_path": "~/.ssh/gitcode_wsl_ed25519",
    "public_key_path": "~/.ssh/gitcode_wsl_ed25519.pub",
    "title": "wsl-ubuntu-gitcode",
    "comment": "x.dc0521@gmail.com"
  },
  "safety": {
    "auto_update_gitignore": true,
    "auto_update_info_exclude": true,
    "abort_on_high_risk": true
  },
  "remote_validation": {
    "enabled": true,
    "allowed_hosts": ["gitcode.com"]
  }
}
```

## 脚本支持的环境变量

- `GITCODE_TOKEN`
- `GITCODE_TOKEN_ENV_NAME`
- `GITCODE_USER_NAME`
- `GITCODE_USER_EMAIL`
- `GITCODE_NAMESPACE`
- `GITCODE_SSH_PRIVATE_KEY_PATH`
- `GITCODE_SSH_PUBLIC_KEY_PATH`
- `GITCODE_SSH_TITLE`
- `GITCODE_SSH_COMMENT`
- `GITCODE_REMOTE_NAME`
- `GITCODE_CONFIG_SCOPE`
- `GITCODE_COMMIT_RULES_PATH`
- `GITCODE_ALLOWED_REMOTE_HOSTS`（逗号分隔 host，例如 `gitcode.com,gitlab.com`）
- `GITCODE_REMOTE_VALIDATION_ENABLED`（`true` 或 `false`）

## 说明

- 脚本默认使用 **repo-local** Git 身份、`master` 分支名和 `gitcode` 远端名，以满足“本地优先初始化”的使用场景。
- 当 `namespace` 为空时，脚本会尝试通过 `GET /api/v5/user` 自动解析。
- `preview` 默认会写入 `.git/gitcode-workflow-review.json` 审阅清单，供 `publish` 在暂存前校验快照一致性。
