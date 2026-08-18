# gh CLI 速查（GitHub 官方能力全表）

本技能不重复实现 GitHub API；GitHub 侧能力一律用官方 `gh`。以下为常用命令。

## 认证

```bash
gh auth login                # 交互式登录（浏览器 / token）
gh auth status               # 查看当前登录状态
gh auth setup-git            # 让 git 走 gh 凭证（https 推送免密）
gh auth switch               # 切换账号（多账号时）
```

## 仓库

```bash
gh repo create <name> --private --source=. --remote=origin --push   # 建仓+连远端+推送
gh repo create <o>/<name> --public                                   # 建空仓
gh repo view <o>/<r> --json defaultBranchRef,isFork,isPrivate        # 查看仓库信息
gh repo edit <o>/<r> --default-branch master                         # 改默认分支
gh repo edit <o>/<r> --add-topic xxx --description "..."             # 改描述/话题
gh repo list [<owner>] --limit 200 --json name,isPrivate             # 列仓库（JSON）
gh repo clone <o>/<r>                                                # 克隆
gh repo delete <o>/<r> --yes                                         # 删除（慎用）
```

## Issue

```bash
gh issue list --repo <o>/<r> --state open --label bug --limit 50
gh issue create --repo <o>/<r> --title "..." --body "..." --label bug --assignee @me
gh issue view <n> --repo <o>/<r> --comments
gh issue edit <n> --repo <o>/<r> --title "..." --body "..."
gh issue close <n> --repo <o>/<r>
gh issue reopen <n> --repo <o>/<r>
gh issue comment <n> --repo <o>/<r> --body "..."
```

## PR

```bash
gh pr create --base master --title "..." --body "..." --assignee @me
gh pr list --repo <o>/<r> --state open
gh pr view <n> --repo <o>/<r>
gh pr diff <n>
gh pr merge <n> --merge            # merge 提交计入贡献图
gh pr checkout <n>                 # 检出 PR 分支
```

## 用户信息（gh api）

```bash
gh api user                       # 当前用户完整信息
gh api users/<username>           # 指定用户公开信息
gh api user/emails                # 已验证邮箱列表（贡献图归属判定用）
gh api user/starred --paginate    # 收藏仓库
gh api -X PATCH user -f bio="..." -f location="..."   # 修改个人资料
gh api repos/<o>/<r>/branches --jq '.[].name'         # 分支列表
```

## 贡献图（绿点）排障

1. 默认分支：`gh repo view <o>/<r> --json defaultBranchRef` → 不是提交所在分支就
   `gh repo edit <o>/<r> --default-branch master`
2. 邮箱：`git log --format='%ae' | sort -u` 对比 `gh api user/emails`（需已验证）
3. 时间：贡献图只统计最近一年（滚动）
4. 私有仓库：Profile → Contribution settings → *Include private contributions*
5. 缓存：改完等数小时；必要时推空提交 `git commit --allow-empty -m "chore: refresh"` 触发重算

## 9p/drvfs 挂载注意事项

`/mnt/*`（Windows 盘符经 9P 挂载）无 `metadata` 选项时 chmod 返回 EPERM：
- `git config` / `git remote add` / `git push -u` 等写 `.git/config` 的命令会失败
- 根治：`~/bin/enable-drvfs-metadata.sh`（sudo 执行后 `wsl --shutdown` 重启）
- 临时绕过：直接编辑 `.git/config`；push 用不带 `-u` 的普通 push（本技能 publish 已自动降级）
