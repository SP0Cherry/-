## Context

当前代码（jwt-bearer-auth 已落地）：单体 Flask（应用工厂 + Blueprint）+ Flask-SQLAlchemy + SQLite；业务能力全部是无状态 JWT（HS256）保护的 JSON API（`/api/*`），并向浏览器提供公开、零数据的静态 HTML + vanilla JS 外壳（`/`、`/login`、`/register`）；材料落盘 `UPLOAD_ROOT/<class_id>/<uuid>.<ext>`；班级过滤只存在于 `materials/repository.py`；允许类型由 `ALLOWED_EXTENSIONS` 与 `ALLOWED_MIME_TYPES` 双白名单控制；建表仅靠 `db.create_all()`（不引入 Alembic）；容器入口固定 `flask init-db && flask seed`，gunicorn 2 workers，全部持久数据在命名卷 `/data`。

编写本设计前，用用户提供的凭据对网关做了真实验证（结果作为设计依据）：

- `POST {EMBEDDING_BASE_URL}/embeddings`（模型 `course-embedding`）成功返回嵌入，维度 **2048**。
- `POST {EMBEDDING_BASE_URL}/chat/completions` 网关只允许模型 **`course-chat`**（请求其他模型返回 400「只允许这些模型：course-chat」）；`course-chat` 接口通路正常。
- 两个服务同 Base URL、同 API Key，均为 OpenAI 兼容报文。

本设计取代早先版本：嵌入由本地 FastEmbed/BGE（512 维、全离线）改为上述远程 API（2048 维）；页面由 Jinja 服务端渲染改为静态外壳 + JSON API。

## Goals / Non-Goals

**Goals:**

- txt/md 可上传（UTF-8 严格校验）、可在浏览器安全预览（txt 等宽纯文本、md 渲染为排版结构），师生双端体验一致。
- txt/md 上传后自动进入按 `class_id` 强制隔离的向量知识库；检索结果带来源文件、片段与定位锚点。
- 两种模式：知识检索（只返回可溯源片段）；知识问答（先检索，命中则带依据调用 `course-chat` 生成带来源回答；未命中返回门控状态，用户确认后才做无依据回答并显式标注）。
- 嵌入/问答密钥只存服务端，浏览器不直连网关；索引与 SQLite 同库同卷持久；`flask reindex-kb` 幂等回填/重建。
- 测试零网络、零模型下载：嵌入与问答均有 stub 后端。

**Non-Goals（本期不做）:**

- pdf/docx/pptx/xlsx/图片的内容抽取与预览（仅保留下载；不索引）。
- 流式（SSE）回答、多轮对话上下文、问答历史持久化、检索结果的 LLM 重排。
- 材料的删除/编辑（索引删除路径只服务"重建"）；一师多班。
- 本地嵌入后端（抽象保留，但不提供也不测试 FastEmbed 通路）。
- 知识库管理后台、索引失败自动重试队列、异步任务框架、模型管理 UI。

## Decisions

### 1. 模块结构：新增 `app/kb/` 包，材料侧加内容接口与预览入口

```
app/kb/
  __init__.py      # kb_bp Blueprint
  chunking.py      # 文本切分、标题/行号提取、slug 计算
  embeddings.py    # Embedder 抽象 + APIEmbedder（HTTP /embeddings）+ StubEmbedder；惰性单例工厂
  llm.py           # ChatClient 抽象 + GatewayChatClient（HTTP /chat/completions）+ StubChatClient
  vector_store.py  # sqlite-vec 扩展加载、按配置维度建 vec0 虚表、upsert/delete/KNN
  repository.py    # kb_chunks 唯一 DAL（所有读带 class_id）、单事务替换
  indexer.py       # index_material：读文件→切分→嵌入→事务替换→置 indexed_at
  service.py       # retrieve()：校验→嵌入→KNN→本班过滤→阈值判定；ask()：检索→门控/带依据/强制回答
  routes.py        # GET /api/kb/search；POST /api/kb/ask
templates 无（静态外壳架构）
app/static/kb.html, app/static/preview.html
app/static/js/kb.js, app/static/js/preview.js
```

