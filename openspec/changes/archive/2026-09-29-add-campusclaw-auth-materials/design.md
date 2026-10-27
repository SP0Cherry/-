## Context

仓库目前为绿地：只有 OpenSpec 脚手架，没有任何应用代码、依赖或数据模型。技术栈确定为 Python Flask（应用工厂 + Blueprint + Jinja2 服务端渲染）+ SQLAlchemy + SQLite，材料文件存本地磁盘，运行方式为 Docker Compose，对外提供 `GET /health`。本站用于教学，核心诉求是让"认证、角色、班级边界在服务端被强制执行"成为可直接演示、可测试的行为（动机见 proposal.md，外部行为契约见四份 spec）。

## Goals / Non-Goals

**Goals:**

- 所有受保护页面与接口经过统一的服务端鉴权层：页面重定向、接口 401/403、跨班 404 语义一致。
- 班级过滤收敛在服务端数据访问函数中，业务代码无法构造"不带班级条件"的材料查询。
- 密码只以加盐哈希形态存在；会话密钥只来自服务端环境变量，缺失即拒绝启动。
- 上传文件不落入任何可公开静态访问的目录，下载一律经过鉴权。
- `docker compose up` 一条命令完成建表、种子与启动；种子可重复执行。
- 种子数据可一键复现四个核心场景：未登录被重定向/401、学生上传 403、A 班访问 B 班材料 404、教师上传后本班列表立即可见。

**Non-Goals（本期不做）:**

- 知识库检索问答、对话助手、作业提交与批改、SSO 与生产 HA（详见 proposal.md 的 Non-goals）。
- 管理员后台、账号审批、邀请码、邮箱验证、找回密码。
- 一师多班、用户跨班/换班（本期每人固定归属一个班级）。
- 材料在线预览、编辑、删除；对象存储；病毒扫描；限流与登录失败锁定（仅保留基本输入校验）。

## Decisions

### 1. 总体结构：单体 Flask 应用，Blueprint 分层

- 应用工厂 `create_app(config)`；Blueprint：`auth`（注册/登录/登出）、`materials`（列表页、上传、下载）、`health`。
- 目录建议：`app/__init__.py`（工厂）、`config.py`（环境变量配置）、`models.py`、`auth/`、`materials/`（含 `repository.py` 数据访问层）、`templates/`、`cli.py`（init-db / seed）、`wsgi.py`（gunicorn 入口）。
- 页面为 Jinja2 服务端渲染，不引入前端框架；前端按角色隐藏上传入口仅是体验优化，不是安全边界。
- 备选：前后端分离（Vue/React + API）——部署单元与样板翻倍，对教学演示无收益，否决。

### 2. 数据模型（SQLAlchemy / SQLite）

- `Class`：`id`、`name`（唯一，如 "A班"/"B班"）。
- `User`：`id`、`username`（唯一）、`password_hash`、`role`（字符串枚举 `teacher` | `student`）、`class_id`（非空外键 → `classes.id`）。
- `Material`：`id`、`original_name`、`stored_key`（服务端生成的存储相对路径，唯一）、`mime_type`、`size_bytes`、`uploader_id`（外键 → users）、`class_id`（非空外键 → classes）、`created_at`；索引 `(class_id, created_at)` 支撑本班列表倒序查询。
- SQLite 开启外键约束（连接事件里执行 `PRAGMA foreign_keys=ON`）与 WAL；建表用 `flask init-db`（`db.create_all()`），教学项目不引入 Alembic 迁移框架。

### 3. 密码与会话

- **密码哈希**：使用 Werkzeug 的 `generate_password_hash(password, method="pbkdf2:sha256", salt_length=16)` 与 `check_password_hash`——每用户独立随机盐、纯 Python 无原生编译依赖（Windows 课堂环境友好）。注册与种子统一走该函数；代码中不得出现任何"保存明文密码"的分支，日志中禁止打印密码字段。
- **会话**：使用 Flask 内置签名 Cookie 会话（itsdangerous HMAC 签名，内容不保密但不可篡改）；会话中只存 `user_id`，每个请求 `before_request` 回库加载用户到 `g.user`，角色与班级始终以数据库为准。
- Cookie 属性：`HttpOnly=True`、`SameSite=Lax`、生产环境 `Secure=True`；登出即 `session.clear()`。
- **密钥**：`SECRET_KEY` 只从环境变量读取；`FLASK_ENV=production` 下缺失或为空时在工厂中抛错终止启动（fail closed）。`.env.example` 只放占位说明，真实值放 `.env`（加入 `.gitignore`）并由 Compose 的 `env_file`/`environment` 注入，不写进镜像。
- 备选：bcrypt/argon2——需原生编译，课堂机器环境差异大，否决；服务端会话表（Redis/DB）——本期无强失效需求，过重，否决。

