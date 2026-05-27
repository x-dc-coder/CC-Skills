# GitCode API v5 完整功能清单

> 基于官方文档 https://docs.gitcode.com/v1-docs/docs/openapi/ 整理
> API Base: `https://api.gitcode.com/api/v5`

---

## 目录

1. [认证与授权](#1-认证与授权)
2. [用户管理](#2-用户管理)
3. [仓库管理](#3-仓库管理)
4. [分支管理](#4-分支管理)
5. [Issue 管理](#5-issue-管理)
6. [Pull Request 管理](#6-pull-request-管理)
7. [Webhook 管理](#7-webhook-管理)
8. [Release 管理](#8-release-管理)
9. [标签管理](#9-标签管理)
10. [里程碑管理](#10-里程碑管理)
11. [提交与文件](#11-提交与文件)
12. [搜索](#12-搜索)
13. [通知](#13-通知)
14. [组织与企业](#14-组织与企业)
15. [成员与权限](#15-成员与权限)
16. [代码审查设置](#16-代码审查设置)
17. [可扩展功能建议](#17-可扩展功能建议)

---

## 1. 认证与授权

| 端点 | 方法 | 描述 | 当前skill使用 |
|------|------|------|--------------|
| `GET /user` | GET | 获取认证用户信息 | ✅ 已使用 |
| `GET /user/keys` | GET | 列出用户SSH公钥 | ✅ 已使用 |
| `POST /user/keys` | POST | 添加SSH公钥 | ✅ 已使用 |
| `DELETE /user/keys/{id}` | DELETE | 删除SSH公钥 | ❌ |
| `GET /user/keys/{id}` | GET | 获取单个公钥 | ❌ |
| `GET /user/namespace` | GET | 获取用户命名空间 | ❌ |
| `GET /user/starred` | GET | 列出用户star的仓库 | ❌ |
| `GET /user/repos` | GET | 列出用户仓库 | ❌ |
| `GET /user/issues` | GET | 获取授权用户的Issues | ❌ |

---

## 2. 用户管理

| 端点 | 方法 | 描述 |
|------|------|------|
| `GET /users/{username}` | GET | 获取用户信息 |
| `GET /users/{username}/events` | GET | 获取用户活动/事件 |
| `GET /users/{username}/repos` | GET | 获取用户公开仓库 |
| `GET /emails` | GET | 获取认证用户邮箱 |

---

## 3. 仓库管理

### 3.1 CRUD 操作

| 端点 | 方法 | 描述 | 当前skill使用 |
|------|------|------|--------------|
| `POST /user/repos` | POST | 创建个人仓库 | ✅ 已使用 |
| `POST /orgs/{org}/repos` | POST | 创建组织仓库 | ❌ |
| `GET /repos/{owner}/{repo}` | GET | 获取仓库信息 | ❌ |
| `PATCH /repos/{owner}/{repo}` | PATCH | 更新仓库设置 | ❌ |
| `DELETE /repos/{owner}/{repo}` | DELETE | 删除仓库 | ❌ |
| `POST /repos/{owner}/{repo}/forks` | POST | Fork仓库 | ❌ |
| `GET /repos/{owner}/{repo}/forks` | GET | 列出Forks | ❌ |
| `POST /repos/{owner}/{repo}/transfer` | POST | 转移仓库 | ❌ |
| `PUT /org/{org}/repo/{repo}/status` | PUT | 归档/取消归档仓库 | ❌ |

### 3.2 仓库设置

| 端点 | 方法 | 描述 |
|------|------|------|
| `GET /repos/{owner}/{repo}/repo_settings` | GET | 获取详细仓库设置 |
| `PUT /repos/{owner}/{repo}/repo_settings` | PUT | 更新详细仓库设置 |
| `GET /repos/{owner}/{repo}/pull_request_settings` | GET | 获取PR设置 |
| `PUT /repos/{owner}/{repo}/pull_request_settings` | PUT | 更新PR设置 |
| `GET /repos/{owner}/{repo}/push_config` | GET | 获取推送规则 |
| `PUT /repos/{owner}/{repo}/push_config` | PUT | 设置推送规则 |
| `GET /repos/{owner}/{repo}/transition` | GET | 获取权限模式 |
| `PUT /repos/{owner}/{repo}/transition` | PUT | 更新权限模式 |
| `PUT /repos/{owner}/{repo}/reviewer` | PUT | 更新代码审查设置 |
| `PUT /repos/{owner}/{repo}/module/setting` | PUT | 设置项目模块 |

### 3.3 仓库统计

| 端点 | 方法 | 描述 |
|------|------|------|
| `GET /repos/{owner}/{repo}/languages` | GET | 获取仓库语言统计 |
| `GET /repos/{owner}/{repo}/contributors` | GET | 获取贡献者列表 |
| `GET /repos/{owner}/{repo}/contributors/statistic` | GET | 贡献者统计 |
| `GET /repos/{owner}/{repo}/stargazers` | GET | 列出star用户 |
| `GET /repos/{owner}/{repo}/subscribers` | GET | 列出watch用户 |
| `GET /repos/{owner}/{repo}/events` | GET | 仓库事件 |
| `GET /repos/{owner}/{repo}/download_statistics` | GET | 下载统计 |

### 3.4 文件操作

| 端点 | 方法 | 描述 |
|------|------|------|
| `GET /repos/{owner}/{repo}/contents/{path}` | GET | 获取路径内容 |
| `POST /repos/{owner}/{repo}/contents/{path}` | POST | 创建文件 |
| `PUT /repos/{owner}/{repo}/contents/{path}` | PUT | 更新文件 |
| `DELETE /repos/{owner}/{repo}/contents/{path}` | DELETE | 删除文件 |
| `GET /repos/{owner}/{repo}/git/trees/{sha}` | GET | 获取仓库树 |
| `GET /repos/{owner}/{repo}/git/blobs/{sha}` | GET | 获取文件blob |
| `GET /repos/{owner}/{repo}/file_list` | GET | 获取文件列表 |
| `GET /repos/{owner}/{repo}/raw/{path}` | GET | 获取原始文件内容 |
| `POST /repos/{owner}/{repo}/img/upload` | POST | 上传图片 |
| `POST /repos/{owner}/{repo}/file/upload` | POST | 上传文件 |

---

## 4. 分支管理

| 端点 | 方法 | 描述 |
|------|------|------|
| `GET /repos/{owner}/{repo}/branches` | GET | 列出所有分支 |
| `POST /repos/{owner}/{repo}/branches` | POST | 创建分支 |
| `GET /repos/{owner}/{repo}/branches/{branch}` | GET | 获取单个分支 |
| `GET /repos/{owner}/{repo}/protect_branches` | GET | 列出保护规则 |
| `PUT /repos/{owner}/{repo}/branches/setting/new` | PUT | 创建保护规则 |
| `PUT /repos/{owner}/{repo}/branches/{wildcard}/setting` | PUT | 更新保护规则 |
| `DELETE /repos/{owner}/{repo}/branches/{wildcard}/setting` | DELETE | 删除保护规则 |

---

## 5. Issue 管理

### 5.1 Issue CRUD

| 端点 | 方法 | 描述 |
|------|------|------|
| `GET /repos/{owner}/{repo}/issues` | GET | 列出仓库Issues |
| `POST /repos/{owner}/issues` | POST | 创建Issue |
| `GET /repos/{owner}/{repo}/issues/{number}` | GET | 获取单个Issue |
| `PATCH /repos/{owner}/issues/{number}` | PATCH | 更新Issue |

### 5.2 Issue 评论

| 端点 | 方法 | 描述 |
|------|------|------|
| `GET /repos/{owner}/{repo}/issues/{number}/comments` | GET | 获取Issue评论 |
| `POST /repos/{owner}/{repo}/issues/{number}/comments` | POST | 创建Issue评论 |
| `GET /repos/{owner}/{repo}/issues/comments` | GET | 获取所有Issue评论 |
| `GET /repos/{owner}/{repo}/issues/comments/{id}` | GET | 获取单个评论 |
| `PATCH /repos/{owner}/{repo}/issues/comments/{id}` | PATCH | 更新评论 |
| `DELETE /repos/{owner}/{repo}/issues/comments/{id}` | DELETE | 删除评论 |

### 5.3 Issue 标签

| 端点 | 方法 | 描述 |
|------|------|------|
| `POST /repos/{owner}/{repo}/issues/{number}/labels` | POST | 添加Issue标签 |
| `DELETE /repos/{owner}/{repo}/issues/{number}/labels/{name}` | DELETE | 删除Issue标签 |
| `GET /enterprises/{enterprise}/issues/{issue_id}/labels` | GET | 获取企业Issue标签 |

### 5.4 Issue 其他

| 端点 | 方法 | 描述 |
|------|------|------|
| `GET /repos/{owner}/issues/{number}/operate_logs` | GET | 获取Issue操作日志 |
| `GET /repos/{owner}/{repo}/issues/{number}/pull_requests` | GET | 获取关联的PR |
| `GET /enterprises/{enterprise}/issues` | GET | 列出企业Issues |
| `GET /enterprises/{enterprise}/issues/{number}` | GET | 获取企业Issue |
| `GET /enterprises/{enterprise}/issues/{number}/comments` | GET | 获取企业Issue评论 |
| `GET /orgs/{org}/issues` | GET | 获取组织Issues |

---

## 6. Pull Request 管理

### 6.1 PR CRUD

| 端点 | 方法 | 描述 |
|------|------|------|
| `GET /repos/{owner}/{repo}/pulls` | GET | 列出PR |
| `POST /repos/{owner}/{repo}/pulls` | POST | 创建PR |
| `GET /repos/{owner}/{repo}/pulls/{number}` | GET | 获取单个PR |
| `PATCH /repos/{owner}/{repo}/pulls/{number}` | PATCH | 更新PR |
| `PUT /repos/{owner}/{repo}/pulls/{number}/merge` | PUT | 合并PR |
| `GET /repos/{owner}/{repo}/pulls/{number}/merge` | GET | 检查PR是否已合并 |

### 6.2 PR 评论与审查

| 端点 | 方法 | 描述 |
|------|------|------|
| `GET /repos/{owner}/{repo}/pulls/{number}/comments` | GET | 获取PR评论 |
| `POST /repos/{owner}/{repo}/pulls/{number}/comments` | POST | 创建PR评论 |
| `GET /repos/{owner}/{repo}/pulls/comments/{id}` | GET | 获取特定评论 |
| `PATCH /repos/{owner}/{repo}/pulls/comments/{id}` | PATCH | 编辑评论 |
| `DELETE /repos/{owner}/{repo}/pulls/comments/{id}` | DELETE | 删除评论 |
| `POST /repos/{owner}/{repo}/pulls/{number}/review` | POST | PR审查 |

### 6.3 PR 文件与提交

| 端点 | 方法 | 描述 |
|------|------|------|
| `GET /repos/{owner}/{repo}/pulls/{number}/files` | GET | PR文件列表 |
| `GET /repos/{owner}/{repo}/pulls/{number}/files.json` | GET | PR文件变更 |
| `GET /repos/{owner}/{repo}/pulls/{number}/commits` | GET | PR提交列表 |
| `GET /repos/{owner}/{repo}/pulls/{number}/issues` | GET | PR关联的Issues |

### 6.4 PR 标签与指派

| 端点 | 方法 | 描述 |
|------|------|------|
| `GET /repos/{owner}/{repo}/pulls/{number}/labels` | GET | 获取PR标签 |
| `POST /repos/{owner}/{repo}/pulls/{number}/labels` | POST | 添加PR标签 |
| `PUT /repos/{owner}/{repo}/pulls/{number}/labels` | PUT | 替换所有PR标签 |
| `DELETE /repos/{owner}/{repo}/pulls/{number}/labels/{name}` | DELETE | 删除PR标签 |
| `POST /repos/{owner}/{repo}/pulls/{number}/assignees` | POST | 指派审查者 |
| `DELETE /repos/{owner}/{repo}/pulls/{number}/assignees` | DELETE | 移除审查者 |
| `PATCH /repos/{owner}/{repo}/pulls/{number}/assignees` | PATCH | 重置审查状态 |
| `POST /repos/{owner}/{repo}/pulls/{number}/testers` | POST | 指派测试者 |
| `PATCH /repos/{owner}/{repo}/pulls/{number}/testers` | PATCH | 重置测试状态 |
| `POST /repos/{owner}/{repo}/pulls/{number}/test` | POST | 处理PR测试 |

### 6.5 PR 日志

| 端点 | 方法 | 描述 |
|------|------|------|
| `GET /repos/{owner}/{repo}/pulls/{number}/operate_logs` | GET | 获取PR操作日志 |
| `GET /enterprises/{enterprise}/pull_requests` | GET | 企业PR列表 |
| `GET /org/{org}/pull_requests` | GET | 组织PR列表 |
| `GET /enterprises/{enterprise}/issues/{number}/pull_requests` | GET | Issue关联的PR |

---

## 7. Webhook 管理

| 端点 | 方法 | 描述 |
|------|------|------|
| `GET /repos/{owner}/{repo}/hooks` | GET | 列出Webhooks |
| `POST /repos/{owner}/{repo}/hooks` | POST | 创建Webhook |
| `GET /repos/{owner}/{repo}/hooks/{id}` | GET | 获取单个Webhook |
| `PATCH /repos/{owner}/{repo}/hooks/{id}` | PATCH | 更新Webhook |
| `DELETE /repos/{owner}/{repo}/hooks/{id}` | DELETE | 删除Webhook |
| `POST /repos/{owner}/{repo}/hooks/{id}/tests` | POST | 测试Webhook |

**Webhook 事件类型:**
- `push_events` - 推送事件
- `tag_push_events` - 标签推送事件
- `issues_events` - Issue事件
- `note_events` - 评论事件
- `merge_requests_events` - 合并请求事件

---

## 8. Release 管理

| 端点 | 方法 | 描述 |
|------|------|------|
| `GET /repos/{owner}/{repo}/releases` | GET | 列出Releases |
| `GET /repos/{owner}/{repo}/releases/tags/{tag}` | GET | 根据Tag获取Release |
| `PATCH /repos/{owner}/{repo}/releases/{id}` | PATCH | 更新Release |

**注意:** 创建Release可能通过Tag或独立端点

---

## 9. 标签管理

| 端点 | 方法 | 描述 |
|------|------|------|
| `GET /repos/{owner}/{repo}/releases/tags/{tag}` | GET | 获取Tag关联的Release |

**注意:** 标签创建可能通过Git操作或Release API

---

## 10. 里程碑管理

| 端点 | 方法 | 描述 |
|------|------|------|
| `PATCH /repos/{owner}/{repo}/milestones/{number}` | PATCH | 更新里程碑 |

**在PR/Issue中使用:**
- 创建/更新PR时可指定 `milestone_number`
- Issue接口支持 `milestone` 参数

---

## 11. 提交与文件

### 11.1 提交

| 端点 | 方法 | 描述 |
|------|------|------|
| `GET /repos/{owner}/{repo}/pulls/{number}/commits` | GET | 获取PR的提交 |

### 11.2 原始文件

| 端点 | 方法 | 描述 |
|------|------|------|
| `GET /{owner}/{repo}/raw/{head_sha}/{name}` | GET | 获取文件内容 |

---

## 12. 搜索

| 端点 | 方法 | 描述 |
|------|------|------|
| `GET /search/issues` | GET | 搜索Issues |
| `GET /search/repositories` | GET | 搜索仓库 |

**搜索参数:**
- `q` - 搜索关键字（必填）
- `access_token` - 授权令牌（必填）
- `page` - 页码（最大100）
- `per_page` - 每页数量（最大50）
- `sort` - 排序字段
- `order` - 排序方向
- `repo` - 仓库路径
- `state` - 状态过滤
- `language` - 语言过滤

---

## 13. 通知

| 端点 | 方法 | 描述 |
|------|------|------|
| `GET /repos/{owner}/{repo}/notifications` | GET | 列出仓库通知 |

**参数:**
- `unread` - 未读过滤
- `type` - 类型过滤
- `since` - 开始时间
- `before` - 结束时间
- `ids` - ID列表

---

## 14. 组织与企业

### 14.1 组织

| 端点 | 方法 | 描述 |
|------|------|------|
| `GET /orgs/{org}` | GET | 获取组织信息 |
| `POST /orgs/{org}/repos` | POST | 创建组织仓库 |
| `POST /orgs/{org}/memberships/{username}` | POST | 邀请组织成员 |
| `GET /org/{org}/pull_requests` | GET | 组织PR列表 |
| `POST /org/{org}/repo/{repo}/status` | PUT | 归档/取消归档仓库 |
| `POST /org/{org}/projects/{repo}/transfer` | POST | 转移仓库 |

### 14.2 企业

| 端点 | 方法 | 描述 |
|------|------|------|
| `GET /enterprises/{enterprise}/issues` | GET | 企业Issues |
| `GET /enterprises/{enterprise}/issues/{number}` | GET | 企业Issue详情 |
| `GET /enterprises/{enterprise}/issues/{number}/comments` | GET | 企业Issue评论 |
| `GET /enterprises/{enterprise}/issues/{issue_id}/labels` | GET | 企业Issue标签 |
| `GET /enterprises/{enterprise}/pull_requests` | GET | 企业PR列表 |
| `GET /enterprises/{enterprise}/issue_statuses` | GET | 企业Issue状态 |

---

## 15. 成员与权限

| 端点 | 方法 | 描述 |
|------|------|------|
| `GET /repos/{owner}/{repo}/collaborators/self-permission` | GET | 检查当前用户权限 |
| `PUT /repos/{owner}/{repo}/members/{username}` | PUT | 更新成员角色 |
| `GET /repos/{owner}/{repo}/customized_roles` | GET | 获取自定义角色 |

**权限级别:** `pull`, `push`, `admin`, `customized`

---

## 16. 代码审查设置

| 端点 | 方法 | 描述 |
|------|------|------|
| `PUT /repos/{owner}/{repo}/reviewer` | PUT | 修改代码审查设置 |

---

## 17. 可扩展功能建议

基于以上API清单，以下是建议扩展的功能模块：

### 高优先级扩展

| 功能模块 | 涉及API | 使用场景 |
|---------|--------|---------|
| **Issue管理** | Issues CRUD + 评论 + 标签 | 创建bug报告、任务跟踪、代码审查反馈 |
| **Pull Request管理** | PR CRUD + 评论 + 合并 | 代码审查流程、自动化合并 |
| **Webhook管理** | Webhooks CRUD + 测试 | CI/CD集成、自动化工作流 |
| **分支保护** | 保护规则CRUD | 代码质量保障、防止误推送 |
| **Release管理** | Releases + Tags | 版本发布、变更日志 |

### 中优先级扩展

| 功能模块 | 涉及API | 使用场景 |
|---------|--------|---------|
| **仓库文件操作** | Contents CRUD | 远程编辑配置文件、自动化文档更新 |
| **仓库统计** | Contributors + Languages | 项目健康度分析、贡献者报告 |
| **通知管理** | Notifications | 未读消息提醒、工作流状态跟踪 |
| **成员管理** | Members + Permissions | 团队协作、权限审计 |

### 低优先级扩展

| 功能模块 | 涉及API | 使用场景 |
|---------|--------|---------|
| **搜索** | Search issues/repos | 跨仓库查询、知识检索 |
| **里程碑** | Milestones | 项目规划、迭代管理 |
| **Fork管理** | Forks | 代码复用、贡献流程 |
| **组织管理** | Orgs + Enterprises | 企业级部署、团队管理 |

---

## 当前Skill已使用 vs 可扩展对比

| 功能域 | 已使用 | 可扩展 |
|--------|--------|--------|
| 用户认证 | `GET /user`, `GET /user/keys`, `POST /user/keys` | `DELETE /user/keys`, `GET /user/starred`, `GET /user/repos`, `GET /user/issues` |
| 仓库管理 | `POST /user/repos` | 仓库CRUD、Fork、转移、归档、设置、统计 |
| 分支管理 | - | 分支CRUD、保护规则 |
| Issue管理 | - | 完整CRUD、评论、标签、日志 |
| Pull Request | - | 完整CRUD、评论、审查、合并、标签 |
| Webhook | - | 完整CRUD、测试 |
| Release | - | 列出、获取、更新 |
| 文件操作 | - | 内容CRUD、上传、原始内容 |
| 搜索 | - | Issues、仓库搜索 |
| 通知 | - | 仓库通知 |
| 成员 | - | 权限检查、角色管理 |
