## 1. 数据模型与技能解析

- [x] 1.1 在 `app/models.py` 新增班级级 `Skill` 模型（名称、适用条件关键词、资料、工具引用 JSON、正文、启用、创建者、创建时间，班内名称唯一），并在 `Class` 上建立关系；验证 `flask init-db` 后 `skills` 表存在且唯一约束生效
- [x] 1.2 新增 `app/skills/parser.py`，实现元数据/正文分割、`#` 注释与空行忽略、全角/半角冒号、8000 字上限、必填字段、重复/未定义字段、空正文校验；验证单测覆盖合法文件与每个拒绝场景
- [x] 1.3 在解析器中实现适用条件与工具字段拆分，支持 `knowledge_search` 与 `工具名@服务器名`，校验工具名正则和单 `@`；验证合法/非法引用单测通过
- [x] 1.4 将 MCP 缓存工具解析逻辑从 `app/mcp/routes.py` 抽到 `app/mcp/service.py`，并提供班级范围内按名称查服务器、解析令牌、构造客户端、读取缓存工具的函数；验证现有 MCP 测试与新增单元测试通过

## 2. 教师技能管理与 MCP 绑定校验

- [x] 2.1 新增 `app/skills/service.py`，实现 `create_skill`（解析 → 班内重名 → 逐个 MCP 引用校验 → 入库）与 `serialize_skill`（不含正文敏感内容与令牌）；验证重名、未登记服务器、未连接服务器、工具不在缓存四类错误消息
- [x] 2.2 新增 `app/skills/routes.py` 并注册蓝图：`GET /api/skills`（教师全部、学生仅启用）、`POST /api/skills`（教师 multipart 上传 UTF-8 文件）、`DELETE /api/skills/<id>`（教师、班级作用域）；验证学生 403、跨班 404、非 UTF-8 与超长文件 400
- [x] 2.3 验证技能管理响应不包含 `auth_token` 与技能正文，且跨班查询不泄露技能是否存在；用 API 测试断言原始响应文本

## 3. 种子预置技能

- [x] 3.1 新增 `app/skills/presets.py`，提供 A 班数学/语文两份合法技能文本（`资料`、`工具：knowledge_search`、`启用：是`，正文强调只指出下一步、不直接给答案）；验证两份文本均能通过解析器
- [x] 3.2 在 `app/seed.py` 中调用幂等写入，仅归属 A 班且按 `(class_id, name)` 跳过已存在记录；验证首次写入两份、重复执行数量不变、B 班为空

## 4. 流式问答与技能编排

- [x] 4.1 扩展 `app/kb/llm.py`：为 `ChatClient` 增加 `stream()`，实现网关 SSE 增量解析与 `StubChatClient` 单段输出；验证增量拼接等于完整回答、上游非 200 抛 `ChatError`
- [x] 4.2 扩展 `app/kb/service.py`：校验 `skill_ids`（去重保序、跨班 404、停用 400、上限 20），实现关键词命中、按请求顺序拼接技能规程到 system；验证未选择/命中/未命中/多技能顺序的单测
- [x] 4.3 在服务层实现命中技能的工具执行：`knowledge_search` 记录 `ok`；MCP 引用运行时按本班重新解析，未登记/未连接/不在缓存记 `denied`，远端异常记 `error`；结果截断后放入 user 数据区块；验证工具输出中的指令式文本不进入 system
- [x] 4.4 将 `POST /api/kb/ask` 改为 SSE：请求级错误返回 JSON，流内依次发送 `meta`、`delta`、`done`，聊天异常发送 `error`，并设置 `Cache-Control`/`X-Accel-Buffering` 头；验证事件顺序、`meta.tool_calls` 状态、门控无 delta、401/400 仍为 JSON
- [x] 4.5 更新 `tests/test_kb_api.py` 等既有问答测试以解析 SSE，保留检索、门控、强制继续与班级隔离断言；验证全量 `pytest` 通过

## 5. 前端技能选择与流式渲染

- [x] 5.1 在 `app/static/kb.html`/`kb.js` 增加已启用技能复选列表，提交时发送 `skill_ids`；验证未选择时请求体不含技能、选择后请求体包含所选标识
- [x] 5.2 用 `fetch` + `ReadableStream` 实现 SSE 解析与增量渲染，处理 `meta`（技能命中、`tool_calls` 状态）、`delta`、`done`、`error`，并用 `AbortController` 中止旧请求；验证回答逐段出现、`denied/error` 有可见标签
- [x] 5.3 为教师增加技能上传与删除区块（学生不渲染），上传错误直接展示服务端可读消息；浏览器验证教师可见、学生不可见、上传/删除生效
- [x] 5.4 调整问答门控交互以适配流式 `meta.gate`：显示继续/取消并在继续时以 `force=true` 重新请求；验证两种选择的行为

## 6. 集成与回归验证

- [x] 6.1 重建并重启 Compose，确认 `flask init-db` 建表、种子为 A 班补齐两份技能，且 `GET /api/kb/search` 与材料/MCP 管理接口保持原行为
- [x] 6.2 端到端验证技能 + MCP：教师登记并连接 `mcp-demo`，上传引用 `formula_hint@<班内服务器名>` 的技能，学生勾选后提问，SSE `meta.tool_calls` 显示 `ok` 且回答使用工具结果
- [x] 6.3 端到端验证失败路径：断开服务器后再次提问，`meta.tool_calls` 显示 `denied` 且问答继续；跨班技能标识返回 404；令牌不出现在任何响应或页面
- [x] 6.4 运行全量 `pytest` 与浏览器回归，确认检索、流式问答、技能管理、MCP 工具状态四部分均无控制台错误与既有功能回归