### 4. 服务端访问控制的落点

- `login_required` 装饰器统一处理未认证：
  - 页面请求（Accept: text/html 或浏览器导航）→ 302 重定向 `/login?next=<原路径>`，登录成功后回跳（`next` 仅允许站内相对路径，防开放重定向）；
  - 接口请求（上传/下载等程序化调用）→ 401 JSON。
- `role_required("teacher")`：在 `login_required` 之后执行；学生调用上传直接返回 403，装饰器短路，不读取文件、不触盘、不写库。
- **班级过滤只存在于数据访问层** `materials/repository.py`，所有材料读写必须经此：
  - 列表：`list_for(user)` → `Material.query.filter_by(class_id=user.class_id).order_by(created_at.desc())`；
  - 详情/下载：`get_scoped_or_404(user, material_id)` → `filter_by(id=..., class_id=user.class_id).first()`，查不到统一 `abort(404)`，不区分"不存在"与"跨班"；
  - 写入：新建 `Material` 的 `class_id` 只能取 `g.user.class_id`，`uploader_id` 取 `g.user.id`；表单/查询串里出现的 class/role 字段一律不读。
- 关键不变量：除 repository 外的代码不允许直接 `Material.query` 访问；测试中对该不变量做断言（所有材料查询都带 class_id 条件）。

### 5. 上传与下载数据流

- 上传 `POST /materials/upload`（`multipart/form-data`，单字段单文件），顺序固定：**认证 → 角色 → 文件校验 → 落盘 → 写库**，任何一步失败立即返回且无副作用。
- 校验：扩展名 + 声明 MIME 双白名单（pdf、docx、pptx、xlsx、png、jpeg），单文件上限 20MB（同时配 `MAX_CONTENT_LENGTH`，超限由框架拒绝）；不合法返回 400/413。
- 存储键服务端生成：`<UPLOAD_ROOT>/<class_id>/<uuid4><.ext>`；`secure_filename` 仅用于净化原始文件名后存入数据库展示，**绝不参与服务端路径拼接**（防路径穿越）。上传目录放在数据卷（如 `/data/uploads`），不放在 `app/static/` 下。
- 一致性：先落盘再写库；写库抛异常时 `os.remove` 回滚已存文件（孤儿清理），整体返回 5xx。
- 下载 `GET /materials/<id>/download`：先 `login_required`，再 `get_scoped_or_404`（跨班 404），命中后 `flask.send_file` 流式返回并设置 `Content-Disposition: attachment; filename*=UTF-8''<净化后的原始名>`；物理文件缺失返回 500。
- 备选：BLOB 入库（库体积/性能差）、`static/` 直出（绕过班级鉴权）——均否决。

### 6. 预置数据（seed）

- `flask init-db` 建表；`flask seed` 幂等执行：按班级名/用户名 `get-or-create`，创建 A/B 班、`teacher_a`、`student_a`、`teacher_b`、`student_b`（演示口令经哈希写入，口令值仅记录在 `.env.example` 或课堂说明中）与 A 班一条 PDF 示例材料。
- 所有账号密码同样走 `generate_password_hash`，种子文件中不得把任何口令明文写库。
- 重复 `flask seed`：已存在的班级/账号跳过，不产生重复行（用户名、班级名唯一约束兜底）。

### 7. Docker Compose 与 GET /health

