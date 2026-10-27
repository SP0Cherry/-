"""Preset prompt template texts for class A and their idempotent seed writer."""
from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from ..db import db
from ..models import Class, PromptTemplate, User
from .parser import parse_template_text

CONCLUSION_FIRST = """名称：结论先行讲解
描述：先给结论，再列依据要点，并标注资料出处
启用：是

请严格按以下方式组织回答：
1. 先用一句话给出结论。
2. 再分点列出依据要点，每点说明理由或来源。
3. 在引用本班资料处标注出处：{{sources}}
4. 本次参考的技能：{{skills}}
只做归纳，不要整段照抄资料原文。
"""

PRESET_TEMPLATES = (CONCLUSION_FIRST,)


def seed_class_a_templates() -> int:
    """Insert the preset templates for class A; skip existing names."""
    class_a = Class.query.filter_by(name="A班").first()
    teacher = User.query.filter_by(username="teacher_a").first()
    if class_a is None or teacher is None:
        return 0

    created = 0
    for text in PRESET_TEMPLATES:
        parsed = parse_template_text(text)
        existing = PromptTemplate.query.filter_by(
            class_id=class_a.id, name=parsed.name
        ).first()
        if existing is not None:
            continue
        db.session.add(
            PromptTemplate(
                class_id=class_a.id,
                name=parsed.name,
                description=parsed.description,
                body=parsed.body,
                enabled=parsed.enabled,
                created_by_id=teacher.id,
            )
        )
        created += 1

    if created:
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return 0
    return created