"""JSON authentication API: register, login (issue JWT), current user."""
from flask import Blueprint, current_app, jsonify, request

from ..db import db
from ..models import Class, User
from ..security import hash_password, verify_password
from .decorators import current_user, login_required
from .tokens import issue_access_token

auth_bp = Blueprint("auth", __name__)

MIN_PASSWORD_LENGTH = 8
GENERIC_LOGIN_ERROR = "用户名或密码错误"


def _public_user(user: User) -> dict:
    return {
        "username": user.username,
        "role": user.role,
        "class": {"id": user.class_id, "name": user.class_.name},
    }


@auth_bp.get("/classes")
def list_classes():
    """Public class directory for the registration form (names only).

    The old server-rendered register page exposed the same list anonymously;
    registrations are still rejected server-side for unknown class ids.
    """
    classes = Class.query.order_by(Class.name).all()
    return jsonify(items=[{"id": c.id, "name": c.name} for c in classes])


@auth_bp.post("/register")
def register():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    role = data.get("role") or ""
    class_id_raw = data.get("class_id")

    errors = []
    if not (3 <= len(username) <= 50):
        errors.append("用户名长度需为 3-50 个字符")
    if len(password) < MIN_PASSWORD_LENGTH:
        errors.append(f"密码长度至少 {MIN_PASSWORD_LENGTH} 个字符")
    if role not in ("teacher", "student"):
        errors.append("角色无效")
    try:
        class_id = int(class_id_raw)
    except (TypeError, ValueError):
        class_id = None
        errors.append("请选择有效的班级")

    if username and User.query.filter_by(username=username).first():
        errors.append("用户名已被占用")
    if class_id is not None and not db.session.get(Class, class_id):
        errors.append("所选班级不存在")

    if errors:
        return jsonify(error="validation_error", messages=errors), 400

    user = User(
        username=username,
        password_hash=hash_password(password),
        role=role,
        class_id=class_id,
    )
    db.session.add(user)
    db.session.commit()
    # Registration never auto-issues a token; the client must log in.
    return jsonify(message="注册成功，请登录"), 201


@auth_bp.post("/login")
def login():
    """用户名密码登录并签发 Bearer 令牌。
    ---
    tags:
      - auth
    summary: 登录获取 JWT
    requestBody:
      required: true
      content:
        application/json:
          schema:
            type: object
            required: [username, password]
            properties:
              username:
                type: string
                example: teacher_a
              password:
                type: string
                format: password
                example: your-password
    responses:
      200:
        description: 登录成功
        content:
          application/json:
            schema:
              type: object
              properties:
                access_token:
                  type: string
                token_type:
                  type: string
                  example: Bearer
                expires_in:
                  type: integer
                  description: 有效期（秒）
                user:
                  type: object
      401:
        description: 用户名或密码错误
    """
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    user = User.query.filter_by(username=username).first()
    if user is None or not verify_password(user.password_hash, password):
        # One generic message: do not reveal whether the username exists.
        return jsonify(error="invalid_credentials", message=GENERIC_LOGIN_ERROR), 401

    token, expires_in = issue_access_token(
        user,
        current_app.config["SECRET_KEY"],
        current_app.config["JWT_ACCESS_TTL_MINUTES"],
    )
    return jsonify(
        access_token=token,
        token_type="Bearer",
        expires_in=expires_in,
        user=_public_user(user),
    )


@auth_bp.get("/me")
@login_required
def me():
    return jsonify(user=_public_user(current_user()))
