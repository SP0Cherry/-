"""Prompt template persistence, teacher-facing validation and ask-time selection."""
from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from ..db import db
from ..models import PromptTemplate
from .parser import find_placeholders, parse_template_text


class TemplateDuplicateError(ValueError):
    """The same template name already exists in this class."""


class TemplateSelectionError(ValueError):
    status_code = 400
    error_code = "bad_request"


class TemplateNotFoundError(TemplateSelectionError):
    status_code = 404
    error_code = "not_found"


class TemplateDisabledError(TemplateSelectionError):
    status_code = 400
    error_code = "template_disabled"


def serialize_template(template: PromptTemplate, *, include_body: bool) -> dict:
    """Public representation: metadata plus placeholders derived from the body."""
    data = {
        "id": template.id,
        "name": template.name,
        "description": template.description,
        "placeholders": list(find_placeholders(template.body)),
        "enabled": bool(template.enabled),
        "created_at": template.created_at.isoformat(),
    }
    if include_body:
        data["body"] = template.body
    return data


def create_template(user, text: str) -> PromptTemplate:
    parsed = parse_template_text(text)

    existing = PromptTemplate.query.filter_by(
        class_id=user.class_id, name=parsed.name
    ).first()
    if existing is not None:
        raise TemplateDuplicateError(f"本班已存在名为「{parsed.name}」的模板")

    template = PromptTemplate(
        class_id=user.class_id,
        name=parsed.name,
        description=parsed.description,
        body=parsed.body,
        enabled=parsed.enabled,
        created_by_id=user.id,
    )
    db.session.add(template)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise TemplateDuplicateError(
            f"本班已存在名为「{parsed.name}」的模板"
        ) from None
    return template


def list_templates(user) -> list[PromptTemplate]:
    query = PromptTemplate.query.filter_by(class_id=user.class_id)
    if not user.is_teacher:
        query = query.filter_by(enabled=True)
    return query.order_by(PromptTemplate.id.asc()).all()


def delete_template(user, template_id: int) -> bool:
    template = PromptTemplate.query.filter_by(
        id=template_id, class_id=user.class_id
    ).first()
    if template is None:
        return False
    db.session.delete(template)
    db.session.commit()
    return True


def select_for_ask(user, template_id):
    """Validate the selected template id against the acting user's class."""
    if template_id is None:
        return None
    if isinstance(template_id, bool) or not isinstance(template_id, int):
        raise TemplateSelectionError("template_id 必须是整数")

    template = PromptTemplate.query.filter_by(
        id=template_id, class_id=user.class_id
    ).first()
    if template is None:
        # Unknown and cross-class ids are indistinguishable by design.
        raise TemplateNotFoundError("模板不存在")
    if not template.enabled:
        raise TemplateDisabledError(
            f"模板「{template.name}」已停用，无法用于提问"
        )
    return template