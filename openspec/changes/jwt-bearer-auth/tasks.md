# Tasks

## 1. 依赖与配置

- [x] 1.1 在 requirements.txt 增加 `PyJWT>=2.8,<3` 并在 venv 安装验证（`python -c "import jwt"` 成功）
- [x] 1.2 修改 `app/config.py`：删除 SESSION_COOKIE_* 配置；新增 `JWT_ACCESS_TTL_MINUTES`（env 可覆盖，默认 480）、固定算法常量 HS256；保留 SECRET_KEY fail-closed 逻辑；用配置加载测试断言默认 TTL 与生产缺密钥启动报错仍成立
- [x] 1.3 更新 `.env.example`：SECRET_KEY 注释改为 JWT 签名密钥（生产必填），新增 `JWT_ACCESS_TTL_MINUTES=480` 示例；确认仅含占位符无真实密钥

## 2. JWT 核心模块

- [x] 2.1 新增 `app/auth/tokens.py`：`issue_access_token(user)`（sub/iat/exp，HS256，SECRET_KEY）与 `decode_token(token)`（固定 algorithms=["HS256"]，区分过期/非法/声明缺失异常）；单元测试验证签发后可解、sub 正确、exp-iat=配置 TTL
- [x] 2.2 令牌异常专项测试：篡改签名、`alg:none`/算法混淆、过期令牌、畸形字符串分别抛出对应异常类型（供装饰器映射 401 错误码）

## 3. 鉴权层与应用工厂改造

- [x] 3.1 重写 `app/auth/decorators.py`：新增 Bearer 头提取助手（只接受 `Authorization: Bearer`，拒绝无头/空令牌/查询参数）；`login_required` 统一为 JSON 401（unauthorized/token_expired/token_invalid/user_not_found 四种错误码），验签后按 sub 回库装载 `g.user`，查无此人 401；`role_required` 保持 403 语义；测试覆盖四种 401 与查询参数不被接受
- [x] 3.2 修改 `app/__init__.py`：移除基于 session 的 before_request、全部 session/flash 依赖与 SESSION_COOKIE 配置使用；蓝图按 `/api/auth`、`/api` 前缀注册；保留 /health 与 413 JSON；grep 验证应用代码中不再出现 `session[`/`flash(`/`SESSION_COOKIE`
- [x] 3.3 为公开外壳响应增加限制性 CSP 头（default-src 'self'，禁第三方与内联脚本）；测试断言外壳响应含该头

## 4. 认证 JSON 接口

- [x] 4.1 重写 `app/auth/routes.py`：`POST /api/auth/register`（公开，成功 201 JSON 不签发令牌；重复用户名/无效班级/短密码返回 400 JSON 错误明细）；测试覆盖成功 201 且响应无 access_token、各类 400、成功后可登录
- [x] 4.2 实现 `POST /api/auth/login`：正确凭据返回 200 `{access_token, token_type:"Bearer", expires_in, user:{username,role,class...}}` 且不 Set-Cookie；错误凭据 401 统一提示；测试断言响应结构、无 Set-Cookie、401 文案不区分用户不存在
- [x] 4.3 实现 `GET /api/auth/me`（Bearer）：返回当前用户 username/role/class；无令牌 401、用户被删后 401；前端外壳据此引导角色视图

## 5. 材料 JSON 接口

- [x] 5.1 将材料路由迁移到 `/api` 前缀并 JSON 化：`GET /api/materials` 返回 `{items:[...]}`（id、original_name、mime_type、size_bytes、uploader 用户名、created_at ISO 字符串，倒序）；`GET /api/materials/<id>` 返回详情 JSON；测试断言字段、倒序、无令牌 401、跨班 404
- [x] 5.2 上传接口迁移为 `POST /api/materials/upload`（Bearer + 教师，multipart）：保持双白名单/大小/落盘/写库补偿/400/403/413 语义，成功 201 JSON；测试验证学生 403、非法类型 400、超限 413、写库失败无孤儿文件
- [x] 5.3 下载接口迁移为 `GET /api/materials/<id>/download`：凭 Bearer 授权的 send_file，无头 401、跨班 404、文件缺失 500、带头下载字节与文件名正确；测试逐一覆盖

## 6. 前端静态外壳（零构建 vanilla JS）

- [x] 6.1 新增公开页面 `app/static/login.html`、`register.html`、`index.html`（外壳不含任何私有数据）与 `css/app.css`；在应用工厂为 `GET /login`、`GET /register`、`GET /` 提供外壳路由；测试验证无令牌访问三页 200 且响应体不含任何材料数据
- [x] 6.2 新增 `js/api.js`：localStorage 令牌存取、`authFetch` 自动附加 Bearer、401 统一清令牌跳登录（登录页除外）、JSON 错误解析；用浏览器手工/脚本验证登录后请求自动带头、过期后跳回登录
- [x] 6.3 新增 `js/auth.js`：登录页提交调 /api/auth/login 存令牌后进入外壳；注册页提交与错误提示渲染（用 textContent，不用 innerHTML 插入接口内容）；浏览器验证登录、注册、错误提示链路
- [x] 6.4 新增 `js/materials.js`：启动调 /me 按角色显示上传区（仅体验差异）；列表渲染材料表格；上传 FormData；下载用 fetch 取 blob 后 createObjectURL 保存并 revoke；登出删除令牌回登录页；所有不可信文本经 textContent/DAM 渲染；浏览器走查完整链路
- [x] 6.5 删除旧的 Jinja 数据模板与 flash 渲染（base/login/register/materials 模板），确认无残留 url_for 页面引用与死链

## 7. 测试整体改造

- [x] 7.1 改造 `tests/conftest.py`：新增 `login_token()`（接口换令牌）与认证头辅助；upload 等夹具默认带 Bearer；运行全量 pytest 列出剩余失败点
- [x] 7.2 改写 test_auth/test_access_control/test_materials：删除 302/next 重定向断言；未认证一律 401 JSON；保留并适配学生 403、伪造 role 字段 403、跨班 404、伪装班级不生效、上传后列表立即可见、跨班列表不可见
- [x] 7.3 保持 test_security、test_foundations 绿色（健康检查措辞断言同步为"不携带 Authorization"；密码哈希、pragma、seed 幂等不变）；全量 pytest 通过

## 8. 容器化与端到端验收

- [x] 8.1 重建镜像并 `docker compose up`：确认 init-db/seed 正常、`/health` 200、无新增数据卷或 schema 变更；`docker compose exec` 内验证登录返回 JWT
- [x] 8.2 浏览器端到端走查：登录（localStorage 可见令牌、无会话 Cookie）→ 材料列表渲染 → 教师上传后立即可见 → 学生账号上传被 403 → 带令牌下载成功 → A 班账号访问 B 班 id 为 404 → 登出后接口 401 → 手工篡改/过期令牌 401；记录验收结果
- [x] 8.3 运行 `openspec validate jwt-bearer-auth --strict` 通过；在材料中登记后续动作：对在途的 add-material-preview-and-kb-search 执行 `/opsx-update`，将预览/检索对齐为 Bearer JSON API + JS 页面（已在 design.md「实施顺序」章节登记）
