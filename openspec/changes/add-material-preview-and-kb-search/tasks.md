﻿﻿﻿﻿﻿﻿﻿﻿﻿# Tasks

## 1. 依赖与配置

- [x] 1.1 在 requirements.txt 增加 `sqlite-vec>=0.1,<1`、`requests>=2.31,<3`（不引入 Markdown/bleach/fastembed），在 venv 执行 `pip install -r requirements.txt` 验证安装成功，并 `python -c "import sqlite_vec,requests"` 通过
- [x] 1.2 更新 `app/config.py`：默认允许扩展名追加 txt/md，MIME 白名单增加 `txt:{text/plain}`、`md:{text/markdown,text/x-markdown,text/plain}`，新增 `PREVIEWABLE_EXTENSIONS={"txt","md"}`；新增嵌入配置 `EMBEDDING_BASE_URL`（默认给定网关地址）、`EMBEDDING_API_KEY`（仅环境变量，无默认）、`EMBEDDING_MODEL=course-embedding`、`EMBEDDING_DIM=2048`；新增问答配置 `LLM_MODEL=course-chat`、`LLM_BACKEND`、`LLM_TEMPERATURE=0.3`、`LLM_MAX_TOKENS=800`、`EMBEDDING_TIMEOUT=15`、`LLM_TIMEOUT=40`；新增 KB 配置 `EMBEDDING_BACKEND`、`KB_CHUNK_CHARS=400`、`KB_CHUNK_OVERLAP=80`、`KB_TOP_K=8`、`KB_QUERY_MAX_LEN=200`、`KB_MIN_SCORE=0.35`；以加载配置的单元测试断言默认值齐全且无硬编码密钥
- [x] 1.3 更新 `.env.example`：补充上述变量说明与占位值（`EMBEDDING_API_KEY=` 留空加注"服务端专用、切勿提交"），确认仓库中无真实密钥；核对 `.gitignore` 仍忽略 `.env`

## 2. 数据模型与 SQLite schema 升级

- [x] 2.1 在 `app/models.py` 的 `Material` 增加可空列 `indexed_at`，新增 `KbChunk` 模型（id、material_id、class_id 带索引、chunk_index、char_start、line_no、heading、heading_slug、content、created_at，`UNIQUE(material_id, chunk_index)` 及关系）；用 `db.create_all()` 建表验证结构
- [x] 2.2 在应用工厂 sqlite 连接事件中加载 sqlite-vec（与既有 PRAGMA 同处，`sqlite_vec.load(dbapi_connection)`）；测试在测试库连接上执行 `SELECT vec_version()` 验证扩展可用
- [x] 2.3 新增幂等 `ensure_runtime_schema()`（置于 `app/kb/vector_store.py`）：`PRAGMA table_info(materials)` 缺列时 `ALTER TABLE ... ADD COLUMN indexed_at`，并按 `Config.EMBEDDING_DIM` 执行 `CREATE VIRTUAL TABLE IF NOT EXISTS kb_vectors USING vec0(chunk_id INTEGER PRIMARY KEY, embedding FLOAT[<dim>])`；在 `create_app` 初始化段与 `flask init-db` 中调用；测试在全新库与模拟旧库各执行一次，断言列/虚表存在且重复执行不报错

## 3. 格式清单接口与 txt/md 上传改造

- [x] 3.1 改造上传视图：txt/md 先读入字节并按 UTF-8 严格解码（失败返回 400 编码错误，不触盘不写库），随后复用 `storage.write_bytes` 落盘与 `repository.create_material` 写库；其他类型保持原路径；测试覆盖合法 txt/md 成功、非 UTF-8 返回 400 且无文件无记录、md 声明 text/plain 被接受
- [x] 3.2 新增 `GET /api/config`（`login_required`）返回 `{allowed_extensions, previewable_extensions}`；更新 `index.html` 的 accept 与说明文字、`materials.js` 在加载时拉取该接口派生展示（不写死清单）；测试断言未认证 401、响应含全部扩展名与 txt/md 预览标注

## 4. 内容接口与预览外壳页

