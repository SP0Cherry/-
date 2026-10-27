## Why

现有认证基于 Flask 服务端签名会话 Cookie：登录态保存在服务端会话中，页面靠服务端渲染与 302 跳转保护。需要改为无状态 JWT 认证，使身份凭证以令牌形式由客户端持有、通过标准的 `Authorization: Bearer` 头呈现，从而让所有受保护能力成为可被程序化调用的 JSON API，并消除服务端会话状态。

## What Changes

- **BREAKING**：认证机制由"服务端会话 + httpOnly Cookie"替换为"服务端签发的 JWT（HS256）+ `Authorization: Bearer` 请求头"；登录接口校验凭据通过后在 JSON 响应体中签发访问令牌，系统不再写入或读取任何会话 Cookie，不再保存任何服务端会话状态。
- **BREAKING**：受保护能力全部改为 JSON API（统一置于 `/api` 前缀下，如 `/api/materials`）：未携带令牌、令牌过期、签名无效或格式错误时一律返回 `401` JSON，不再有到登录页的 302 重定向；角色不足仍为 403、跨班仍为 404。
- 前端由服务端渲染页面改为 **JS fetch 驱动的静态 HTML 外壳（零构建 vanilla JS）**：登录/注册页通过接口换取令牌并存入 localStorage；统一的 API 调用封装自动附加 Bearer 头并在 401 时跳转登录；材料列表、详情、上传（含 multipart）、下载（fetch 取 blob 后本地保存）全部改为 JS 调接口完成；外壳页面本身公开但不含任何业务数据。
- 登出改为客户端行为：删除本地令牌并回到登录页；服务端无会话可清，不设服务端登出接口。
- 令牌仅携带用户标识与时间声明（`sub/iat/exp`），角色与班级仍在每次请求时回库以数据库为准；请求体中自报的角色、班级字段依旧无效，班级数据边界规则不变。
- 令牌有效期由环境变量配置（默认 8 小时）；过期或验签失败即 401 需重新登录；本期不引入刷新令牌与服务端吊销名单（明确的范围取舍）。
- 全部测试改为令牌方式：登录换取 JWT、所有请求带 `Authorization` 头；删除 Cookie 会话与登录重定向相关断言。
- 与尚未实施的 `add-material-preview-and-kb-search` 变更存在架构冲突：后者按服务端渲染预览页、`/kb` HTML 表单与会话 `g.user` 设计；该变更的工件需在本次改造落地后修订为 JSON API + JS 页面。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `user-auth`: 登录成功由"建立服务端会话并写 Cookie"改为"签发 JWT 并在响应体返回"；登出改为客户端丢弃令牌；"受保护页面未认证重定向"改为"公开 HTML 外壳 + 受保护数据接口 Bearer 鉴权、失败一律 401"；会话安全要求改为 JWT 签名、有效期与防篡改要求。
- `access-control`: "授权判定只信任服务端会话"改为"只信任服务端签发并验签通过的 JWT 所标识的用户，且角色/班级以数据库实时记录为准"。
- `app-foundations`: 密钥配置要求的表述由"会话签名密钥"更新为"JWT 签名密钥"并新增令牌有效期环境变量；健康检查场景中"不带登录 Cookie"的措辞同步更新（行为不变：公开、200）。
- `teaching-materials`: 材料列表与详情由服务端渲染页改为经 Bearer 鉴权的 JSON 接口；文件下载改为凭 Bearer 头授权的文件响应；元数据归属依据由"会话"改为"已认证令牌对应的用户"；上传校验与跨班 404 行为不变。

## Impact

- **新依赖**：`PyJWT`（纯 Python，无原生编译负担）。
- **BREAKING 接口契约**：受保护接口迁移到 `/api/*` 且只接受 Bearer 令牌；旧的 Cookie、表单 POST 后 302、页面直出数据等用法全部失效（无外部既有调用方，测试与种子均在仓库内同步更新）。
- **代码**：重写 `app/auth/`（新增令牌签发/解析模块、Bearer 鉴权装饰器、JSON 登录注册接口）；`app/materials/routes.py` 全面 JSON 化；`app/__init__.py` 移除会话加载、改为公开 HTML 外壳路由并注册 `/api` 蓝图；新增 `app/static/` 下的 vanilla JS/CSS 与少量公开 HTML 页面；删除依赖 Jinja 数据渲染的材料模板。
- **配置**：`SECRET_KEY` 继续作为 JWT 签名密钥（生产缺失仍拒绝启动）；新增 `JWT_ACCESS_TTL_MINUTES`（默认 480）；会话 Cookie 相关配置移除。
- **测试**：`tests/conftest.py` 的登录夹具改为先调登录接口取令牌，所有受保护请求带 `Authorization`；约全部受保护接口用例的断言从"重定向/页面"改为"401/JSON/API"。
- **安全面变化**：令牌存 localStorage 带来 XSS 窃取面（缓解：前端不使用 `innerHTML` 插入不可信内容、无第三方 JS）；无服务端吊销意味着登出/改密后旧令牌在到期前理论有效（缓解：8 小时短有效期，每请求回库使被删除用户立即失效）。
- **在途变更**：`add-material-preview-and-kb-search` 的 spec/design/tasks 需在本次改造后用 `/opsx-update` 修订（预览与检索改为 API + JS），否则其任务描述与新架构不符。
