"""Parse teacher-uploaded prompt template text.

Structurally identical to ``app/skills/parser.py`` (metadata block, first blank
line separates the body, comments/leading blanks ignored, full/half-width colon,
character cap). The parser is a pure function: it only validates syntax and
field-level rules; class scope and duplicate checks live in the service layer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

MAX_TEMPLATE_CHARS = 8000
MAX_NAME_CHARS = 100
MAX_DESCRIPTION_CHARS = 255

ALLOWED_FIELDS = ("名称", "描述", "启用")
REQUIRED_FIELDS = ("名称", "启用")

# Any ``{{ ... }}`` span. Unknown names (and unclosed ``{{`` below) are rejected
# at save time so a rendered prompt can never leak an unreplaced placeholder.
PLACEHOLDER_PATTERN = re.compile(r"\{\{(.*?)\}\}")
ALLOWED_PLACEHOLDERS = ("question", "sources", "skills")


class TemplateParseError(ValueError):
    """Invalid template text with a teacher-readable Chinese message."""


@dataclass(frozen=True)
class ParsedTemplate:
    name: str
    description: str | None
    body: str
    enabled: bool
    placeholders: tuple[str, ...]


def find_placeholders(body: str) -> tuple[str, ...]:
    """Return the unique placeholder names used in ``body``, in order.

    Raises ``TemplateParseError`` for any unsupported or unclosed placeholder.
    """
    names: list[str] = []
    seen = set()
    for raw in PLACEHOLDER_PATTERN.findall(body):
        name = raw.strip()
        if name not in ALLOWED_PLACEHOLDERS:
            raise TemplateParseError(
                f"正文包含不支持的占位符「{{{{{raw}}}}}」；"
                f"仅支持：{'、'.join('{{' + item + '}}' for item in ALLOWED_PLACEHOLDERS)}"
            )
        if name not in seen:
            seen.add(name)
            names.append(name)

    if "{{" in PLACEHOLDER_PATTERN.sub("", body):
        raise TemplateParseError("正文包含未闭合的占位符“{{”，请检查模板正文")
    return tuple(names)


def _split_metadata_and_body(text: str) -> tuple[list[tuple[int, str]], str]:
    if not isinstance(text, str):
        raise TemplateParseError("模板文件内容必须是文本")

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if text.startswith("\ufeff"):
        text = text[1:]

    if len(text) > MAX_TEMPLATE_CHARS:
        raise TemplateParseError(
            f"模板文件不能超过 {MAX_TEMPLATE_CHARS} 个字符（当前 {len(text)} 个）"
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
        raise TemplateParseError("模板文件缺少元数据，请先填写“名称”“启用”")

    metadata: list[tuple[int, str]] = []
    body_lines: list[str] | None = None
    for index in range(start, len(lines)):
        line = lines[index]
        if not line.strip():
            # The first blank line after metadata starts the template body.
            body_lines = lines[index + 1 :]
            break
        if line.strip().startswith("#"):
            continue
        metadata.append((index + 1, line))

    if body_lines is None:
        raise TemplateParseError("元数据后必须有一个空行，空行之后是模板正文")

    body = "\n".join(body_lines).strip()
    if not body:
        raise TemplateParseError("空行之后缺少模板正文")
    return metadata, body


def parse_template_text(text: str) -> ParsedTemplate:
    metadata, body = _split_metadata_and_body(text)

    values: dict[str, str] = {}
    for line_no, line in metadata:
        positions = [pos for pos in (line.find("："), line.find(":")) if pos >= 0]
        if not positions:
            raise TemplateParseError(
                f"第 {line_no} 行格式错误：应为「字段：值」，"
                "字段名和值之间使用全角或半角冒号"
            )
        position = min(positions)
        field = line[:position].strip()
        value = line[position + 1 :].strip()

        if field not in ALLOWED_FIELDS:
            raise TemplateParseError(
                f"第 {line_no} 行出现未支持的字段「{field}」；"
                f"仅支持：{'、'.join(ALLOWED_FIELDS)}"
            )
        if field in values:
            raise TemplateParseError(f"字段「{field}」重复出现（第 {line_no} 行）")
        values[field] = value

    missing = [field for field in REQUIRED_FIELDS if not values.get(field, "")]
    if missing:
        raise TemplateParseError(f"缺少必填字段：{'、'.join(missing)}")

    name = values["名称"]
    if len(name) > MAX_NAME_CHARS:
        raise TemplateParseError(f"名称不能超过 {MAX_NAME_CHARS} 个字符")

    description = values.get("描述") or None
    if description is not None and len(description) > MAX_DESCRIPTION_CHARS:
        raise TemplateParseError(
            f"描述不能超过 {MAX_DESCRIPTION_CHARS} 个字符"
        )

    enabled_text = values["启用"]
    if enabled_text == "是":
        enabled = True
    elif enabled_text == "否":
        enabled = False
    else:
        raise TemplateParseError("启用字段只接受「是」或「否」")

    return ParsedTemplate(
        name=name,
        description=description,
        body=body,
        enabled=enabled,
        placeholders=find_placeholders(body),
    )