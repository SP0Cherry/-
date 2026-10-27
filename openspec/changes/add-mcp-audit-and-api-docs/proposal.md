## Why

当前 MCP 工具调用只体现在单次问答的流式 `meta.tool_calls` 中，教师无法在事后查看本班谁在什么时候调用了哪个 `工具@服务器`、是成功还是被拒绝，出现越权或故障时缺少可追溯证据。同时，MCP 服务器、工具调用与技能管理接口只有零散的前端实现与文字说明，缺少可浏览、可试调的接口文档，联调与课堂演示成本高。

## What Changes

- 新增班级级 MCP 工具调用审计：每次 MCP `tools/call` 尝试（来自学生问答命中技能，或教师在前端手动调用）都记录 `工具@服务器`、状态（`ok`/`denied`/`error`）、操作用户、时间与可读原因；内置 `knowledge_search` 不计入 MCP 审计。
- 新增教师专属审计查询接口与前端审计列表：只返回本班记录，按时间倒序，支持分页；学生访问返回 403，跨班数据不可见，任何响应都不包含服务器令牌。
- 为 MCP 相关接口（服务器登记/连接/断开/删除、工具清单、`tools/call`、审计查询）与技能管理接口（列表/上传/删除）、登录接口补充 OpenAPI 注解，生成 OpenAPI 3 文档。
- 新增浏览器可打开的 Swagger UI 页面：资源全部同源、离线可用，支持填入 Bearer 令牌后试调 connect、tools、技能保存等主要接口；文档页面与 API 的现有 CSP 策略保持兼容。
- 审计写入失败必须被隔离，不得影响问答或手动工具调用的主路径。

## Capabilities

### New Capabilities

- `mcp-audit`: 班级级 MCP 工具调用审计的记录范围、字段、写入时机、教师查询授权与分页查询行为。
- `api-docs`: OpenAPI 3 文档的覆盖范围、Bearer 鉴权声明、Swagger UI 页面可访问性与 CSP/同源资源约束、敏感信息不进入文档。

### Modified Capabilities

<!-- 无：本次只新增能力，不改变既有 capability 的 Requirement。 -->

## Impact

- 数据模型：新增 MCP 工具调用审计表；`flask init-db` 的 `db.create_all()` 会为现有数据库补建该表，无需数据迁移。
- 后端：`app/models.py`、`app/mcp/`（审计服务与查询接口、手动调用记录）、`app/kb/service.py`（技能工具执行记录）、`app/__init__.py`（Swagger 初始化与文档页 CSP）、`requirements.txt`（引入 `flasgger`）。
- 前端：首页新增教师可见的审计表格与刷新交互；新增 Swagger UI 文档页与初始化脚本，复用同源静态资源。
- 测试：新增审计记录/查询/隔离、OpenAPI 文档内容与页面可达性测试；浏览器回归需覆盖教师查看审计、学生不可见、Swagger 页面试调。
- 依赖：`flasgger`（已在本机 Flask 3.1 环境验证可导入并生成 OpenAPI 3.0.3 文档与本地 Swagger UI 资源）。
- 不改变既有问答、检索、技能、MCP 管理接口的鉴权与业务语义。
