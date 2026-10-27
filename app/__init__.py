"""CampusClaw Flask application factory.

The backend exposes stateless JWT-protected JSON APIs under /api and serves a
public, data-free static HTML/JS shell at /, /login, /register. All business
data is fetched by the shell with an Authorization: Bearer token.
"""
import os

from flask import (
    Flask,
    jsonify,
    request,
    send_from_directory,
)
import flasgger
from flasgger import Swagger
from sqlalchemy import event
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from .config import Config
from .db import db

SWAGGER_CONFIG = {
    "headers": [],
    "specs": [
        {
            "endpoint": "campusclaw-openapi",
            "route": "/api/openapi.json",
            "rule_filter": lambda rule: rule.rule.startswith("/api/"),
            "model_filter": lambda tag: True,
        }
    ],
    "static_url_path": "/flasgger_static",
    # The UI is our own same-origin shell (app/static/docs.html); flasgger only
    # supplies spec generation here.
    "swagger_ui": False,
    "specs_route": "/api/openapi.json",
    "openapi": "3.0.3",
}

SWAGGER_TEMPLATE = {
    "openapi": "3.0.3",
    "info": {
        "title": "CampusClaw API",
        "version": "1.0.0",
        "description": "课程知识库、MCP 服务器/工具与技能管理接口。",
    },
    "tags": [
        {"name": "auth", "description": "登录与令牌"},
        {"name": "mcp", "description": "MCP 服务器、工具与调用审计"},
        {"name": "skills", "description": "技能管理与使用"},
        {"name": "prompt-templates", "description": "提示词模板管理与使用"},
    ],
    "components": {
        "securitySchemes": {
            "bearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
                "description": (
                    "先调用 /api/auth/login 获取 access_token，"
                    "再填入 Authorization: Bearer <token>。"
                ),
            }
        },
        "schemas": {
            "Error": {
                "type": "object",
                "properties": {
                    "error": {"type": "string"},
                    "message": {"type": "string"},
                },
            },
            "McpServer": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "name": {"type": "string"},
                    "base_url": {"type": "string"},
                    "has_token": {"type": "boolean"},
                    "connected": {"type": "boolean"},
                    "connected_at": {
                        "type": "string",
                        "nullable": True,
                        "format": "date-time",
                    },
                    "tools": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "description": {"type": "string"},
                            },
                        },
                    },
                    "last_error": {"type": "string", "nullable": True},
                    "created_at": {"type": "string", "format": "date-time"},
                },
            },
            "CachedTool": {
                "type": "object",
                "properties": {
                    "server_id": {"type": "integer"},
                    "server_name": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "input_schema": {"type": "object"},
                },
            },
            "AuditItem": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "ref": {"type": "string", "example": "formula_hint@campus-tools"},
                    "tool": {"type": "string"},
                    "server": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["ok", "denied", "error"],
                    },
                    "username": {"type": "string"},
                    "reason": {"type": "string", "nullable": True},
                    "created_at": {
                        "type": "string",
                        "format": "date-time",
                        "description": "UTC 时间",
                    },
                },
            },
            "Skill": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "name": {"type": "string"},
                    "subject": {"type": "string", "nullable": True},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                    "tools": {"type": "array", "items": {"type": "string"}},
                    "enabled": {"type": "boolean"},
                    "created_at": {"type": "string", "format": "date-time"},
                },
            },
            "PromptTemplate": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "name": {"type": "string"},
                    "description": {"type": "string", "nullable": True},
                    "placeholders": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "enabled": {"type": "boolean"},
                    "created_at": {"type": "string", "format": "date-time"},
                    "body": {
                        "type": "string",
                        "description": "仅教师列表与创建响应包含",
                    },
                },
            },
        },
    },
}

# Single-page shells (public; contain no business data).
SHELL_PAGES = {
    "/": "index.html",
    "/kb": "kb.html",
    "/login": "login.html",
    "/register": "register.html",
    "/api/docs": "docs.html",
}