`materials` 模块新增 `GET /api/materials/<id>/content`（受班级边界保护）与 `GET /api/config`（下发允许格式/可预览格式）；上传流程仍在 `materials/routes.py`，材料提交成功后调用 `kb.indexer.index_material()`。

### 2. 上传链路：txt/md 先校验 UTF-8，再落盘→写库→建索引

- `Config.ALLOWED_EXTENSIONS` 默认追加 `txt`、`md`；`ALLOWED_MIME_TYPES` 增加 `txt:{text/plain}` 与 `md:{text/markdown,text/x-markdown,text/plain}`（兼容浏览器对 .md 的不一致声明，仍维持扩展名 + MIME 双白名单）；新增 `PREVIEWABLE_EXTENSIONS={"txt","md"}`。
- txt/md 上传处理：在 20MB 上限内读入字节 → `bytes.decode("utf-8")` 严格解码，失败直接 400 且不触盘 → `storage.write_bytes` 落盘（复用现有"写库失败删文件"补偿）→ `repository.create_material`。
- 材料记录提交成功后调用 `indexer.index_material(material)`；索引失败仅记日志、`indexed_at` 留空，**上传接口不回滚材料**。
- `GET /api/config`（`login_required`）返回 `{allowed_extensions:[...], previewable_extensions:[...]}`；前端据此渲染 accept 与提示文字。不把该清单塞进 `/api/auth/me`，避免身份负载混入业务配置。

### 3. 预览：内容接口取数 + 浏览器端安全渲染（不注入 HTML 字符串）

- `GET /api/materials/<id>/content`：复用 `repository.get_scoped_or_404(user, id)`（跨班天然 404）；扩展名非 txt/md 返回 415；物理文件缺失返回 500；响应 `{id, original_name, ext, content}`。
- 新外壳路由 `/materials/<int:material_id>/preview` 公开返回 `preview.html`（与现有 SHELL_PAGES 同样的 send_from_directory 模式；业务数据全部靠 JS 带令牌拉取）。
- `preview.js`：txt → 构建 `<pre>`，逐行生成 `<span id="L{n}">`，文本经 `textContent` 注入；md → 自研最小 Markdown 渲染器，只生成 DOM 节点：标题 h1–h6（id 取与索引侧一致的 slug）、段落、无序/有序列表、引用块、代码块、行内粗体/斜体/代码与链接。链接只接受 http/https 协议，强制 `target=_blank rel=noopener`；不使用 `innerHTML`，不加载任何第三方 JS。
- 选择客户端渲染而非早先的服务端 `Markdown` + `bleach`：保持静态外壳"不用 innerHTML 插入不可信内容"的 XSS 缓解纪律与现有 CSP（`script-src 'self'`），材料脚本天然不可执行；代价是渲染器只支持 Markdown 安全子集。溯源定位：`chunking` 记录每块 `line_no` 与标题 slug，检索结果链接指向 `/materials/<id>/preview#L<n>` 或 `#<slug>`，预览渲染完成后按 location.hash 滚动。两端 slug 算法必须一致（见 Decision 5），以固定夹具测试对齐。

### 4. 数据模型：常规表 + sqlite-vec 虚表，维度取配置

