---
name: gitcode-workflow
description: Bootstrap git for local projects on WSL or Linux, apply repo-local git identity defaults, use master as the default branch, use gitcode as the default remote name, preview the exact pending files before any upload, freeze the reviewed snapshot into a .git review manifest before publish, optionally create and connect a private gitcode repository, and analyze an existing project to propose a layered commit strategy. Use this skill whenever the user needs to initialize git, configure local repo identity, read commit rules from docs/rules/git-commit.md with fallback to the bundled template, create a gitcode remote after explicit user instruction, publish only after the user confirms both the reviewed file set and the final commit message, or suggest how to split an already-built project into multiple clean commits without making repo changes. Also use when the user mentions gitcode, wants to push to gitcode, needs to create a gitcode repository, or wants to manage git workflow with token-based authentication.
---

# GitCode Git Workflow

Use this skill for WSL or Linux projects that need predictable local Git setup, safe GitCode remote creation, and commit guidance.

## Decide the mode first

1. Determine the user intent.
   - **local-only**: initialize a local repo, configure repo-local Git identity, and prepare ignore and safety rules.
   - **adopt-existing-project**: analyze an existing directory and output a layered commit strategy only.
   - **create-remote**: do the local bootstrap, create or reuse SSH material, and connect a GitCode remote without committing.
   - **preview**: inspect the worktree, show the exact file set that would be published, and write a review manifest under `.git/`.
   - **publish**: only after the user confirms the reviewed file set and a final commit message, verify the review manifest still matches and then push.

2. Respect side-effect boundaries.
   - `local-only`: repo-local changes only.
   - `adopt-existing-project`: analysis only, no repo mutation.
   - `create-remote`: external side effect, so only run after the user explicitly asks to create/connect the remote.
   - `preview`: safe to run, but it writes a review manifest inside `.git/`.
   - `publish`: external side effect, so only run after explicit user confirmation.

3. Load configuration.
   - Prefer `~/.config/gitcode-workflow/config.json`.
   - Use [references/config-format.md](references/config-format.md).
   - Precedence is: explicit CLI args > environment variables > config file > built-in defaults.
   - Recommend `GITCODE_TOKEN` or another configured token environment variable instead of writing tokens into JSON.
   - Keep the config file outside the repository.

4. Resolve commit rules.
   - First look for `docs/rules/Git-Commit.md` inside the project.
   - If that file does not exist, use [references/commit-rules.md](references/commit-rules.md).
   - Before any commit, read the active rules and keep the generated subject aligned with them.

## local-only workflow

Run:

```bash
python scripts/gitcode_bootstrap.py local-only --project /path/to/project --config ~/.config/gitcode-workflow/config.json --json
```

This workflow:
- initializes Git when `.git/` is missing
- keeps the identity **repo-local** by default
- defaults to `x-dc-coder / x.dc0521@gmail.com` unless overridden
- uses `master` as the default branch
- detects common stacks (`springboot/java`, `python`, `go`)
- appends shared ignore rules to `.gitignore`
- appends machine-local sensitive patterns to `.git/info/exclude`
- reports which commit-rules file is active

When the user only asks to configure local Git, stop after this workflow and summarize the results.

## adopt-existing-project workflow

Use this mode only when the user already has a built project and wants **layered commit advice** before starting Git management.

Run:

```bash
python scripts/gitcode_bootstrap.py adopt-existing-project --project /path/to/project --max-layers 6 --config ~/.config/gitcode-workflow/config.json --json
```

This workflow:
- inspects the current directory structure and common build files
- detects likely stacks and sensitive config candidates
- outputs a recommended layered commit order
- gives include samples, exclude patterns, and commit-message candidates for each layer
- labels the result as **heuristic** and **manual-review-required**
- does **not** initialize Git
- does **not** preview pending files
- does **not** create a remote
- does **not** commit or push
- does **not** change any project files

Always tell the user this is a path-and-filename heuristic draft, not an authoritative module boundary map.

## create-remote workflow

Run:

```bash
python scripts/gitcode_bootstrap.py create-remote --project /path/to/project --config ~/.config/gitcode-workflow/config.json --json
```