- [x] 4.1 新增 `GET /api/materials/<id>/content`：`get_scoped_or_404` 鉴权 → 非 txt/md 返回 415 → 文件缺失 500 → 返回 `{id, original_name, ext, content}`；测试覆盖跨班 404、非文本 415、文件缺失 500、未认证 401
- [x] 4.2 在应用工厂注册公开外壳路由 `/materials/<int:material_id>/preview`（返回静态 preview.html，模式同 SHELL_PAGES）；新建 `app/static/preview.html` 与 `js/preview.js`：从路径解析 id、带 Bearer 拉取内容接口，401 跳登录；测试验证外壳路由公开 200
- [x] 4.3 实现 txt 预览：`<pre>` 内逐行生成 `<span id="L{n}">`，全部文本经 textContent 注入；测试验证尖括号/脚本片段以纯文本展示、换行保留
- [x] 4.4 实现安全的 md DOM 渲染器（标题 h1–h6 带 slug、段落、列表、引用、代码块、行内粗体/斜体/代码、链接仅 http/https 且 noopener；全程 createElement/textContent，不用 innerHTML）；渲染后按 location.hash 定位；浏览器验收标题/列表正确呈现且 `<script>`、`onerror`、`javascript:` 输入不构成可执行内容
- [x] 4.5 更新材料列表：对 txt/md 行显示"预览"按钮（打开 `/materials/<id>/preview`），师生视图均显示；测试验证按钮可见性由接口字段决定、非文本行无预览入口

## 5. 知识库核心：切分、嵌入、问答、向量存储、索引

- [x] 5.1 编写 `app/kb/chunking.py` 纯函数：按约 400 字符切块、80 字符重叠，输出每块文本、char_start、line_no、最近标题 heading 与 heading_slug；slug 规则与 preview.js 共享；单元测试覆盖短文本单块、长文本多块不丢字、重叠正确、标题归属、空文本零块，并用同一组标题夹具断言 Python/JS slug 一致
- [x] 5.2 编写 `app/kb/embeddings.py`：`Embedder` 抽象 + `APIEmbedder`（requests POST `/embeddings`，Bearer 头，15s 超时、5xx/连接错误重试一次、≤64 条分批、校验返回条数与维度、L2 归一化）+ `StubEmbedder`（确定性 n-gram 哈希投影到配置维度并归一化、不访问网络）；定义 `EmbeddingConfigError`；提供按 config 取惰性单例的工厂；stub 单测验证同维、归一化与可重复结果
- [x] 5.3 编写 `app/kb/llm.py`：`ChatClient` 抽象 + `GatewayChatClient`（POST `/chat/completions`，模型取 LLM_MODEL，复用 EMBEDDING_BASE_URL/EMBEDDING_API_KEY，40s 超时与一次重试，报文异常抛 `ChatError`）+ `StubChatClient`（区分有无材料上下文的确定性回答）；用注入的 requests 假对象测试请求组织与错误映射，stub 路径不访问网络
- [x] 5.4 完善 `app/kb/vector_store.py`：kb_vectors 插入（块 id + 向量序列化）、按 material_id 删除、查询向量 KNN（返回 chunk_id/distance，全库扫描不在 vec 侧截断）；测试验证写入→KNN 命中自身→删除后不命中的往返
- [x] 5.5 编写 `app/kb/repository.py`：`replace_chunks(class_id, material_id, chunks, vectors)` 单事务替换（先删旧块与向量再插入）、`set_indexed_at`、`search_scoped(user_class_id, candidate_rows, limit)` JOIN kb_chunks 强制带 class_id 过滤并按 distance 排序；测试断言所有读路径带班级条件、同材料替换两次行数不变
- [x] 5.6 编写 `app/kb/indexer.py`：`index_material(material)` 读盘→切块→批量嵌入→事务替换→置 indexed_at；异常回滚不留半套块并抛出；上传视图在材料提交成功后调用并捕获异常仅记日志；测试验证 txt/md 上传后块与 indexed_at 立即可用、非文本无块、嵌入失败（注入抛错 embedder）时上传仍 201、无半成品块且 indexed_at 为空

## 6. 检索/问答服务、路由与页面

