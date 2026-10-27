"""Prompt template management API (teacher upload/delete, class-scoped listing)."""
from flask import Blueprint, jsonify, request

from ..auth.decorators import current_user, login_required, role_required
from . import service
from .parser import TemplateParseError

prompt_templates_bp = Blueprint("prompt_templates", __name__)


def _error(code: str, message: str, status: int):
    return jsonify(error=code, message=message), status


@prompt_templates_bp.get("/prompt-templates")
@login_required
def list_prompt_templates():
    """列出本班提示词模板。
    ---
    tags:
      - prompt-templates
    summary: 列出本班模板
    description: 教师返回本班全部模板（含正文），学生仅返回已启用模板（不含正文）。
    security:
      - bearerAuth: []
    responses:
      200:
        description: 模板列表
        content:
          application/json:
            schema:
              type: object
              properties:
                items:
                  type: array
                  items:
                    $ref: '#/components/schemas/PromptTemplate'
      401:
        description: 未认证
    """
    user = current_user()
    return jsonify(
        items=[
            service.serialize_template(
                template, include_body=user.is_teacher
            )
            for template in service.list_templates(user)
        ]
    )


@prompt_templates_bp.post("/prompt-templates")
@login_required
@role_required("teacher")
def upload_prompt_template():
    """教师上传提示词模板文件。
    ---
    tags:
      - prompt-templates
    summary: 上传模板文件
    description: 仅教师可用；元数据支持「名称、描述、启用」，正文支持固定占位符。
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
                description: UTF-8 编码的模板文本文件
    responses:
      201:
        description: 上传成功
        content:
          application/json:
            schema:
              type: object
              properties:
                template:
                  $ref: '#/components/schemas/PromptTemplate'
      400:
        description: 文件缺失、编码错误或模板内容不合法
      401:
        description: 未认证
      403:
        description: 学生无权上传
      409:
        description: 本班已存在同名模板
    """
    upload = request.files.get("file")
    if upload is None:
        return _error("bad_request", "请选择模板文件（multipart 字段名 file）", 400)

    try:
        text = upload.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        return _error("invalid_template", "模板文件必须是 UTF-8 编码的纯文本", 400)

    try:
        template = service.create_template(current_user(), text)
    except TemplateParseError as error:
        return _error("invalid_template", str(error), 400)
    except service.TemplateDuplicateError as error:
        return _error("conflict", str(error), 409)

    return (
        jsonify(template=service.serialize_template(template, include_body=True)),
        201,
    )


@prompt_templates_bp.delete("/prompt-templates/<int:template_id>")
@login_required
@role_required("teacher")
def delete_prompt_template(template_id: int):
    """教师删除本班提示词模板。
    ---
    tags:
      - prompt-templates
    summary: 删除模板
    security:
      - bearerAuth: []
    parameters:
      - in: path
        name: template_id
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
        description: 模板不存在或不属于本班
    """
    if not service.delete_template(current_user(), template_id):
        return _error("not_found", "模板不存在", 404)
    return jsonify(deleted=True)