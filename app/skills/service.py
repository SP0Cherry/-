"""Skill persistence, teacher-facing validation and ask-time selection."""
from __future__ import annotations

import json

from sqlalchemy.exc import IntegrityError

from ..db import db
from ..mcp import service as mcp_service
from ..models import Skill
from .parser import ParsedSkill, parse_skill_text

MAX_SELECTED_SKILLS = 20

TOOL_SEPARATOR = "、"


class SkillDuplicateError(ValueError):
    """The same skill name already exists in this class."""


class SkillBindingError(ValueError):
    """An MCP tool reference cannot be resolved in this class."""


class SkillSelectionError(ValueError):
    status_code = 400
    error_code = "bad_request"


class SkillNotFoundError(SkillSelectionError):
    status_code = 404
    error_code = "not_found"


class SkillDisabledError(SkillSelectionError):
    status_code = 400
    error_code = "skill_disabled"


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _load_list(raw: str) -> list:
    try:
        value = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def skill_tools(skill: Skill) -> list[dict]:
    return [item for item in _load_list(skill.tools_json) if isinstance(item, dict)]


def tool_ref(tool: dict) -> str:
    if tool.get("kind") == "builtin":
        return str(tool.get("name") or "")
    return f"{tool.get('tool')}@{tool.get('server')}"


def serialize_skill(skill: Skill) -> dict:
    """Public representation: no bearer token and no guidance body."""
    return {
        "id": skill.id,
        "name": skill.name,
        "subject": skill.subject,
        "keywords": _load_list(skill.keywords_json),
        "tools": [tool_ref(tool) for tool in skill_tools(skill)],
        "enabled": bool(skill.enabled),
        "created_at": skill.created_at.isoformat(),
    }


def _validate_bindings(user, parsed: ParsedSkill) -> None:
    for tool in parsed.tools:
        if tool.get("kind") != "mcp":
            continue
        server_name = tool.get("server") or ""
        tool_name = tool.get("tool") or ""
        server = mcp_service.find_server(user.class_id, server_name)
        if server is None:
            raise SkillBindingError(
                f"本班未登记 MCP 服务器「{server_name}」，"
                f"无法绑定工具「{tool_name}」"
            )
        if not server.is_connected:
            raise SkillBindingError(
                f"MCP 服务器「{server_name}」尚未连接，"
                "请先连接服务器并缓存工具清单"
            )
        if mcp_service.cached_tool(server, tool_name) is None:
            raise SkillBindingError(
                f"工具「{tool_name}」尚未出现在服务器「{server_name}」"
                "的工具发现缓存中"
            )


def create_skill(user, text: str) -> Skill:
    parsed = parse_skill_text(text)

    existing = Skill.query.filter_by(
        class_id=user.class_id, name=parsed.name
    ).first()
    if existing is not None:
        raise SkillDuplicateError(f"本班已存在名为「{parsed.name}」的技能")

    _validate_bindings(user, parsed)

    skill = Skill(
        class_id=user.class_id,
        name=parsed.name,
        subject=parsed.subject,
        keywords_json=_dump(list(parsed.keywords)),
        tools_json=_dump(list(parsed.tools)),
        body=parsed.body,
        enabled=parsed.enabled,
        created_by_id=user.id,
    )
    db.session.add(skill)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise SkillDuplicateError(f"本班已存在名为「{parsed.name}」的技能") from None
    return skill


def list_skills(user) -> list[Skill]:
    query = Skill.query.filter_by(class_id=user.class_id)
    if not user.is_teacher:
        query = query.filter_by(enabled=True)
    return query.order_by(Skill.id.asc()).all()


def delete_skill(user, skill_id: int) -> bool:
    skill = Skill.query.filter_by(
        id=skill_id, class_id=user.class_id
    ).first()
    if skill is None:
        return False
    db.session.delete(skill)
    db.session.commit()
    return True


def select_for_ask(user, skill_ids) -> list[Skill]:
    """Validate selected ids: class scope, enabled state, order, limit."""
    if skill_ids is None:
        return []
    if not isinstance(skill_ids, list):
        raise SkillSelectionError("skill_ids 必须是技能标识数组")

    ordered: list[int] = []
    seen = set()
    for value in skill_ids:
        if isinstance(value, bool) or not isinstance(value, int):
            raise SkillSelectionError("skill_ids 中的每一项都必须是整数")
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)

    if len(ordered) > MAX_SELECTED_SKILLS:
        raise SkillSelectionError(
            f"一次最多选择 {MAX_SELECTED_SKILLS} 个技能"
        )
    if not ordered:
        return []

    found = {
        skill.id: skill
        for skill in Skill.query.filter(
            Skill.class_id == user.class_id, Skill.id.in_(ordered)
        ).all()
    }
    if len(found) != len(ordered):
        # Cross-class ids and unknown ids are indistinguishable by design.
        raise SkillNotFoundError("技能不存在")

    selected = []
    for skill_id in ordered:
        skill = found[skill_id]
        if not skill.enabled:
            raise SkillDisabledError(f"技能「{skill.name}」已停用，无法用于提问")
        selected.append(skill)
    return selected


def matches_question(skill: Skill, question: str) -> bool:
    folded = question.casefold()
    for keyword in _load_list(skill.keywords_json):
        if isinstance(keyword, str) and keyword and keyword.casefold() in folded:
            return True
    return False