This workflow:
- performs the local-only workflow first
- gets the GitCode user profile with `GET /api/v5/user` using the token
- creates or reuses an ED25519 key pair
- checks existing keys with `GET /api/v5/user/keys`
- uploads the public key with `POST /api/v5/user/keys` only if needed
- creates a **private** personal repository with `POST /api/v5/user/repos`
- uses the current directory name as the default repo name unless overridden
- configures `gitcode` as the default remote name
- sets `remote.pushDefault` to that remote
- does **not** commit or push

Do not run this mode unless the user has clearly asked to create or connect a remote repository.

## preview workflow

Always run this before any publish or push:

```bash
python scripts/gitcode_bootstrap.py preview --project /path/to/project --config ~/.config/gitcode-workflow/config.json --json
```

Important behavior:
- it groups the pending files by added, modified, deleted, renamed, and untracked
- it shows blocked high-risk files or warnings from the safety scan
- it uses `preview.diff_excerpt`, `preview.type_hints`, `preview.scope_hints`, and the active commit rules to draft **3 commit-message candidates**
- it writes a review manifest to `.git/gitcode-workflow-review.json` by default, or to `--review-manifest <path>` if provided
- the review manifest freezes the reviewed file set and content hashes for the next publish step

After `preview`:
1. Show the pending file list grouped by added, modified, deleted, renamed, and untracked.
2. Show blocked high-risk files or warnings from the safety scan.
3. Draft **3 commit-message candidates**.
4. Prefer concise Chinese subject lines when the active rules require Chinese subjects.
5. Ask the user to choose one option or edit it.
6. Surface the review-manifest path and snapshot hash.
7. Do **not** run `publish` until the user confirms the final message.

Example output shape:

```text
Pending files
- added: ...
- modified: ...
- deleted: ...

Commit message options
1. feat(scope): <subject>
2. fix(scope): <subject>
3. refactor(scope): <subject>

Review manifest
- path: .git/gitcode-workflow-review.json
- snapshot: <sha256>
```

## publish workflow

Use this only after the user has explicitly confirmed a final commit message.

Run:

```bash
python scripts/gitcode_bootstrap.py publish --project /path/to/project --commit-message "feat(scope): <subject>" --config ~/.config/gitcode-workflow/config.json --json
```

The publish workflow:
- loads the review manifest from `.git/gitcode-workflow-review.json` by default, or `--review-manifest <path>` if provided
- aborts if the manifest is missing, belongs to another project, or no longer matches the current worktree
- validates the commit-message format against the allowed conventional types
- ensures the remote exists, creating it if needed and a token is available
- runs the safety scan before staging
- aborts on high-risk secret files that are present but not ignored
- stages **only the reviewed manifest targets**, commits once, and pushes the current branch to the configured remote
- clears the review manifest after a successful publish

If the user asks to push but the worktree changed after preview, rerun `preview` and make them review the new file set first.

## SSH preflight before publish

Before running `publish`, do a lightweight SSH preflight in WSL/Linux:

1. Ensure `~/.ssh/config` contains a `Host gitcode.com` entry with:
   - `User git`
   - `IdentityFile ~/.ssh/<your-key>`
   - `IdentitiesOnly yes`
2. Verify permissions:
   - `chmod 600 ~/.ssh/config`
   - private key file should remain `600`
3. Verify connectivity:
   - `ssh -T git@gitcode.com`

If the key file is non-default (not `id_rsa` / `id_ed25519`) and no ssh-agent is loaded, publish may fail with `Permission denied (publickey)`.

Temporary fallback:

```bash
GIT_SSH_COMMAND='ssh -i ~/.ssh/<your-key> -o IdentitiesOnly=yes' git push -u gitcode master
```

Then fix `~/.ssh/config` permanently.

## CJK path stability note

When the repository contains Chinese/Japanese/Korean filenames, set repo-local:

```bash
git config core.quotepath false
```

This avoids quoted/escaped paths in status output and reduces pathspec mismatch risk in automated staging/publish flows.

## Commit-message drafting rules

Use [references/commit-rules.md](references/commit-rules.md) when the project file is missing.

