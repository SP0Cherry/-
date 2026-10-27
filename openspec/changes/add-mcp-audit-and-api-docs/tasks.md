## 1. 审计数据模型与写入

- [x] 1.1 在 `app/models.py` 新增 `McpToolCallAudit`（班级、用户、用户名快照、服务器名、工具名、状态、原因、UTC 时间），并在 `app/__init__.py` 或模型模块导出；验证 `flask init-db` 后 `mcp_tool_call_audits` 表存在且 `class_id`、`created_at` 索引生效
- [x] 1.2 新增 `app/mcp/audit.py::record_call`，实现新增 + 提交 + 异常回滚/日志且绝不抛出；验证数据库写入失败时函数不抛异常、业务调用方仍返回原结果
- [x] 1.3 在 `app/kb/service.py::prepare` 的每次工具结果后写入审计，仅记录 `server` 非空的引用、跳过 `knowledge_search`；验证成功/未连接/远端失败三种场景各产生一条且仅一条 `ok`/`denied`/`error` 记录，问答不受影响
- [x] 1.4 在 `app/mcp/routes.py::call_server_tool` 的每个结果分支写入审计（未连接、工具不在缓存、远端错误、成功），跨班或不存在 `server_id` 的 404 不记录；验证手动调用成功与失败均可在审计中查到，且记录用户为当前教师

## 2. 教师审计查询接口与前端

- [x] 2.1 新增 `GET /api/mcp/audit`：教师专属、强制本班过滤、`created_at DESC, id DESC` 排序、`limit`（默认 50，最大 200）与 `offset` 分页、`limit+1` 计算 `has_more`，返回 `ref/tool/server/status/username/reason/created_at`；验证学生 403、未认证 401、跨班不可见、空列表 200、响应不含令牌
- [x] 2.2 在 `app/static/index.html` 教师 MCP 区块内新增审计表格（时间/用户/工具@服务器/状态/原因）与刷新、加载更多交互，`materials.js` 仅在教师登录时加载首屏；验证教师可见并可翻页、学生页面不渲染该区块
- [x] 2.3 为审计状态新增/复用可读样式（成功、拒绝、失败三种标签）；验证三种状态在页面上可区分且无控制台错误

## 3. OpenAPI 注解与 Swagger UI

- [x] 3.1 在 `requirements.txt` 增加 `flasgger>=0.9.7,<1`，在 `create_app` 中以 OpenAPI 3.0.3 初始化（`swagger_ui=False`、`specs_route="/api/openapi.json"`）；验证 `GET /api/openapi.json` 返回 200 且为合法 OpenAPI 3 JSON
- [x] 3.2 为登录、MCP 服务器列表/登记/删除/连接/断开、缓存工具、`tools/call`、技能列表/上传/删除、审计查询补充 YAML 注解（tags、Bearer 安全方案、技能上传 `multipart/form-data`、主要 401/403/404/409 响应）；验证文档包含全部目标路径、方法与安全方案
- [x] 3.3 新增 `app/static/docs.html` 与 `app/static/js/docs.js`，引用 `/flasgger_static/` 下的 Swagger UI 资源与 `/api/openapi.json`，新增 `GET /api/docs` 返回该静态壳；验证页面无任何外部域名引用、离线可加载
- [x] 3.4 在 `_security_headers` 中仅对 `/api/docs` 放宽 `style-src` 到 `'self' 'unsafe-inline'`，其余页面策略不变；验证文档页脚本仍为 `'self'`，登录/材料/问答页面响应头与变更前一致

## 4. 自动化测试

- [x] 4.1 新增审计测试：问答成功/拒绝/失败、手动调用、内置检索不记录、审计写入失败隔离、教师/学生/未认证、班级隔离、分页、字段与令牌断言；验证新增测试全部通过
- [x] 4.2 新增文档测试：`/api/openapi.json` 含目标路径与 Bearer 方案、技能上传为 multipart、无令牌与技能正文；`/api/docs` 返回 200 且 HTML 不含外部域名；文档页与其他页面 CSP 断言
- [x] 4.3 运行全量 `pytest`；验证既有 168 个测试与新增测试全部通过，无回归

## 5. Compose 与浏览器验证

- [x] 5.1 重建并启动 Compose，确认 `flask init-db` 自动建审计表、种子与既有接口正常；验证健康检查 200
- [x] 5.2 教师登录触发一次成功调用与一次断开后的拒绝调用，确认首页审计按时间倒序显示状态、用户与时间；学生账号确认审计区块不可见且接口返回 403
- [x] 5.3 浏览器打开 `/api/docs`，确认 Swagger UI 正常渲染、无外部请求与 CSP 阻断；填入教师令牌授权后试调连接服务器、查看工具、上传技能，确认 200 与数据可见；用学生令牌试调技能上传/审计查询确认 403
- [x] 5.4 浏览器回归登录、检索、流式问答、技能管理、MCP 管理与审计页面，确认无控制台错误、无既有功能回归；同时确认文档页与接口响应均不出现令牌明文