- `Dockerfile`：python:3.12-slim 基础镜像，装 requirements，复制代码，非 root 用户运行，`CMD` 由 compose 覆盖为启动脚本。
- `docker-compose.yml`：单服务 `web`，构建本镜像，发布 `8000:8000`，gunicorn 启动 `wsgi:app`；两个挂载——命名卷或 bind mount 映射 `/data`（内含 SQLite 文件与 uploads）；`env_file: .env` 注入 `SECRET_KEY` 等。
- 容器入口脚本：`flask init-db && flask seed && gunicorn ...`，保证全新环境 `docker compose up` 即得可演示系统；init-db/seed 均幂等，故每次启动执行安全。
- `GET /health`：公开路由（无任何鉴权装饰器），执行一次轻量数据库探活（`SELECT 1`），成功返回 `200 {"status":"ok"}`，异常返回 `503 {"status":"error"}`；compose 配置 `healthcheck: curl -f http://localhost:8000/health`。
- 备选：Compose 中再加独立 nginx/db 服务——SQLite 无需独立数据库服务，多一层只增加课堂负担，否决。

### 8. 关键 HTTP 语义

| 情形 | 状态码 |
|---|---|
| 未登录访问受保护页面 | 302 → `/login?next=...` |
| 未登录调用上传/下载等受保护接口 | 401 |
| 学生调用上传接口（含绕过前端直连） | 403 |
| 跨班访问材料详情/下载 | 404（不确认资源存在） |
| 文件类型不合法 | 400 |
| 文件超过大小上限 | 413（或框架等价错误页/JSON） |
| 元数据存在但物理文件缺失、落盘后写库失败 | 500（失败时回滚已存文件） |
| `GET /health` 正常 / 数据库不可用 | 200 / 503 |

### 9. 测试策略

- pytest + Flask test client：每个测试用独立临时 SQLite 文件（`DATABASE_URL` 指向 tmp_path）与临时上传目录、独立 `SECRET_KEY`。
- 必测教学主线：
  1. 未登录访问列表页 302 到登录页；未登录 POST 上传返回 401；
  2. 学生登录后直传合法文件返回 403，上传目录无新增文件、material 表无新增行；
  3. A 班学生/教师访问 B 班 material id 的详情与下载均 404；列表互不串数据；
  4. teacher_a 上传后立即查列表含新记录且字段正确；student_b 列表不含；文件可下载且字节一致；
  5. 直接断言数据库中密码列为哈希形态、相同密码哈希不同；
  6. `flask seed` 连跑两次行数不变；生产模式缺 `SECRET_KEY` 启动即报错；`GET /health` 未登录 200、DB 故障 503。

## Risks / Trade-offs

- [开放注册允许自选角色，任何人都能注册教师账号] → 教学取舍，注册页标注"演示用途"，班级只能选预置项；后续加邀请码即可收敛，不影响本期模型。
- [本地磁盘存储不支持多实例] → 存储读写封装在单一 storage 辅助模块（按 `stored_key` 读写），日后换对象存储只改该模块；Compose 用卷保证单机持久。
- [上传伪装扩展名的恶意文件] → 扩展名+MIME 双白名单、服务端 UUID 重命名、目录不可执行、不经静态路径暴露；不做内容级病毒扫描（Non-Goal）。
- [原始文件名路径穿越/乱码] → 存储键只用 uuid4，原始名净化后仅入库与下载头展示。
- [SQLite 多写并发] → 教学低并发足够；WAL + 短事务；compose 单实例避免多写者。
- [签名 Cookie 被盗] → httpOnly、SameSite=Lax、生产 Secure；会话仅存 user_id 且每请求回库，删除/变更用户即时生效；不设超长有效期。

## Migration Plan

1. 初始化 Flask 工程、依赖清单、配置与 `.env.example`/`.gitignore`。
2. `flask init-db` 建表 → `flask seed` 写入 A/B 班、演示账号与示例材料。
3. 构建镜像并 `docker compose up`，用 `/health` 与四条测试主线验收。
4. 回滚：删除数据卷（SQLite 文件与 uploads）后重新 `up` 即自动重建；无生产数据风险。

## Open Questions

无。以下细节已按合理假设固化：每人归属一个班级；允许类型 pdf/docx/pptx/xlsx/png/jpeg；单文件上限 20MB；演示账号 `teacher_a` / `student_a` / `teacher_b` / `student_b`；对外端口 8000；健康检查路径 `GET /health`。
