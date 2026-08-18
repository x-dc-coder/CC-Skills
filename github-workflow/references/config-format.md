# 配置格式与优先级（github-workflow）

## 配置文件位置

`~/.config/github-workflow/config.json`（可选；不存在时使用内置默认值）

## 配置优先级

CLI 参数 > 环境变量（`GITHUB_*`）> 配置文件 > 内置默认值

## 内置默认值（与 assets/config.example.json 一致）

```json
{
  "git": {
    "user_name": "x-dc-coder",
    "user_email": "x.dc0521@gmail.com",
    "config_scope": "local",
    "default_branch": "master",
    "commit_rules_path": "docs/rules/Git-Commit.md",
    "remote_name": "origin"
  },
  "github": {
    "hostname": "github.com",
    "default_private": true
  },
  "safety": {
    "auto_update_gitignore": true,
    "auto_update_info_exclude": true,
    "abort_on_high_risk": true
  },
  "remote_validation": {
    "enabled": true,
    "allowed_hosts": ["github.com"]
  }
}
```

## 字段说明

| 段 | 字段 | 说明 |
|----|------|------|
| `git` | `user_name` / `user_email` | 仓库级 git 身份（`local-only` 时写入） |
| `git` | `config_scope` | `local`（默认）或 `global` |
| `git` | `default_branch` | 初始化默认分支（`master`） |
| `git` | `commit_rules_path` | 项目内提交规范路径；不存在时用内置模板 |
| `git` | `remote_name` | 默认 remote 名（`origin`） |
| `github` | `hostname` / `default_private` | GitHub 主机 / 新建仓库默认私有 |
| `safety` | 见下 | 安全扫描开关 |
| `remote_validation` | `allowed_hosts` | 允许的远程主机白名单（默认 `github.com`） |

## 环境变量（可选）

| 变量 | 对应配置 |
|------|----------|
| `GITHUB_USER_NAME` / `GITHUB_USER_EMAIL` | git 身份 |
| `GITHUB_CONFIG_SCOPE` | local/global |
| `GITHUB_DEFAULT_BRANCH` | 默认分支 |
| `GITHUB_COMMIT_RULES_PATH` | 提交规范路径 |
| `GITHUB_REMOTE_NAME` | 默认 remote 名 |
| `GITHUB_HOSTNAME` / `GITHUB_DEFAULT_PRIVATE` | GitHub 配置 |
| `GITHUB_ALLOWED_REMOTE_HOSTS` | 逗号分隔的白名单 |

## 与旧版 gitcode-workflow 的关系

- 旧配置 `~/.config/gitcode-workflow/config.json`（含 `gitcode` 段、SSH 密钥路径）**不再使用**。
- 检测到配置文件中残留 `gitcode` 段时，脚本会输出迁移提示（可安全删除）。
- GitHub 认证与密钥全部交给 `gh` 管理，配置文件中不再存放任何 token/密钥。
