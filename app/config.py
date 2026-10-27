"""Application configuration.

All sensitive/deployable values come from environment variables only.
No real secret is ever hardcoded here.
"""
import os


def _default_data_dir() -> str:
    return os.environ.get("DATA_DIR", os.path.join(os.getcwd(), "data"))


def _database_uri() -> str:
    raw = os.environ.get("DATABASE_URL")
    if raw:
        # Normalize relative sqlite paths to absolute (absolute URIs such as
        # sqlite:////data/campusclaw.db pass through unchanged).
        if raw.startswith("sqlite:///") and not raw.startswith("sqlite:////"):
            relative = raw[len("sqlite:///") :]
            if relative and relative != ":memory:":
                return "sqlite:///" + os.path.abspath(relative).replace("\\", "/")
        return raw
    default_file = os.path.join(_default_data_dir(), "campusclaw.db")
    return "sqlite:///" + os.path.abspath(default_file).replace("\\", "/")


class Config:
    # --- Identity / environment -------------------------------------------------
    FLASK_ENV = os.environ.get("FLASK_ENV", "development")

    # MUST be provided via environment in production; validated in create_app.
    # Used as the HMAC key that signs JWT access tokens.
    SECRET_KEY = os.environ.get("SECRET_KEY")

    # --- JWT access tokens ------------------------------------------------------
    JWT_ALGORITHM = "HS256"
    JWT_ACCESS_TTL_MINUTES = int(os.environ.get("JWT_ACCESS_TTL_MINUTES", "480"))

    # --- Database / storage -----------------------------------------------------
    SQLALCHEMY_DATABASE_URI = _database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    UPLOAD_ROOT = os.environ.get("UPLOAD_ROOT") or os.path.join(
        _default_data_dir(), "uploads"
    )

    # --- Upload limits ----------------------------------------------------------
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_UPLOAD_BYTES", 20 * 1024 * 1024))
    ALLOWED_EXTENSIONS = {
        part.strip().lower()
        for part in os.environ.get(
            "ALLOWED_EXTENSIONS", "pdf,docx,pptx,xlsx,png,jpg,jpeg,txt,md"
        ).split(",")
        if part.strip()
    }

    # Extensions whose content can be previewed in the browser (subset of the
    # allowed extensions); surfaced to the UI via GET /api/config.
    PREVIEWABLE_EXTENSIONS = {
        part.strip().lower()
        for part in os.environ.get("PREVIEWABLE_EXTENSIONS", "txt,md").split(",")
        if part.strip()
    }

    # Extension -> acceptable declared MIME types (double whitelist).
    ALLOWED_MIME_TYPES = {
        "pdf": {"application/pdf"},
        "docx": {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        },
        "pptx": {
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        },
        "xlsx": {
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        },
        "png": {"image/png"},
        "jpg": {"image/jpeg"},
        "jpeg": {"image/jpeg"},
        # Browsers/OSes disagree on the declared MIME type for .md, so plain
        # text is accepted there; the extension remains the primary check.
        "txt": {"text/plain"},
        "md": {"text/markdown", "text/x-markdown", "text/plain"},
    }

    # --- AI gateway (embeddings + chat) ----------------------------------------
    # Server-side only: the browser never calls the gateway and never receives
    # the key. One OpenAI-compatible base URL/key serves both services.
    EMBEDDING_BASE_URL = os.environ.get(
        "EMBEDDING_BASE_URL", "https://ai-gateway.devops.hello1023.com/v1"
    )
    EMBEDDING_API_KEY = os.environ.get("EMBEDDING_API_KEY", "")
    EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "course-embedding")
    EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "2048"))
    EMBEDDING_TIMEOUT = int(os.environ.get("EMBEDDING_TIMEOUT", "15"))
    # "api" (real gateway) or "stub" (deterministic, offline; tests/CI).
    EMBEDDING_BACKEND = os.environ.get("EMBEDDING_BACKEND", "api")

    # Chat/answer model. The gateway currently permits only "course-chat".
    LLM_MODEL = os.environ.get("LLM_MODEL", "course-chat")
    LLM_BACKEND = os.environ.get("LLM_BACKEND", "api")
    LLM_TEMPERATURE = float(os.environ.get("LLM_TEMPERATURE", "0.3"))
    LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "800"))
    LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "40"))

    # --- Self-hosted MCP server ------------------------------------------------
    # The API reaches the MCP container over the Compose network. The bearer
    # token is a server-side secret: it is never exposed to the browser.
    MCP_BASE_URL = os.environ.get("MCP_BASE_URL", "http://mcp-demo:8090")
    MCP_AUTH_TOKEN = os.environ.get("MCP_AUTH_TOKEN", "")
    MCP_TIMEOUT = int(os.environ.get("MCP_TIMEOUT", "10"))

    # --- Knowledge base tuning --------------------------------------------------
    KB_CHUNK_CHARS = int(os.environ.get("KB_CHUNK_CHARS", "400"))
    KB_CHUNK_OVERLAP = int(os.environ.get("KB_CHUNK_OVERLAP", "80"))
    KB_TOP_K = int(os.environ.get("KB_TOP_K", "8"))
    KB_QUERY_MAX_LEN = int(os.environ.get("KB_QUERY_MAX_LEN", "200"))
    KB_MIN_SCORE = float(os.environ.get("KB_MIN_SCORE", "0.35"))