When drafting options:
- use one of `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `chore`, `revert`
- include a scope whenever a clear scope is available
- keep the subject concise and action-oriented
- do not end the subject with punctuation
- keep the final subject close to the stated length target in the active rules
- when multiple interpretations are plausible, present a preferred option plus safer alternatives

## Safety rules

Follow [references/safety-and-ignore.md](references/safety-and-ignore.md).

Key rules:
- put shared, team-wide ignore rules in `.gitignore`
- put machine-local or user-local secret patterns in `.git/info/exclude`
- keep the GitCode config file outside the repository
- store SSH key **paths** in config, not raw private-key contents
- prefer token environment variables instead of JSON secrets
- before every push, check for `.env`, key stores, private keys, service-account JSON, and local Spring config files

## Worked examples

### Example A: first local bootstrap
User intent: "帮我在这个项目里先初始化 Git，但先不要连远端。"

Assistant behavior:
1. run `local-only`
2. report repo initialization, identity, stack detection, active commit rules, and ignore updates
3. stop without preview or publish

### Example B: review before first push
User intent: "帮我看看现在会提交哪些文件，并给我几个提交信息备选。"

Assistant behavior:
1. run `preview`
2. show grouped file list and safety findings
3. draft 3 commit-message options
4. surface the review-manifest path and snapshot hash
5. wait for the user to confirm a final message

### Example C: publish after confirmation
User intent: "就用第 2 个提交信息，开始推送。"

Assistant behavior:
1. run `publish` with the confirmed message
2. rely on the saved review manifest
3. abort if the worktree changed since preview
4. report remote, branch, commit hash, staged targets, and manifest cleanup status

## Output expectations

Always report the project path and the mode used.

Additionally:
- `local-only`: report whether the repo was initialized, Git identity values, detected stacks, active commit-rules source, and whether `.gitignore` / `.git/info/exclude` changed.
- `adopt-existing-project`: report only the layered commit strategy, sensitive candidates, heuristic caveats, and commit-message suggestions for each proposed layer.
- `preview` and `publish`: report the pending upload file list, generated commit-message candidates, and review-manifest details.
- `create-remote` and `publish`: report remote name / URL and SSH key status.

## Issue 管理

使用 Issue 功能进行任务跟踪、bug 报告和项目管理。

### Issue 工作流

1. **列出 Issue**
   ```bash
   python scripts/gitcode_issues.py list --owner <owner> --repo <repo> [--state open|closed|all] [--json]
   ```

2. **创建 Issue**
   ```bash
   python scripts/gitcode_issues.py create --owner <owner> --repo <repo> --title "<title>" [--body "<body>"] [--labels "<labels>"] [--json]
   ```

3. **查看 Issue**
   ```bash
   python scripts/gitcode_issues.py get --owner <owner> --repo <repo> <number> [--json]
   ```

4. **更新 Issue**
   ```bash
   python scripts/gitcode_issues.py update --owner <owner> --repo <repo> <number> [--title "<title>"] [--body "<body>"] [--state open|closed] [--json]
   ```

5. **关闭 Issue**
   ```bash
   python scripts/gitcode_issues.py close --owner <owner> --repo <repo> <number> [--json]
   ```

6. **重新打开 Issue**
   ```bash
   python scripts/gitcode_issues.py reopen --owner <owner> --repo <repo> <number> [--json]
   ```

7. **列出评论**
   ```bash
   python scripts/gitcode_issues.py comments --owner <owner> --repo <repo> <number> [--json]
   ```

8. **添加评论**
   ```bash
   python scripts/gitcode_issues.py comment-create --owner <owner> --repo <repo> <number> --body "<body>" [--json]
   ```

### Issue 使用场景

- **个人 TODO**: 用 Issue 替代本地待办列表，随时随地访问
- **Bug 跟踪**: 记录发现的问题，关联修复提交
- **功能规划**: 标记未来要实现的功能
- **代码审查反馈**: 在 Issue 中讨论代码改进

### Issue 与 Git 工作流集成

建议在 `publish` 后自动关联 Issue:
- 提交信息中使用 `#1` 引用 Issue
- 使用 `fix #1` 或 `close #1` 自动关闭 Issue

## Resources

- [scripts/gitcode_bootstrap.py](scripts/gitcode_bootstrap.py): deterministic bootstrap automation
- [scripts/gitcode_issues.py](scripts/gitcode_issues.py): Issue management automation
- [references/config-format.md](references/config-format.md): config schema and precedence
- [references/commit-rules.md](references/commit-rules.md): bundled fallback commit template
- [references/safety-and-ignore.md](references/safety-and-ignore.md): secret-protection and review-manifest strategy
- [references/api-capabilities.md](references/api-capabilities.md): full GitCode API v5 capabilities
- [assets/config.example.json](assets/config.example.json): copyable starter config
