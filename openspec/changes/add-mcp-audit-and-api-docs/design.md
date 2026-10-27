## Context

见 [proposal.md](proposal.md)。当前实现的相关事实：

- MCP 工具调用有两条路径：`app/kb/service.py::_execute_tool`（问答命中技能后调用，失败不阻断问答）与 `app/mcp/routes.py::call_server_tool`（教师手动调用）。两条路径当前只把结果放进响应的 `tool_calls` 或返回体，不落库。
- `McpServer` 保存班级、名称、缓存工具与令牌；`Skill` 保存工具引用。班级边界由会话用户决定。
- 数据库通过 `flask init-db` 的 `db.create_all()` 建表，没有迁移框架；新增表会在下次启动时自动补建。
- 全局 CSP 为 `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:`，不允许内联脚本/样式；MCP 管理区仅对教师显示，由 `materials.js` 控制。
- 项目无 OpenAPI 依赖。已在本机临时环境验证 `flasgger 0.9.7.1` 可在 Flask 3.1 下导入、生成 OpenAPI 3.0.3 JSON，并在 `/flasgger_static` 同源提供 Swagger UI 资源。

## Goals / Non-Goals

**Goals:**

- 每次 MCP 工具调用尝试（含被拒绝与失败）都留下可追溯记录，且不影响主业务路径。
- 教师只能看到本班审计；学生与未认证请求被拒绝。
- OpenAPI 3 文档覆盖 MCP、技能与登录的主要接口，可在浏览器中授权后试调。
- 文档页离线可用、资源同源，不放宽其他页面的 CSP。

**Non-Goals:**

- 不审计内置 `knowledge_search`，不记录工具入参、返回正文或令牌。
- 不实现审计归档/保留期限、导出、告警或实时推送。
- 不引入完整 API 治理平台或自动生成客户端 SDK。
- 不改变现有接口的鉴权、状态码、响应结构与班级边界。
- 不把文档页做成教师专属（浏览器直接导航无法携带 Bearer 头；页面仅为静态壳，数据接口仍鉴权）。

## Decisions

### 1. 审计数据模型：独立表 + 用户名快照

新增 `McpToolCallAudit` 表：`id`、`class_id`（索引）、`user_id`（索引）、`username`（快照）、`server_name`、`tool_name`、`status`、`reason`（可空）、`created_at`（UTC，索引）。

- 保留 `username` 快照，避免用户改名前后的审计语义变化，也避免列表查询必须联表。
- 不保存令牌、调用参数与工具返回内容，降低敏感信息面；`reason` 截断到 255 字符。
- `status` 只允许 `ok`/`denied`/`error`，与问答 `meta.tool_calls` 的取值一致。

替代方案：复用问答日志或 `McpServer.last_error`。前者不是持久化记录，后者只保留最后一次错误且无法回答“谁在何时调用”。

### 2. 审计写入：集中式记录函数，失败隔离

新增 `app/mcp/audit.py::record_call(user, tool_name, server_name, status, reason=None)`：

- 自行 `db.session.add` + `commit`，异常时 `rollback` 并写 warning 日志，绝不向调用方抛出。
- 只接受已确定的调用结果；`ref` 由 `tool_name@server_name` 派生，不单独存列。

写入点：

- 问答路径：`app/kb/service.py::prepare` 在每次 `_execute_tool` 返回后调用，且仅当 `call["server"]` 非空时记录，保证一次工具尝试恰好一条；内置 `knowledge_search` 跳过。
- 手动路径：`app/mcp/routes.py::call_server_tool` 在确定响应结果后记录，包括服务器未连接、工具不在缓存、远端错误与成功。跨班/不存在的 `server_id` 返回 404，不记录（没有发生有效的本班工具调用）。
- 先记录审计再继续后续流程，确保即使聊天阶段失败也留有调用记录。

替代方案：在各 `return` 处分别记录，容易漏记；在 `MCPClient` 内记录，拿不到用户与班级。集中到调用结果处更稳妥。

### 3. 审计查询接口：教师专属、班级硬过滤、offset 分页

`GET /api/mcp/audit`：

- `@login_required` + 教师角色校验，学生 403；未认证 401。
- 查询强制 `class_id == 当前用户.class_id`，不接受任何班级参数；排序 `created_at DESC, id DESC`。
- 参数 `limit`（默认 50，范围 1–200）与 `offset`（默认 0）；额外取 `limit + 1` 条判断 `has_more`，避免 `COUNT`。
- 返回 `{"items": [...], "has_more": bool}`；`items` 含 `id`、`ref`、`tool`、`server`、`status`、`username`、`reason`、`created_at`（ISO 8601 UTC）。