- `materials` 增加可空列 `indexed_at DATETIME`（非文本/未索引为 NULL，兼作回填判据）。
- 新表 `kb_chunks`：`id`、`material_id FK→materials.id`、`class_id`（冗余落列并建索引，物理保证班级过滤）、`chunk_index`、`char_start`、`line_no`、`heading NULL`、`heading_slug NULL`、`content TEXT`、`created_at`；`UNIQUE(material_id, chunk_index)`。
- 向量虚表：裸 DDL `CREATE VIRTUAL TABLE IF NOT EXISTS kb_vectors USING vec0(chunk_id INTEGER PRIMARY KEY, embedding FLOAT["{Config.EMBEDDING_DIM}"])`，与主库同一文件，随 `/data/campusclaw.db` 持久。维度在建表时从应用配置读取；测试通过 test_config 把 `EMBEDDING_DIM` 设为 64。
- 幂等 `ensure_runtime_schema()`：`PRAGMA table_info(materials)` 缺列则 `ALTER TABLE ... ADD COLUMN indexed_at`，并确保虚表存在；在 `create_app` 既有 sqlite 初始化段与 `flask init-db` 中各调用一次。不引入 Alembic。
- sqlite-vec 在现有 sqlite 连接事件中加载（与 `PRAGMA foreign_keys/WAL` 同处）：`import sqlite_vec; sqlite_vec.load(dbapi_connection)`。
- 维度变更在已有数据卷上无法直接改虚表列型：本期为首版（卷中尚无虚表）；若日后改维度，需 `reindex-kb --all`（重建时先 DROP 再按新维度建表），部署文档说明。

### 5. 切分：纯函数、双端 slug 对齐

`chunking.py`（纯函数易测）：按段落累积到约 `KB_CHUNK_CHARS=400` 字符（中文按字符计），相邻块 `KB_CHUNK_OVERLAP=80` 字符重叠；逐段跟踪最近的 Markdown/文本标题行作为 `heading`，同时输出标题 `slug`、块首 `char_start` 与 `line_no`。空文件/纯空白文件不产块（上传仍成功）。slug 规则固化为共享约定：去除标点、空白转连字符、ASCII 小写、保留中文字符；Python 与 `preview.js` 各实现一份，测试用同一组标题夹具断言两侧输出一致。

### 6. 嵌入客户端：APIEmbedder（requests，归一化，批量）

- `embeddings.py` 定义 `Embedder`（`dim`、`embed(list[str]) -> list[list[float]]`）：
  - **APIEmbedder**（默认）：`POST {EMBEDDING_BASE_URL}/embeddings`，JSON `{model: EMBEDDING_MODEL, input: texts}`，`Authorization: Bearer EMBEDDING_API_KEY`，超时 `EMBEDDING_TIMEOUT=15s`；对连接错误/5xx 重试一次；按输入条数分批（每批 ≤64 条）；响应向量数与输入数一致、维度与 `EMBEDDING_DIM` 一致，否则抛错。对返回向量做 L2 归一化（防御性，保证距离阈值语义稳定）。
  - **StubEmbedder**（`EMBEDDING_BACKEND=stub`，测试/CI）：对文本做确定性字符 n-gram 哈希投影到配置维度并归一化；相同词条共现的查询与文本得分更高，使命中/排序/隔离断言无需网络即可运行。
- 工厂按 config 返回惰性单例（首次入库/检索时构造），健康检查不占用连接。
- 配置缺失（Base URL/Key/Model 为空）时，embedder 抛 `EmbeddingConfigError`，由路由映射为 503。

### 7. 问答客户端与提示词

- `llm.py` 定义 `ChatClient.chat(messages) -> str`：
  - **GatewayChatClient**：`POST {EMBEDDING_BASE_URL}/chat/completions`，JSON `{model: LLM_MODEL（默认 course-chat）, messages, temperature: LLM_TEMPERATURE=0.3, max_tokens: LLM_MAX_TOKENS=800}`，复用同一 API Key，超时 `LLM_TIMEOUT=40s`，5xx/连接错误重试一次；非 200 或报文缺字段抛 `ChatError`（路由映射 502）。
  - **StubChatClient**（`LLM_BACKEND=stub`）：依据 messages 中是否含材料上下文返回确定性文本（如"根据材料：…"或"未参考材料：…"），供门控/标注断言。
- **带依据回答的提示词**（检索命中时）：system 固定为"你是课堂助教。只能依据给出的参考材料回答，材料不足就明说材料中未找到答案，不得编造；回答简洁并可注明依据编号。"；user 组织为编号片段清单（每条带来源名/小节）+ 问题。
- **强制回答**（用户确认继续）：不带材料片段，system 改为通用助教；响应在 API 层标记 `retrieved=false`，前端展示"该回答未基于本班材料"警示。
- 实测发现 `course-chat` 对部分模板化长句会回"我没理解您的问题"，但简单中文提问通路正常 → 提示词保持单块、自然陈述；实施时以真实课程问题校准措辞（列为任务，不改变方案与契约）。

