## Context

现状（见 proposal 与已归档设计）：单体 Flask，登录态用 Flask 签名 Cookie 会话（仅存 user_id）；`before_request` 回库装载 `g.user`；`login_required` 对页面 302 跳登录、对接口 401；`role_required` 判 403；材料读写全部收敛在 `materials/repository.py` 做班级过滤；页面为 Jinja2 服务端渲染（`g.user`、flash 消息、HTML 表单、multipart 上传、`<a href>` 直接下载）；测试通过表单登录 + Cookie 罐工作。约束延续：单容器、单数据卷、零前端构建、纯 Python 依赖优先、Windows 课堂可复现、`SECRET_KEY` 生产缺失即拒绝启动。

用户已明确选择**纯 Bearer 请求头**方式（非 Cookie 承载 JWT），因此前端必须改为 JS 调 API 的形态。另注意：在途变更 `add-material-preview-and-kb-search` 按 SSR 页面与会话设计，本变更不修改其工件，但实施顺序与后续修订必须协调（见 Decision 9）。

## Goals / Non-Goals

**Goals:**

- 完全移除服务端会话：不写不读任何会话 Cookie，受保护接口只认 `Authorization: Bearer <JWT>`，失败一律 401 JSON（无 302）。
- 受保护能力全部成为同源 JSON API（`/api/*`）；前端为零构建 vanilla JS 静态外壳，登录拿令牌存 localStorage，统一封装带令牌调用。
- 现有安全行为不回退：学生 403、跨班 404、上传双白名单/大小限制、物理文件保护、每请求回库、密码加盐哈希、健康检查公开、种子幂等。
- 无数据库结构变更、无数据迁移；回滚只需回退代码与镜像。

**Non-Goals（本期不做）:**

- 刷新令牌（refresh token）、令牌吊销名单/黑名单、强制下线、"记住我"、改密后全局失效。
- Cookie 承载 JWT（用户已排除）；第三方 IdP/SSO/OAuth2。
- 前端框架（Vue/React）、Node 构建链、独立前端仓库/独立部署单元、CORS 跨域支持。
- 密码哈希算法、班级/材料数据模型、文件存储布局、允许类型清单的变更。
- 在途知识库变更（预览/检索）的适配修订（本变更后用 `/opsx-update` 单独处理）。

## Decisions

### 1. 总体形态：同源 JSON API + 公开静态外壳

- Flask 同源同时提供静态外壳与 `/api` JSON 接口：不引入跨域、不新增服务，docker-compose/卷/健康检查不变。
- 公开页面（不含任何业务数据）：`GET /login`、`GET /register`、`GET /`（应用外壳），由 Flask 发送静态 HTML；`/static/**` 放 JS/CSS。外壳可以仍是 Jinja 模板文件，但渲染时**不注入** `g.user`、材料或任何私有数据。
- 数据全部在 `/api` 下：