替代方案：游标 `before_id`。在课程数据规模下 offset 足够，且更易在前端实现“加载更多”。

### 4. 前端审计视图：复用教师 MCP 区块

在首页现有 `#mcp-section`（仅教师显示）内追加审计表格与刷新/加载更多按钮，由 `materials.js` 在教师登录后加载首屏。列：时间、用户、工具@服务器、状态、原因；状态复用现有 `tool-ok/tool-denied/tool-error` 样式。学生不渲染该区块，天然不触发查询。

### 5. 文档技术选型：flasgger 注解 + 自建同源 Swagger UI 页面

- 依赖 `flasgger>=0.9.7,<1`，在 `create_app` 中初始化，OpenAPI 版本设为 `3.0.3`，`swagger_ui=False` 只保留注解解析与同源静态资源；通过 `specs_route="/api/openapi.json"` 暴露文档 JSON。
- 注解写在路由函数 docstring 中（YAML），覆盖：登录、MCP 服务器列表/登记/删除/连接/断开、缓存工具、`tools/call`、技能列表/上传/删除、审计查询。统一 `tags`：`auth`、`mcp`、`skills`；受保护操作声明 Bearer 安全方案。
- 自建 `app/static/docs.html` + `app/static/js/docs.js`，引用 `/flasgger_static/swagger-ui.css`、`swagger-ui-bundle.js`、`swagger-ui-standalone-preset.js` 与 `/api/openapi.json`，不使用 Google Fonts 或任何外链。页面由 `GET /api/docs` 返回静态壳。
- 为什么不直接用 flasgger 的 `/apidocs/`：其模板含内联脚本并引用 Google Fonts，会违反现有 CSP 或造成离线失败。自建页面把初始化逻辑放进同源 JS，并把 CSP 放宽限制在文档页自身。

### 6. 文档页 CSP：仅对文档路径放宽内联样式

`_security_headers` 对 `/api/docs` 响应使用 `style-src 'self' 'unsafe-inline'`（Swagger UI 会设置样式属性），`script-src` 仍保持 `'self'`。`/flasgger_static/*` 由 flasgger 以同源静态资源提供，沿用默认 CSP；其他业务页面策略完全不变。

替代方案：全局加 `'unsafe-inline'`，会削弱所有页面的 XSS 防护，拒绝。

### 7. 文档页鉴权交互

页面公开可访问，但所有受保护操作仍走 Bearer 校验。Swagger UI 的 Authorize 对话框接受令牌；由用户手动粘贴，浏览器不自动读取 localStorage，避免把令牌注入文档页面逻辑。文档内容、页面与服务端响应均不回显令牌。

## Risks / Trade-offs

- [注解与实际接口漂移] → 测试断言关键路径、方法与安全方案；实现后逐项核对注解对应的真实参数与状态码。
- [flasgger 的 Swagger 2 风格安全定义与 OpenAPI 3 渲染差异] → 实现时优先使用 `components.securitySchemes`，并在浏览器回归中确认 Authorize 按钮与 `Authorization: Bearer` 请求头生效；不生效则回退为显式 apiKey 定义并重新验证。
- [Swagger UI 仍依赖内联样式] → 仅对文档页放宽 `style-src`，浏览器回归确认无样式/脚本 CSP 阻断；脚本始终保持同源。
- [审计写入提交事务影响请求原子性] → 审计写入放在工具结果确定后、无其他待提交写操作的时点，异常回滚并降级，不影响业务返回。
- [审计记录增长] → 接口默认 50、上限 200 并支持翻页；本次不实现清理策略。
- [新增依赖增加镜像体积与构建时间] → 固定版本区间，镜像重建验证；flasgger 为纯 Python 依赖，无额外系统库。
- [手动调用与问答调用的状态语义不一致] → 统一使用 `ok/denied/error` 三态映射，测试覆盖两条路径。

## Migration Plan

1. 更新 `requirements.txt`，重建 `web` 镜像；入口 `flask init-db` 的 `db.create_all()` 自动创建审计表，现有数据无需迁移。
2. 部署后教师首次打开首页即可看到空审计列表；调用一次工具后刷新可见记录。
3. 文档端点与页面随应用启动生效，不依赖 MCP 服务器。
4. 回滚：移除路由、前端与依赖即可；审计表保留不影响旧版本运行，不做破坏性删表。
