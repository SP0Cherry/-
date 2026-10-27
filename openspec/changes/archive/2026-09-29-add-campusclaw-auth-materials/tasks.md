# Implementation Tasks

## 1. 工程骨架与配置

- [x] 1.1 创建 Flask 工程结构（应用工厂 `create_app`、`config.py`、Blueprint 占位、`wsgi.py`、requirements.txt）并加入依赖 Flask、Flask-SQLAlchemy、Werkzeug、gunicorn、pytest（verify：`pip install -r requirements.txt` 成功，`python -c "from app import create_app; create_app()"` 不报错）
- [x] 1.2 实现配置只从环境变量读取（`SECRET_KEY`、SQLite 路径、上传目录、允许类型与大小上限），提供仅含占位符的 `.env.example`，并把 `.env`、上传目录、SQLite 文件加入 `.gitignore`（verify：仓库中 grep 不到真实密钥；`.env.example` 只有占位说明）
- [x] 1.3 生产模式（`FLASK_ENV=production`）下缺少 `SECRET_KEY` 时在应用工厂中快速失败（verify：不设该变量启动测试断言抛错退出；设置后正常启动）

## 2. 数据模型与建表

- [x] 2.1 定义 SQLAlchemy 模型 Class、User（username 唯一、password_hash、role、class_id 非空外键）、Material（original_name、stored_key 唯一、mime_type、size_bytes、uploader_id、class_id 非空外键、created_at），并建立 `(class_id, created_at)` 索引（verify：检查模型关系与字段约束齐全）
- [x] 2.2 为 SQLite 连接开启 `PRAGMA foreign_keys=ON` 与 WAL（verify：连接建立后执行外键违规插入测试被约束拒绝）
- [x] 2.3 实现幂等的 `flask init-db` 建表命令（verify：对临时数据库执行后 class/user/material 表存在，重复执行不报错）

## 3. 注册、密码哈希与登录会话

- [x] 3.1 实现密码加盐哈希工具：注册与改密统一走 `generate_password_hash`（pbkdtf2:sha256 + 随机盐）与 `check_password_hash`，全代码路径不出现明文落库/日志（verify：注册两个同密码用户后直接查库，两哈希不同且均不含明文；grep 代码确认无明文写入分支）
- [x] 3.2 实现注册页与注册处理：用户名唯一、密码最小长度、角色仅 teacher/student、班级必须已存在，失败返回字段级错误且不建账号（verify：pytest 覆盖注册成功、重名、不存在班级、短密码四个场景）
- [x] 3.3 实现登录/登出：统一错误提示、登录后写入 httpOnly + SameSite=Lax 的签名会话 Cookie（生产 Secure），登出清空会话（verify：pytest 验证正确凭据登录成功、错误凭据失败且无 Set-Cookie 会话、登出后旧 Cookie 失效）
- [x] 3.4 实现 `login_required` 装饰器与受保护路由的统一行为：页面请求 302 到 `/login?next=<原路径>` 且登录后回跳（仅允许站内相对路径），程序化接口请求返回 401（verify：pytest 覆盖未登录访问列表页重定向、回跳正确、未登录 POST 上传返回 401、篡改 Cookie 被当未认证处理）

## 4. 角色授权与班级隔离

- [x] 4.1 实现 `role_required("teacher")` 装饰器并应用于上传入口，学生请求在触盘/写库前短路返回 403（verify：pytest 用学生会话直传合法文件断言 403，且上传目录无新文件、material 表无新行）
- [x] 4.2 实现材料数据访问层 `repository.py` 作为材料读写唯一出口：列表强制 `filter_by(class_id=当前用户班级)`，单条查询用 `(id, class_id)` 双条件，查不到统一 404（verify：pytest 覆盖 A 班用户访问 B 班材料详情与下载均 404、两班列表互不串数据）
- [x] 4.3 保证写入归属只取会话身份：`class_id` 取当前用户班级、`uploader_id` 取当前用户，忽略请求中任何 class/role/is_admin 字段（verify：pytest 构造带 `role=teacher`、其他班级标识的上传请求，学生仍 403、教师材料归属本班）
- [x] 4.4 建立"除 repository 外不得直接查询 Material"的代码约束（如代码审查清单或静态断言测试）（verify：grep/测试确认业务层不存在绕过 class_id 条件的材料查询）