- [x] 6.1 编写 `app/kb/service.py` 的 `retrieve(user, q)`：校验非空/非纯空白/长度 ≤200（非法返回 400 级错误）→ 嵌入查询 → KNN → 本班 repository 过滤 → 距离换算 score 并按 `KB_MIN_SCORE` 过滤 → 组装来源（material_id/name、snippet、heading、line_no、score、preview_url），数量受 KB_TOP_K 限制；用 stub 测试语义命中、排序、阈值边界与 top_k 截断
- [x] 6.2 编写 `ask(user, q, force=False)`：命中→带依据提示词调用 ChatClient 返回 `{retrieved:true, answer, sources}`；未命中且 force=false→不调用 ChatClient，返回 `{retrieved:false, answer:null, message}`；未命中且 force=true→无材料上下文调用并返回带 `retrieved:false` 标记的回答；测试用调用计数 spy 断言门控态不触发问答、force 路径被标记、ChatClient 抛错映射 502
- [x] 6.3 新增 kb Blueprint 路由 `GET /api/kb/search?q=` 与 `POST /api/kb/ask`（JSON：q、force），在应用工厂以 `/api` 前缀注册；测试覆盖未认证 401、空/超长查询 400、未配置密钥 503、网关错误 502
- [x] 6.4 新建 `app/static/kb.html` 与 `js/kb.js`：模式切换（知识检索 / 知识问答），检索模式渲染来源列表（文件名、片段、小节/行号、相关度、溯源链接），问答模式渲染答案 + 出处；未检索到时展示提示与"继续回答/取消"按钮（默认不继续，继续则带 force=true 重发），force 回答显示"未基于本班材料"警示；全部内容用 textContent/DOM 节点
- [x] 6.5 注册公开外壳路由 `/kb`；在材料页与问答页增加互相导航入口；浏览器端到端验证两种模式、门控确认与标注展示完整

## 7. CLI 与种子数据

- [x] 7.1 在 `app/cli.py` 新增幂等 `flask reindex-kb [--all] [--material-id ID]`：默认处理 txt/md 且 indexed_at 为空的材料，--all 全量替换重建，输出处理统计；测试验证回填缺失索引、--all 连跑两次块数不变、--material-id 只重建指定材料
- [x] 7.2 更新 `app/seed.py`：A/B 班各增加一份内容显著不同的中文文本示例材料（一份 md、一份 txt），走 `index_material` 入库并对单材料索引失败隔离（记 warning 不中断 seed）；保持 get-or-create 幂等；测试验证首次 seed 后两班可分别检索本班内容、A 班检索 B 班独特内容零命中、连跑两次材料数与块数不变

## 8. 持久化与回归测试

- [x] 8.1 持久化测试：对同一 SQLite 文件与上传目录销毁并重建 app（模拟容器重启），断言已索引材料仍可检索、indexed_at 保留、虚表数据存在
- [x] 8.2 在 stub 后端运行全量 pytest（含既有 auth/tokens/access-control/materials/foundations/security 用例），确认全部通过，且无测试触发真实网络（记录对外请求计数为零）与模型下载

## 9. 容器化、网关标定与端到端验收

- [x] 9.1 核对 Dockerfile 无需模型预取/libgomp1 改动、镜像保持 slim；执行 `docker compose build` 成功；在部署说明（或 compose 注释）注明容器需经 HTTPS 出站访问 EMBEDDING_BASE_URL 主机
- [x] 9.2 `docker-compose.yml`/`.env` 链路确认：配置真实 EMBEDDING_* 后 `docker compose up`，entrypoint 自动建虚表、种子文本完成索引；未额外配置时 `/health` 仍 200
- [x] 9.3 网关标定：用真实嵌入对一组"相关/跑题"问题记录 score 分布，校准 `KB_MIN_SCORE`；以真实课程问题校准问答提示词（规避 course-chat 兜底回复），记录标定结果
- [x] 9.4 浏览器端到端验收：教师上传 md（含标题/列表与脚本字符串）→ 可预览（脚本不执行）→ 学生在 `/kb` 检索命中、溯源链接定位锚点 → 切问答模式得到带来源回答 → 用跑题问题得到"未检索到"门控、确认继续后回答标注未基于材料 → B 班账号全程零跨班泄露；记录验收结果
- [x] 9.5 运行 `openspec validate add-material-preview-and-kb-search --strict` 通过
