"""Server-side authorization decorators (stateless JWT bearer auth).

These are the ONLY enforcement points; hiding UI elements is not security.
Every protected request must present `Authorization: Bearer <JWT>`.
- missing/malformed/expired/invalid token -> 401 JSON (distinct error codes)
- valid token whose user no longer exists   -> 401 JSON
- wrong role (e.g. student upload)          -> 403 JSON
Tokens are never accepted from query strings or cookies.
"""
from functools import wraps

from flask import current_app, g, jsonify, request

from ..db import db
from ..models import User
from .tokens import TokenError, TokenExpired, decode_token


def current_user():
    return getattr(g, "user", None)


def _unauthorized(code: str, message: str, status: int = 401):
    return jsonify(error=code, message=message), status


def _bearer_token() -> str | None:
    """Extract the token from the Authorization header only.

    Returns None when the header is absent or does not use the
    `Bearer <token>` scheme. Query parameters and cookies are never read.
    """
    header = request.headers.get("Authorization", "")
    parts = header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        token = _bearer_token()
        if token is None:
            return _unauthorized("unauthorized", "缺少或格式错误的访问令牌")

        try:
            payload = decode_token(token, current_app.config["SECRET_KEY"])
        except TokenExpired:
            return _unauthorized("token_expired", "访问令牌已过期，请重新登录")
        except TokenError:
            return _unauthorized("token_invalid", "访问令牌无效")

        try:
            user_id = int(payload["sub"])
        except (KeyError, TypeError, ValueError):
            return _unauthorized("token_invalid", "访问令牌声明无效")

        user = db.session.get(User, user_id)
        if user is None:
            return _unauthorized("user_not_found", "用户不存在或已被删除")

        g.user = user
        return view(*args, **kwargs)

    return wrapped


def role_required(role: str):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if user is None:
                return _unauthorized("unauthorized", "请先登录")
            if user.role != role:
                return jsonify(error="forbidden", message="无权执行该操作"), 403
            return view(*args, **kwargs)

        return wrapped

    return decorator