## 5. 材料上传、列表与下载

- [x] 5.1 实现 `POST /materials/upload`（multipart 单文件），顺序为认证 → 角色 → 校验 → 落盘 → 写库；扩展名 + MIME 双白名单（pdf/docx/pptx/xlsx/png/jpeg），配置 `MAX_CONTENT_LENGTH=20MB`（verify：pytest 覆盖合法文件成功、错误类型 400、超限 413，且失败时无文件无记录）
- [x] 5.2 实现服务端存储：存储键 `<UPLOAD_ROOT>/<class_id>/<uuid4><.ext>`，原始文件名经 `secure_filename` 净化后仅入库，上传目录不在 `static/` 下（verify：检查落盘路径全部为 UUID 键；构造含 `../` 的文件名不发生路径穿越）
- [x] 5.3 实现落盘-写库一致性：先落盘后写库，写库异常时删除已存文件（verify：pytest 模拟数据库写入失败，断言返回 5xx 且上传目录无孤儿文件）
- [x] 5.4 实现本班材料列表页（文件名、类型、大小、上传者、上传时间倒序）与上传后立即可查（verify：pytest 断言教师上传后本班列表含新记录且字段正确，B 班列表不含该记录；页面只对教师显示上传入口）
- [x] 5.5 实现 `GET /materials/<id>/download`：先登录再按班级双条件取记录，`send_file` 返回原始字节并设置净化文件名的 Content-Disposition；物理文件缺失返回 500（verify：pytest 断言本班下载字节一致、跨班 404、未登录 401、删文件后 500）

## 6. 预置演示数据

- [x] 6.1 实现幂等 `flask seed`：get-or-create A/B 班、teacher_a/student_a/teacher_b/student_b 四账号（哈希口令）与 A 班一条示例材料（verify：对临时库执行后数据齐全、角色班级正确；连跑两次表行数不变）
- [x] 6.2 用预置账号跑通课堂演示链路（verify：pytest 或手工脚本验证 student_a 上传 403、A 班账号访问 B 班材料 404、teacher_a 上传后 student_a 列表可见）

## 7. 健康检查与 Docker Compose

- [x] 7.1 实现公开的 `GET /health`：执行数据库 `SELECT 1` 探活，成功 200 `{"status":"ok"}`、异常 503，且无需登录不触发重定向（verify：pytest 覆盖未登录 200 与数据库不可用 503）
- [x] 7.2 编写 `Dockerfile`（python:3.12-slim、装依赖、非 root 运行、不包含 `.env` 与真实密钥）（verify：`docker build` 成功；镜像内 grep 不到真实 SECRET_KEY）
- [x] 7.3 编写 `docker-compose.yml`：发布 8000 端口、env_file 注入环境变量、卷持久化 /data（SQLite + uploads）、入口脚本执行 `flask init-db && flask seed` 后以 gunicorn 启动，并配置 healthcheck 调用 `/health`（verify：`docker compose up` 后 `curl http://localhost:8000/health` 返回 200，浏览器可打开登录页）
- [x] 7.4 验证容器重建数据持久化（verify：运行中上传材料 → `docker compose down` 容器删除 → `docker compose up` 后新账号/材料/文件仍存在且可下载）

## 8. 整体验收与规范校验

- [x] 8.1 运行完整 pytest 套件并全部通过，重点复核四条主线：未登录重定向/401、学生上传 403 无副作用、跨班访问 404、上传后本班列表可查且跨班不可见（verify：pytest 全绿，输出中四条主线用例均通过）
- [x] 8.2 运行 `openspec validate add-campusclaw-auth-materials --strict` 确认规划产物合法（verify：命令退出码为 0，无 error/warning 输出）