### 8. 检索编排、相关度阈值与问答门控

- `retrieve(user, q)`：输入校验（非空、非纯空白、长度 ≤ `KB_QUERY_MAX_LEN=200`）→ embedder 嵌入查询 → `vector_store.knn()` 对全库做 KNN（不在 vec 侧截断）→ `repository.search_scoped()` JOIN `kb_chunks` 且 **WHERE class_id = 用户班级**，ORDER BY distance 取候选 → L2 距离换算为 0–1 的相关度（归一化向量：`score = 1 - distance²/2`），保留 `score ≥ KB_MIN_SCORE`（默认 0.35，env 可调）的命中，数量 ≤ `KB_TOP_K=8`。
- 全库 KNN 后过滤的原因同早先设计：vec0 不支持任意元数据过滤；跨班数据只参与距离计算，文本只在班级过滤后的 JOIN 中读取。过滤 SQL 集中在 `kb/repository.py`。
- `ask(user, q, force=False)`：
  1. `retrieve` 有达标命中 → 组装带依据提示词 → ChatClient → `{retrieved:true, answer, sources:[...]}`；
  2. 无达标命中且 `force=false` → **不调用 ChatClient**，返回 `{retrieved:false, answer:null, message:"未检索到相关知识，是否仍要 AI 尝试回答？"}`；
  3. 无达标命中且 `force=true` → 无材料上下文调用 ChatClient → `{retrieved:false, answer, sources:[]}`。
- 来源对象字段：`material_id`、`material_name`、`snippet`、`heading`、`line_no`、`score`、`preview_url`（txt→`/materials/<id>/preview#L<line>`，md→`#<slug>`）。

### 9. API 契约（统一 JSON 错误体 `{error, message}`，沿用现有错误处理）

| 接口 | 成功 | 失败语义 |
|---|---|---|
| `GET /api/config` | 200 `{allowed_extensions, previewable_extensions}` | 401 |
| `GET /api/materials/<id>/content` | 200 `{id, original_name, ext, content}` | 401 / 跨班 404 / 非文本 415 / 文件缺失 500 |
| `GET /api/kb/search?q=` | 200 `{items:[...sources], }` | 401 / 400 非法 q / 503 未配置 / 502 网关错误 |
| `POST /api/kb/ask` body `{q, force?}` | 200 `{retrieved, answer, sources, message?}` | 同 search；answer=null 即门控态 |

### 10. 依赖、镜像与运行形态

- requirements 新增 `sqlite-vec>=0.1,<1`、`requests>=2.31,<3`；不引入 Markdown/bleach/fastembed。
- Dockerfile 不需要模型预取、libgomp1 等步骤，镜像保持 slim；运行要求容器能经 HTTPS 出站访问 `EMBEDDING_BASE_URL` 指向的主机（docker-compose 部署说明注明）。
- entrypoint 维持 `init-db → seed → gunicorn`：seed 内对文本材料的索引失败按材料隔离（记 warning、不中断 seed）；配置 Key 后 `flask reindex-kb` 补齐。gunicorn 维持 2 workers（无本地模型，额外内存仅 sqlite-vec 计算）。

### 11. 测试策略（pytest + test client；嵌入/问答 stub，零外网）

