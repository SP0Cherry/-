"""Skill management API (teacher upload/delete, class-scoped listing)."""
from flask import Blueprint, jsonify, request

from ..auth.decorators import current_user, login_required, role_required
from . import service
from .parser import SkillParseError

skills_bp = Blueprint("skills", __name__)


def _error(code: str, message: str, status: int):
    return jsonify(error=code, message=message), status


@skills_bp.get("/skills")
@login_required
def list_skills():
    """列出本班可用技能（不包含技能正文）。
    ---
    tags:
      - skills
    summary: 列出本班技能
    security:
      - bearerAuth: []
    responses:
      200:
        description: 技能列表
        content:
          application/json:
            schema:
              type: object
              properties:
                items:
                  type: array
                  items:
                    $ref: '#/components/schemas/Skill'
      401:
        description: 未认证
    """
    return jsonify(
        items=[service.serialize_skill(skill) for skill in service.list_skills(current_user())]
    )


@skills_bp.post("/skills")
@login_required
@role_required("teacher")
def upload_skill():
    """教师上传 SKILL.md 技能文件。
    ---
    tags:
      - skills
    summary: 上传技能文件
    description: 仅教师可用；绑定的 MCP 工具必须属于本班且已连接。
    security:
      - bearerAuth: []
    requestBody:
      required: true
      content:
        multipart/form-data:
          schema:
            type: object
            required: [file]
            properties:
              file:
                type: string
                format: binary
                description: UTF-8 编码的 SKILL.md 文本文件
    responses:
      201:
        description: 上传成功
        content:
          application/json:
            schema:
              type: object
              properties:
                skill:
                  $ref: '#/components/schemas/Skill'
      400:
        description: 文件缺失、编码错误或技能内容不合法
      401:
        description: 未认证
      403:
        description: 学生无权上传
      409:
        description: 本班已存在同名技能
    """
    upload = request.files.get("file")
    if upload is None:
        return _error("bad_request", "请选择技能文件（multipart 字段名 file）", 400)

    try:
        text = upload.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        return _error("invalid_skill", "技能文件必须是 UTF-8 编码的纯文本", 400)

    try:
        skill = service.create_skill(current_user(), text)
    except SkillParseError as error:
        return _error("invalid_skill", str(error), 400)
    except service.SkillBindingError as error:
        return _error("invalid_skill", str(error), 400)
    except service.SkillDuplicateError as error:
        return _error("conflict", str(error), 409)

    return jsonify(skill=service.serialize_skill(skill)), 201


@skills_bp.delete("/skills/<int:skill_id>")
@login_required
@role_required("teacher")
def delete_skill(skill_id: int):
    """教师删除本班技能。
    ---
    tags:
      - skills
    summary: 删除技能
    security:
      - bearerAuth: []
    parameters:
      - in: path
        name: skill_id
        required: true
        schema:
          type: integer
    responses:
      200:
        description: 已删除
      401:
        description: 未认证
      403:
        description: 学生无权删除
      404:
        description: 技能不存在或不属于本班
    """
    if not service.delete_skill(current_user(), skill_id):
        return _error("not_found", "技能不存在", 404)
    return jsonify(deleted=True)