def create_app(test_config: dict | None = None):
    app = Flask(__name__)

    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    _validate_secret_key(app)

    db.init_app(app)
    _enable_sqlite_pragmas(app)

    # Upgrade existing volumes (add indexed_at / create vector table).
    with app.app_context():
        from .kb.vector_store import ensure_runtime_schema

        ensure_runtime_schema()

    # Blueprints: all protected/business endpoints live under /api.
    from .auth import auth_bp
    from .health import health_bp
    from .kb.routes import kb_bp
    from .materials import materials_bp
    from .mcp.routes import mcp_bp
    from .prompt_templates.routes import prompt_templates_bp
    from .skills.routes import skills_bp

    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(materials_bp, url_prefix="/api")
    app.register_blueprint(kb_bp, url_prefix="/api")
    app.register_blueprint(mcp_bp, url_prefix="/api")
    app.register_blueprint(skills_bp, url_prefix="/api")
    app.register_blueprint(prompt_templates_bp, url_prefix="/api")
    app.register_blueprint(health_bp)

    # OpenAPI 3 spec generated from route docstrings; the Swagger UI shell is
    # our own same-origin page and the assets below ship with flasgger.
    Swagger(app, config=SWAGGER_CONFIG, template=SWAGGER_TEMPLATE)
    swagger_assets = os.path.join(
        os.path.dirname(flasgger.__file__), "ui3", "static"
    )

    @app.get("/flasgger_static/<path:filename>")
    def flasgger_static_asset(filename: str):
        return send_from_directory(swagger_assets, filename)

    from .cli import init_app as init_cli

    init_cli(app)

    @app.after_request
    def _security_headers(response):
        # Static shell only; no third-party or inline scripts. This limits the
        # blast radius of any XSS that could steal tokens from localStorage.
        # The docs page alone allows inline *styles* because Swagger UI sets
        # style attributes; scripts stay same-origin everywhere.
        style_src = (
            "'self' 'unsafe-inline'"
            if request.path == "/api/docs"
            else "'self'"
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            f"default-src 'self'; script-src 'self'; style-src {style_src}; "
            "img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'",
        )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    def _shell(page: str):
        return send_from_directory(app.static_folder, page)

    for rule, page in SHELL_PAGES.items():
        app.add_url_rule(
            rule, endpoint=f"shell-{page}", view_func=(lambda p=page: _shell(p))
        )

    @app.get("/materials/<int:material_id>/preview")
    def material_preview_shell(material_id: int):
        # Public shell only; text is fetched by JS with a bearer token.
        return send_from_directory(app.static_folder, "preview.html")

    @app.errorhandler(RequestEntityTooLarge)
    def _too_large(_error):
        return (
            jsonify(error="file_too_large", message="上传文件超过大小限制"),
            413,
        )

    @app.errorhandler(HTTPException)
    def _api_errors_as_json(error):
        # Every miss/business error under /api is a JSON API response; the
        # static shell keeps Flask's default HTML error pages.
        if request.path.startswith("/api/"):
            messages = {
                404: ("not_found", "资源不存在"),
                405: ("method_not_allowed", "请求方法不被允许"),
            }
            label, message = messages.get(
                error.code,
                (error.name.lower().replace(" ", "_"), error.description),
            )
            return jsonify(error=label, message=message), error.code
        return error.get_response()

    os.makedirs(app.config["UPLOAD_ROOT"], exist_ok=True)
    return app


def _validate_secret_key(app) -> None:
    """Fail closed: production must supply a real SECRET_KEY from env.

    SECRET_KEY signs JWT access tokens (HS256).
    """
    env = app.config.get("FLASK_ENV") or "development"
    if env == "production" and not app.config.get("SECRET_KEY"):
        raise RuntimeError(
            "SECRET_KEY environment variable is required when FLASK_ENV=production"
        )
    if env != "production" and not app.config.get("SECRET_KEY"):
        # Dev/test convenience: ephemeral random key (tokens die on restart).
        app.config["SECRET_KEY"] = os.urandom(32)


def _enable_sqlite_pragmas(app) -> None:
    """Turn on foreign keys and WAL for every SQLite DB-API connection."""
    with app.app_context():
        engine = db.engine
        if engine.dialect.name != "sqlite":
            return

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _connection_record):
            import sqlite_vec

            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()
            # Vector extension on every connection (same place as PRAGMAs).
            dbapi_connection.enable_load_extension(True)
            sqlite_vec.load(dbapi_connection)
            dbapi_connection.enable_load_extension(False)