| 方法/路径 | 鉴权 | 说明 |
|---|---|---|
| POST /api/auth/register | 公开 | 注册；201 JSON，不签发令牌 |
| POST /api/auth/login | 公开 | 登录；200 返回 access_token |
| GET /api/auth/me | Bearer | 当前用户信息（外壳引导角色视图） |
| GET /api/materials | Bearer | 本班材料 JSON 列表（倒序） |
| GET /api/materials/&lt;id&gt; | Bearer | 本班材料详情 JSON |
| POST /api/materials/upload | Bearer + 教师 | multipart 上传 |
| GET /api/materials/&lt;id&gt;/download | Bearer | 文件流响应 |
| GET /health | 公开 | 不变 |
| GET /、/login、/register、/static/* | 公开 | 外壳与静态资源，无私有数据 |

- `/api` 下任何未命中或业务错误均返回 JSON；对外壳路由的未认证访问不做重定向（外壳本身公开）。
- 备选：前后端分端口/分仓 → 部署与课堂复现成本翻倍，否决；继续 SSR + Cookie 承载 JWT → 用户已明确否决。

### 2. JWT 结构与签发（PyJWT, HS256）

- 依赖新增 `PyJWT>=2.8,<3`（纯 Python）。新增 `app/auth/tokens.py`：`issue_access_token(user) -> str`、`decode_token(token) -> dict`（定义 `TokenError/TokenExpired` 等内部异常）。
- 声明：`sub=str(user.id)`、`iat`、`exp`，`typ` 固定为 access；**不放角色与班级**（每请求回库为准，声明只做身份指针）。
- 算法固定 `HS256`，解码显式 `algorithms=["HS256"]` 防算法混淆；密钥复用 `SECRET_KEY`（继续 fail-closed，不新增第二个必填密钥）。
- 有效期 `JWT_ACCESS_TTL_MINUTES`（env，默认 480 分钟=8 小时一个教学日）；登录响应返回 `access_token`、`token_type="Bearer"`、`expires_in`（秒）与用户基本信息。
- 只在登录成功时签发；注册成功返回 201 但不签发（保持"注册后显式登录"语义）。
- 备选：RS256 非对称密钥 → 单体无多方验签需求，徒增密钥管理，否决；在令牌中放 role/class → 变更后令牌内身份陈旧，违背"数据库为准"，否决。

### 3. 鉴权层重构：只认 Bearer 头，失败只回 401

- `decorators.py` 重写：`_bearer_token()` 只从 `Authorization: Bearer <token>` 取令牌——无头、方案错误、空令牌、查询参数携带均视为未认证。
- `login_required` 不再有页面/接口分支与 302：令牌缺失→401 `unauthorized`；过期→401 `token_expired`；签名非法/声明缺失/算法异常/畸形→401 `token_invalid`；验签通过但回库无此用户→401 `user_not_found`。全部为 JSON，不执行后续业务。
- 鉴权装饰器完成"验签 → 取 sub → 回库装载 `g.user`"；`role_required` 与 `get_scoped_or_404` 语义不变（403/404）。
- 移除 `app/__init__.py` 中基于 `session` 的 `before_request` 与全部 `session.*`、`flash` 用法（登录/注册错误改为 JSON 响应体，前端自行渲染）；删除 `SESSION_COOKIE_*` 配置。`SECRET_KEY` 保留作 JWT 签名密钥。
- Bearer 头不会被浏览器跨站自动携带，原有 Cookie 模式下的 CSRF 面随之消除。

### 4. 材料接口 JSON 化（业务规则零改动）

- 列表/详情改返回 JSON：列表 `{items:[...]}`，每条含 id、original_name、mime_type、size_bytes、uploader（用户名）、class 归属仅服务端过滤、created_at（ISO8601 字符串）；倒序、上传立即可见、跨班不可见规则不变。
- 上传路由路径移至 `/api/materials/upload`，仍是单字段 multipart：认证→教师角色→双白名单+大小校验→落盘→写库（写库失败删文件补偿）；400/413/401/403 语义不变，成功 201 JSON。
- 下载保留 `send_file(as_attachment=True)`，但授权来自 Bearer 头；物理文件缺失仍 500。前端不能再用裸 `<a href>`，改为带令牌 fetch 取 blob（20MB 上限内内存可接受）。
- repository/storage/models 不动；归属仍只取 `g.user.id/class_id`。

### 5. 前端：零构建 vanilla JS

```
app/static/
  login.html  register.html  index.html
  css/app.css
  js/api.js          # TOKEN_KEY、authFetch、401 统一处理、JSON 错误解析
  js/auth.js         # 登录/注册页提交与提示
  js/materials.js    # /me 引导、列表渲染、上传、下载 blob、登出
```

- 令牌存 `localStorage["campusclaw_token"]`；`authFetch(path, opts)` 自动附加头并处理 `401 → 清令牌 → location=/login`（登录页本身除外）。
- 所有用户/材料文本只用 `textContent`/`createElement` 渲染，**禁止 `innerHTML` 插入不可信内容**；上传用 `FormData`；下载用 blob+`URL.createObjectURL`+临时锚点+`revokeObjectURL`。
- 外壳启动调 `/api/auth/me`：401 则显示登录引导；成功则按 role 决定是否显示上传区（仅体验差异，不是安全边界）。
- 刷新/直接打开 `/`：外壳公开可得，JS 重新据令牌引导，深链不依赖服务端路由。
- 外壳响应附带限制性 CSP 头（`default-src 'self'`、禁内联脚本/第三方源），降低 localStorage 令牌被 XSS 窃取的面。
- 备选：令牌只存内存（刷新即失）→ 课堂体验差，否决；引入框架/构建链 → Non-Goal。

### 6. 配置与环境

- `config.py` 删除会话 Cookie 配置项；新增 `JWT_ACCESS_TTL_MINUTES = int(os.environ.get("JWT_ACCESS_TTL_MINUTES", "480"))`；`SECRET_KEY` 逻辑不变。
- `.env.example`：SECRET_KEY 注释改为"JWT 签名密钥（必填）"，新增 `JWT_ACCESS_TTL_MINUTES=480` 示例。
- 无 schema 变更：`flask init-db`、seed 逻辑与内部调用（不经 HTTP）保持不变。

### 7. HTTP 语义对照（变更后）

| 情形 | 旧 | 新 |
|---|---|---|
| 未认证访问受保护页面 | 302 → /login | 不存在受保护页面；外壳 200 但无数据 |
| 未认证/坏令牌调数据接口 | 401（Cookie） | 401 JSON（无 Bearer/坏 Bearer） |
| 过期/篡改令牌 | 会话失效→重定向/401 | 一律 401 JSON，前端回登录页 |
| 学生调上传 | 403 | 403（不变） |
| 跨班详情/下载 | 404 | 404（不变） |
| 登录成功 | Set-Cookie + 302 | 200 JSON 令牌，无 Set-Cookie |
| 登出 | POST 清会话 | 客户端删 localStorage 令牌，无服务端接口 |

### 8. 测试改造（pytest + test client）

- `conftest.py`：新增 `login_token(client, username, password)` 调 `/api/auth/login` 取令牌；提供 `auth_headers(token)`；`upload`/下载等辅助统一注入 Authorization。
- 重写断言：未认证全部期望 401 JSON（删除 next 重定向用例）；注册 201 且无令牌；登录 200 含 access_token/expires_in 且无 Set-Cookie；`/me` 返回本人信息；材料列表字段以 JSON 断言；下载带头字节一致、无头 401；学生 403、跨班 404、伪装角色字段仍 403。
- 令牌专项（`test_auth.py` 新用例）：过期令牌（手工构造 past-exp 或极短 TTL）、篡改签名、`alg:none`/算法混淆、畸形头、令牌放查询串、用户被删后 401。
- 外壳用例：`/`、`/login`、`/register` 无令牌 200 且响应体不含材料数据；静态 JS 可达。
- 保持不变：密码哈希用例、安全存储用例、`/health`、seed 幂等、SQLite pragma、413。

### 9. 与在途知识库变更的协调

- 本变更不编辑 `add-material-preview-and-kb-search` 的工件。其 design/tasks 中"SSR 预览页、`/kb` HTML 表单、`g.user` 会话、未登录 302、Jinja 溯源锚点"等假设在 JWT 架构下失效。
- 实施顺序：先 apply 本变更；随后对知识库变更执行 `/opsx-update`：预览/检索改为 `/api` JSON 接口 + 前端 JS 渲染（md 预览改为接口返回消毒后 HTML 由前端受控注入，或返回原文由前端渲染），溯源改为前端路由/锚点，鉴权与 401 语义按本设计改写。

## Risks / Trade-offs

- [localStorage 令牌可被 XSS 读取] → 前端只用 textContent/DOM API 渲染、无第三方 JS、外壳加 CSP；材料内容不进入 HTML 拼接；未来 md 预览须在 KB 修订中坚持服务端 bleach 消毒。
- [无服务端吊销，登出/改密后旧令牌到期前仍有效] → 8 小时短有效期 + 每请求回库（删除用户立即失效）；明确为本期取舍，日后再加刷新令牌/吊销版本号。
- [Bearer 令牌需 HTTPS 防窃听] → 生产经反向代理启用 HTTPS（部署说明）；课堂 compose 明文仅本地回环。
- [文件下载不能用直链，前端需 fetch blob，大文件占内存] → 20MB 上限内可接受；教学规模无需流式授权改造。
- [两个在途变更架构假设冲突] → 已约定先后顺序与 `/opsx-update` 修订点；若先实施 KB 再实施 JWT，KB 的页面任务将返工，故禁止乱序。
- [改造面覆盖全部受保护测试] → 测试与代码同批改、同 PR 验收；无 schema/数据变更，回滚成本低。

## Migration Plan

1. 安装 PyJWT；新增 tokens 模块、重写装饰器与 auth 路由、材料路由 JSON 化、移除 session/flash 与旧模板。
2. 新增 static 外壳与 JS（api/auth/materials）；接好登录、列表、上传、下载、登出、/me。
3. 改造测试夹具与全部用例，pytest 全绿（含令牌专项与外壳无数据断言）。
4. 容器重建（依赖变更，无数据卷变更）；`docker compose up` 后浏览器走查：登录存令牌→列表→教师上传→学生 403→下载→跨班 404→登出→旧令牌 401。
5. 回滚：直接回退代码/镜像即可，无数据库迁移；回滚后旧 JWT 自然失效，用户按 Cookie 模式重新登录。
6. 后续：对 `add-material-preview-and-kb-search` 执行 `/opsx-update` 对齐新架构。

## Open Questions

无。已固化的假设：HS256 且复用 SECRET_KEY；TTL 默认 480 分钟；令牌存 localStorage；无刷新令牌与吊销；注册不自动登录；同源静态外壳、无 CORS；路径统一 `/api` 前缀；无数据库结构变更。