- conftest：test_config 设 `EMBEDDING_BACKEND=stub`、`LLM_BACKEND=stub`、`EMBEDDING_DIM=64`；`ensure_runtime_schema` 在测试库自动建列/虚表。
- 用例：
  1. 上传：txt/md 成功；非 UTF-8 400 且无文件无记录；md 以 text/plain 声明被接受；嵌入 API 故障（注入抛错的 embedder）时上传仍 201、无半套块、`indexed_at` 为空；
  2. `/api/config` 清单含全部扩展名且标注 txt/md；
  3. 内容接口：本班可取、跨班 404、非文本 415、文件缺失 500、未认证 401；
  4. 检索：语义命中、相关度排序、top_k 截断、空/超长 q 400、跨班零命中（含文件名/文本不泄露）、师生范围一致；
  5. 问答：命中时返回回答 + 来源；片段不足时回答声明材料不足；无命中→`retrieved:false, answer:null` 且 ChatClient 未被调用（用计数 spy 断言）；`force=true`→回答且标记未基于材料；问答 API 故障→502；未配置密钥→503；
  6. 溯源 URL 合法，直接访问该内容接口跨班 404；
  7. 持久化：同一数据库文件重建 app 后索引仍在；
  8. `reindex-kb` 连跑两次块数不变、可回填、`--material-id` 单建；
  9. seed 幂等：连跑两次材料数与块数不变；
  10. stub 全链路不发起真实网络（断言请求计数）。
- 前端 vanilla JS 的交互（模式切换、门控确认、md 渲染、锚点定位）通过浏览器端到端验收覆盖。

## Risks / Trade-offs

- [材料文本与问题发送至外部网关，隐私/合规变化] → 仅经 HTTPS 访问指定网关；密钥仅服务端、浏览器不直连；在部署说明中明确该取舍。
- [网关不可用/超时导致检索与问答失败] → 超时 + 一次重试；错误明确映射 502；入库与上传解耦且可 reindex；检索本身依赖网络是已接受取舍。
- [阈值误判：无关内容被当命中，或真正相关被判未检索到] → `KB_MIN_SCORE` 可配；实施期用真实问题集（相关/跑题各若干）标定并记录结果；stub 覆盖边界场景。
- [course-chat 对结构化提示词偶发返回兜底"没理解"] → 实施期以真实课程问题校准提示词；已实测网关通路；问答失败有 502 兜底。
- [全库 KNN 后按班过滤的规模与纪律风险] → 课堂单年级规模毫秒级；过滤 SQL 集中 kb/repository.py，跨班测试锁死；量级增长再改按班分区。
- [向量维度变更/旧卷] → 首版卷中无虚表；换维度需 DROP + `reindex-kb --all`，文档说明；新列可空，旧代码可忽略。
- [自研 md 渲染器能力子集、解析差异] → 只生成 DOM 文本节点，从根本上不产生可执行 HTML；链接协议白名单；渲染范围明确为常用教学排版语法。
- [密钥经错误体/日志泄露] → 异常信息只透传网关 message，不拼接请求头；断言响应与日志不含密钥；.env 不提交。

## Migration Plan

1. 确认 jwt-bearer-auth 基线（代码已在）。
2. `pip install -r requirements.txt`，stub 后端下跑全量 pytest。
3. 在 `.env` 配置 `EMBEDDING_BASE_URL/EMBEDDING_API_KEY/EMBEDDING_MODEL/EMBEDDING_DIM`（`.env.example` 给占位）；`docker compose up`：entrypoint 自动完成建列/虚表升级、种子文本入库。
4. 若启动时未配 Key 或索引失败：配置后执行 `flask reindex-kb` 回填。
5. 验收：未认证检索/问答 401；A 班检索 A 班预置内容命中、检索 B 班独有内容返回未检索到门控；问答命中带来源；确认"继续回答"后回答标注未基于材料；上传 md 后可预览（脚本不执行）、可检索；容器重建后索引仍在。
6. 回滚：回退旧镜像（新表/新列被忽略）；彻底回滚则备份后删除命名卷重建种子。

## Open Questions

无。以下细节按合理假设固化并在实施中校准：切块 400 字符/重叠 80；top_k=8；查询上限 200；相关度阈值默认 0.35（实施时用真实问题标定）；嵌入/问答超时 15s/40s；模型 `course-embedding`(2048 维)/`course-chat`；不做历史与流式；gunicorn 2 workers；非文本与空文本不进索引但上传合法。
