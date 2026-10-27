# knowledge-qa Specification

## Purpose

定义班级知识问答的流式响应契约：在回答生成前通过 `meta` 事件暴露检索结果、技能命中与 MCP 工具调用状态，随后以增量事件返回回答，并继续遵守班级边界与“无资料继续提问”门控。

## Requirements

### Requirement: SSE 流式问答响应

`POST /api/kb/ask` MUST 返回 `text/event-stream` 流式响应，并使用 Bearer 鉴权。流开始前发生的鉴权、参数校验与依赖错误 MUST 仍以明确的 JSON 错误状态返回（401/400/503/502）；流一旦开始，错误 MUST 通过 `error` 事件返回可读信息。

请求体 MAY 携带一个可选的模板标识 `template_id`；其校验失败 MUST 按请求级 JSON 错误返回（未知/跨班 404、停用 400、类型非法 400），MUST NOT 建立 SSE 流。

流 MUST 按以下顺序发送事件：

1. `meta`：首个事件，MUST 包含 `retrieved`、`sources`、`skills`、`tool_calls` 与 `template`；`skills` 每项至少包含技能标识、名称与 `hit`；`tool_calls` 每项至少包含工具引用、工具名、服务器名（内置工具可为空）与状态 `ok`、`denied` 或 `error`，非 `ok` 时 SHOULD 包含可读原因；`template` MUST 为本次实际应用的模板 `{id, name}`，未选择或未应用时为 `null`。
2. `delta`：一个或多个回答文本增量，内容 MUST 按顺序拼接后构成完整回答。
3. `done`：结束事件。

若检索未命中且请求未强制继续，流 MUST 在 `meta` 中标记 `retrieved=false` 与 `gate=true`，随后直接发送 `done`，MUST NOT 生成回答增量。若请求强制继续，则按原行为生成不依据本班资料的回答。聊天服务在流中失败时 MUST 发送 `error` 事件，而不是静默结束。

#### Scenario: 正常流式回答

- **WHEN** 已登录学生提交有本班资料命中的问题
- **THEN** 客户端先收到 `meta`，再收到一个或多个 `delta`，最后收到 `done`；拼接后的文本即完整回答

#### Scenario: 工具状态先于回答可见

- **WHEN** 问题命中带 MCP 工具的技能
- **THEN** `meta.tool_calls` 在首个事件中列出每个工具引用及其 `ok`/`denied`/`error` 状态，且任何 `delta` 都不早于该 `meta`

#### Scenario: 模板信息在 meta 中可见

- **WHEN** 提问时携带了本班已启用模板标识
- **THEN** 首个 `meta` 事件的 `template` 字段包含该模板的标识与名称

#### Scenario: 未选择模板时 meta 标记为空

- **WHEN** 提问时未携带模板标识
- **THEN** `meta.template` 为 `null`，事件顺序与既有契约一致

#### Scenario: 未命中资料的继续提问门控

- **WHEN** 检索未命中且请求未设置强制继续
- **THEN** `meta` 标记 `retrieved=false`、`gate=true`，流只包含 `meta` 与 `done`，不生成回答增量

#### Scenario: 强制继续时不依据资料回答

- **WHEN** 检索未命中但请求设置强制继续
- **THEN** 系统生成回答增量，并保持原有“不依据本班课程资料”的提示语义

#### Scenario: 流开始后的上游失败

- **WHEN** 首个事件已发送后聊天服务失败
- **THEN** 客户端收到可读的 `error` 事件，连接正常结束

#### Scenario: 鉴权或参数错误仍是 JSON

- **WHEN** 请求缺少有效 Bearer 令牌、问题为空、问题超长，或 `template_id` 未知、跨班、已停用或类型非法
- **THEN** 系统返回对应的 401/400/404 JSON 错误，不建立 SSE 流

### Requirement: 流式问答沿用班级边界与既有检索

流式问答 MUST 从服务端登录身份确定班级，MUST NOT 接受请求体、查询串或表单中的班级标识。检索 MUST 与知识检索接口使用同一套班级过滤、相似度阈值与排序规则；`sources` MUST 只包含当前用户班级的材料，跨班材料 MUST NOT 出现在 `meta` 或回答依据中。

`GET /api/kb/search` MUST 保持现有 JSON 行为不变，流式改造 MUST NOT 改变其响应结构与检索语义。

#### Scenario: 其他班级资料不进入来源

- **WHEN** A 班学生提问，数据库中同时存在 A 班与 B 班材料
- **THEN** `meta.sources` 只包含 A 班材料，回答依据中不出现 B 班内容

#### Scenario: 伪造班级字段无效

- **WHEN** 学生提问时在请求体中附带其他班级标识
- **THEN** 系统忽略该字段，仍只使用会话所属班级

#### Scenario: 检索接口保持兼容

- **WHEN** 已登录用户调用 `GET /api/kb/search`
- **THEN** 系统仍返回原有 JSON 结构，不受流式接口改造影响

### Requirement: 前端展示流式回答与工具状态

问答界面 MUST 提供本班已启用技能的勾选入口，并在提交时把所选技能标识随请求发送。回答区域 MUST 在收到增量时逐步追加文本；`meta.tool_calls` 中状态为 `denied` 或 `error` 的引用 MUST 以可读状态展示，MUST NOT 让用户误以为调用成功。

流式请求失败、`error` 事件或网络中断时，界面 MUST 显示可读错误，并允许用户重新提问。学生界面 MUST NOT 展示技能上传或删除入口。

#### Scenario: 勾选技能后提问

- **WHEN** 学生在问答模式勾选本班技能并提交问题
- **THEN** 界面显示逐段出现的回答，并在工具调用存在时显示对应状态

#### Scenario: 越权或未连接状态可见

- **WHEN** `meta.tool_calls` 中某项状态为 `denied`
- **THEN** 界面明确显示该工具引用被拒绝，而不是显示为成功

#### Scenario: 流式错误可恢复

- **WHEN** 流式请求返回 `error` 事件或连接中断
- **THEN** 界面显示错误信息，用户可修改问题后再次提交

#### Scenario: 学生看不到技能管理入口

- **WHEN** 学生登录并进入问答界面
- **THEN** 界面不显示技能上传、删除或连接 MCP 服务器等教师操作入口
