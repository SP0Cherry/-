"""Parse teacher-uploaded SKILL.md text.

The parser is a pure function: it only validates syntax and field-level rules.
MCP server existence / connection / tool-cache checks live in the service layer
because they need the database.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

MAX_SKILL_CHARS = 8000
MAX_NAME_CHARS = 100
MAX_SUBJECT_CHARS = 50
MAX_SERVER_CHARS = 50

ALLOWED_FIELDS = ("名称", "适用条件", "资料", "工具", "启用")
REQUIRED_FIELDS = ("名称", "适用条件", "启用")

_MULTI_VALUE_SEPARATOR = re.compile(r"[,，、;；]")
_TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class SkillParseError(ValueError):
    """Invalid SKILL.md with a teacher-readable Chinese message."""


@dataclass(frozen=True)
class ParsedSkill:
    name: str
    keywords: tuple[str, ...]
    subject: str | None
    tools: tuple[dict[str, Any], ...]
    body: str
    enabled: bool


def _split_multi(value: str) -> list[str]:
    parts = [part.strip() for part in _MULTI_VALUE_SEPARATOR.split(value)]
    seen = set()
    result = []
    for part in parts:
        if not part or part in seen:
            continue
        seen.add(part)
        result.append(part)
    return result


def _parse_tools(value: str) -> tuple[dict[str, Any], ...]:
    if not value.strip():
        return ()

    tools: list[dict[str, Any]] = []
    seen = set()
    for raw in _split_multi(value):
        if raw == "knowledge_search":
            key = ("builtin", "knowledge_search")
            if key not in seen:
                seen.add(key)
                tools.append({"kind": "builtin", "name": "knowledge_search"})
            continue

        if raw.count("@") != 1:
            raise SkillParseError(
                f"工具引用「{raw}」格式错误：应为 工具名@服务器名，"
                "或使用内置工具 knowledge_search"
            )
        tool_name, server_name = (part.strip() for part in raw.split("@", 1))
        if not _TOOL_NAME_PATTERN.fullmatch(tool_name):
            raise SkillParseError(
                f"工具名「{tool_name}」不合法：必须以小写字母开头，"
                "且只能包含小写字母、数字和下划线"
            )
        if not server_name:
            raise SkillParseError(f"工具引用「{raw}」缺少服务器名")
        if len(server_name) > MAX_SERVER_CHARS:
            raise SkillParseError(
                f"工具引用「{raw}」的服务器名不能超过 {MAX_SERVER_CHARS} 个字符"
            )

        key = ("mcp", tool_name, server_name)
        if key not in seen:
            seen.add(key)
            tools.append(
                {"kind": "mcp", "tool": tool_name, "server": server_name}
            )
    return tuple(tools)


def _split_metadata_and_body(text: str) -> tuple[list[tuple[int, str]], str]:
    if not isinstance(text, str):
        raise SkillParseError("技能文件内容必须是文本")

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if text.startswith("\ufeff"):
        text = text[1:]

    if len(text) > MAX_SKILL_CHARS:
        raise SkillParseError(
            f"技能文件不能超过 {MAX_SKILL_CHARS} 个字符（当前 {len(text)} 个）"
        )

    lines = text.split("\n")

    # Leading blank lines and comment lines before the first metadata field are
    # ignored, so a file may start with a short explanatory comment.
    start = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        start = index
        break
    if start is None:
        raise SkillParseError("技能文件缺少元数据，请先填写“名称”“适用条件”“启用”")

    metadata: list[tuple[int, str]] = []
    body_lines: list[str] | None = None
    for index in range(start, len(lines)):
        line = lines[index]
        if not line.strip():
            # The first blank line after metadata starts the guidance body.
            body_lines = lines[index + 1 :]
            break
        if line.strip().startswith("#"):
            continue
        metadata.append((index + 1, line))

    if body_lines is None:
        raise SkillParseError("元数据后必须有一个空行，空行之后是引导规程正文")

    body = "\n".join(body_lines).strip()
    if not body:
        raise SkillParseError("空行之后缺少引导规程正文")
    return metadata, body


def parse_skill_text(text: str) -> ParsedSkill:
    metadata, body = _split_metadata_and_body(text)

    values: dict[str, str] = {}
    for line_no, line in metadata:
        positions = [pos for pos in (line.find("："), line.find(":")) if pos >= 0]
        if not positions:
            raise SkillParseError(
                f"第 {line_no} 行格式错误：应为「字段：值」，"
                "字段名和值之间使用全角或半角冒号"
            )
        position = min(positions)
        field = line[:position].strip()
        value = line[position + 1 :].strip()

        if field not in ALLOWED_FIELDS:
            raise SkillParseError(
                f"第 {line_no} 行出现未支持的字段「{field}」；"
                f"仅支持：{'、'.join(ALLOWED_FIELDS)}"
            )
        if field in values:
            raise SkillParseError(f"字段「{field}」重复出现（第 {line_no} 行）")
        values[field] = value

    missing = [field for field in REQUIRED_FIELDS if not values.get(field, "")]
    if missing:
        raise SkillParseError(f"缺少必填字段：{'、'.join(missing)}")

    name = values["名称"]
    if len(name) > MAX_NAME_CHARS:
        raise SkillParseError(f"名称不能超过 {MAX_NAME_CHARS} 个字符")

    keywords = _split_multi(values["适用条件"])
    if not keywords:
        raise SkillParseError("适用条件必须包含至少一个关键词")

    enabled_text = values["启用"]
    if enabled_text == "是":
        enabled = True
    elif enabled_text == "否":
        enabled = False
    else:
        raise SkillParseError("启用字段只接受「是」或「否」")

    subject = values.get("资料") or None
    if subject is not None and len(subject) > MAX_SUBJECT_CHARS:
        raise SkillParseError(f"资料不能超过 {MAX_SUBJECT_CHARS} 个字符")

    return ParsedSkill(
        name=name,
        keywords=tuple(keywords),
        subject=subject,
        tools=_parse_tools(values.get("工具", "")),
        body=body,
        enabled=enabled,
    )
