"""Preset SKILL.md texts for class A and their idempotent seed writer."""
from __future__ import annotations

import json

from sqlalchemy.exc import IntegrityError

from ..db import db
from ..models import Class, Skill, User
from .parser import parse_skill_text

MATH_SKILL = """名称：数学解题引导
适用条件：方程,去括号,分数,通分,面积,应用题,未知数,行程
资料：数学
工具：knowledge_search
启用：是

学生正在自己做数学作业，往往已经写了一步。先看懂他卡在哪一步，只指出下一步该检查什么，例如去括号有没有乘到每一项、分母不同要不要先通分、该设哪个未知数。不要算出最终得数，不要把整道题做完。依据只用数学自学笔记，并标出材料标题和位置。
"""

CHINESE_SKILL = """名称：语文解题引导
适用条件：春晓,默写,阅读,中心,作文,开头,古诗,词语
资料：语文
工具：knowledge_search
启用：是

学生正在自己背诵、做阅读或改作文，卡在某一句。先接住他已经写出的那一句，告诉他往前看哪一句、找哪类句子。不要把诗的下一句、中心句或改好的段落直接写出来。依据只用语文自学笔记，并标出材料标题和位置。
"""

PRESET_SKILLS = (MATH_SKILL, CHINESE_SKILL)


def seed_class_a_skills() -> int:
    """Insert the two preset skills for class A; skip existing names."""
    class_a = Class.query.filter_by(name="A班").first()
    teacher = User.query.filter_by(username="teacher_a").first()
    if class_a is None or teacher is None:
        return 0

    created = 0
    for text in PRESET_SKILLS:
        parsed = parse_skill_text(text)
        existing = Skill.query.filter_by(
            class_id=class_a.id, name=parsed.name
        ).first()
        if existing is not None:
            continue
        db.session.add(
            Skill(
                class_id=class_a.id,
                name=parsed.name,
                subject=parsed.subject,
                keywords_json=json.dumps(
                    list(parsed.keywords), ensure_ascii=False
                ),
                tools_json=json.dumps(
                    list(parsed.tools), ensure_ascii=False
                ),
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
