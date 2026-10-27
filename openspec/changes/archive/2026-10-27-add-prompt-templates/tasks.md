## 1. 数据模型与模板解析渲染

- [x] 1.1 在 `app/models.py` 新增班级级 `PromptTemplate` 模型（名称、描述、正文、启用、创建者、创建时间，`UniqueConstraint("class_id","name")`），并在 `Class` 上建立 `prompt_templates` 关系（`cascade="all, delete-orphan"`）；验证 `flask init-db` 后 `prompt_templates` 表存在且班内唯一约束生效
- [x] 1.2 新增 `app/prompt_templates/parser.py`，实现元数据/正文分割、`#` 注释与开头空行忽略、全/半角冒号、8000 字上限、必填字段（`名称`、`启用`）、重复/未定义字段、缺少正文校验；验证单测覆盖合法文件与每个拒绝场景
- [x] 1.3 在解析器中实现占位符校验：仅允许 `{{question}}`、`{{sources}}`、`{{skills}}`，正文出现其他 `{{...}}` 占位符时抛可读中文错误；验证合法占位符通过、`{{date}}`/`{{answer}}` 被拒绝的单测
- [x] 1.4 新增模板渲染函数（`render_template(body, question, sources, skills)`）：`{{question}}` 替换为问题原文、`{{sources}}` 渲染为引用列表（材料名+标题+行号，不含全片段）、`{{skills}}` 渲染为命中技能名（无命中为 `（无）`）；验证渲染结果不含未替换的 `{{` 残留且无内容时渲染为"无"的单测

## 2. 模板服务与教师管理 API

- [x] 2.1 新增 `app/prompt_templates/service.py`：`create_template`（解析 → 班内重名 → 入库）、`delete_template`（班级作用域）、`list_templates`（教师全部/学生仅启用）、`serialize_template(template, include_body)`（含实时推导的 `placeholders`）；验证重名与跨班删除返回可读结果
- [x] 2.2 在服务层实现 `select_for_ask(user, template_id)`：`None` 返回 `None`；非整数（含 `bool`）→ 400；未知/跨班 → 404；已停用 → 400；验证各类错误的单测
- [x] 2.3 新增 `app/prompt_templates/routes.py` 并注册蓝图：`GET /api/prompt-templates`（教师含 `body`、学生不含且仅启用）、`POST /api/prompt-templates`（教师 multipart `file`，UTF-8）、`DELETE /api/prompt-templates/<id>`（教师、班级作用域）；验证 201/400/403/409/404 各状态码
- [x] 2.4 验证学生调用创建/删除接口返回 403、跨班读取/删除返回 404，且学生列表响应不含模板正文

## 3. 种子预置模板

- [x] 3.1 新增 `app/prompt_templates/presets.py`，提供 A 班一份合法模板文本（含 `名称`、`描述`、`启用：是`，正文使用 `{{sources}}` 与 `{{skills}}` 并约束"先给结论再列要点、标注出处"）；验证该文本能通过解析器
- [x] 3.2 在 `app/seed.py` 的 `seed_class_a_skills()` 之后调用 `seed_class_a_templates()`，按 `(class_id, name)` 幂等写入；验证首次写入一份、重复执行数量不变、B 班为空

## 4. 问答集成与 SSE 契约

- [x] 4.1 扩展 `app/kb/service.py::prepare()` 接收 `template_id`，调用 `select_for_ask` 校验，并通过新增的 `_template_section()` 把渲染后的模板作为**附加规程**追加到 `_grounded_prompt` 与 `_forced_prompt` 的 system 之后（顺序：基础规程 → 技能规程 → 模板规程）；验证基础规程文字未被改写、模板段位于其后
- [x] 4.2 在 `prepare()` 的 `meta` 中新增 `template` 字段（`{id, name}` 或 `null`），并确保门控（`gate=true`）时仍返回所选模板信息且不生成任何回答内容；验证未选模板时 `meta.template` 为 `null` 且行为与现状一致
- [x] 4.3 在 `app/kb/routes.py::kb_ask` 读取请求体 `template_id`，校验失败在建立 SSE 前返回 JSON 404/400，成功则把模板信息随首个 `meta` 事件下发；验证 401/400/404 仍为 JSON、事件顺序为 `meta`→`delta`→`done`
- [x] 4.4 新增/扩展测试覆盖：模板叠加不削弱基础约束（工具输出仍只进 user 数据区块）、门控不因模板改变、跨班模板 404、停用模板 400；验证全量 `pytest` 通过且 `test_kb_api.py`、`test_skill_ask.py` 无回归

## 5. 前端模板选择与教师管理

- [x] 5.1 在 `app/static/kb.html`/`kb.js` 增加**模板单选**入口（含"不使用模板"，默认不选），提交时携带 `template_id`；验证未选时请求体不含模板、选择后请求体包含所选标识
- [x] 5.2 在 `meta` 渲染逻辑中展示本次使用的模板名称（`meta.template` 非空时），并保持既有技能命中与 `tool_calls` 状态展示不变；验证回答区上方可见模板名
- [x] 5.3 为教师增加"模板管理（教师）"区块（上传/删除/列表，展示 `描述` 与 `placeholders`，复用现有样式），学生端不渲染；验证教师可见并可上传/删除、学生不可见且上传错误显示服务端可读消息
- [x] 5.4 浏览器验证：选中模板后提问得到按模板规程组织的回答；停用模板不出现在学生列表；跨班模板标识被拒绝且界面显示可读错误

## 6. 集成与回归验证

- [x] 6.1 重建并重启 Compose，确认 `flask init-db` 建表、种子为 A 班补齐一份模板，且 `GET /api/kb/search`、材料/技能/MCP 管理接口保持原行为
- [x] 6.2 端到端验证：A 班教师上传模板 → A 班学生选中并提问（有检索命中）→ 回答遵循模板附加规程且 `meta.template` 正确；B 班学生看不到该模板
- [x] 6.3 端到端验证失败路径：未命中资料时门控仍只返回 `meta`+`done`；选择停用/跨班模板返回 400/404；工具输出中的指令式文本仍不进入 system
- [x] 6.4 运行全量 `pytest` 与浏览器回归，确认检索、流式问答、技能、MCP 工具状态与新增模板五部分均无控制台错误与既有功能回归