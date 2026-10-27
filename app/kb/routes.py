"""Knowledge base API: class-scoped retrieval and streaming (SSE) Q&A."""
import json

from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context

from ..auth.decorators import current_user, login_required
from ..prompt_templates.service import TemplateSelectionError
from ..skills.service import SkillSelectionError
from .embeddings import EmbeddingConfigError, EmbeddingError
from .llm import ChatError
from . import service
from .service import QueryValidationError

kb_bp = Blueprint("kb", __name__)


def _error(code: str, message: str, status: int):
    return jsonify(error=code, message=message), status


def _sse(event: str, payload: dict) -> str:
    return (
        f"event: {event}\n"
        f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
    )


@kb_bp.get("/kb/search")
@login_required
def kb_search():
    try:
        sources = service.retrieve(current_user(), request.args.get("q", ""))
    except QueryValidationError as error:
        return _error("bad_request", str(error), 400)
    except EmbeddingConfigError as error:
        return _error("service_unavailable", str(error), 503)
    except EmbeddingError as error:
        return _error("bad_gateway", str(error), 502)
    return jsonify(retrieved=bool(sources), sources=sources)


@kb_bp.post("/kb/ask")
@login_required
def kb_ask():
    payload = request.get_json(silent=True) or {}
    try:
        prepared = service.prepare(
            current_user(),
            payload.get("q", ""),
            force=bool(payload.get("force", False)),
            skill_ids=payload.get("skill_ids"),
            template_id=payload.get("template_id"),
        )
    except QueryValidationError as error:
        return _error("bad_request", str(error), 400)
    except SkillSelectionError as error:
        return _error(error.error_code, str(error), error.status_code)
    except TemplateSelectionError as error:
        return _error(error.error_code, str(error), error.status_code)
    except EmbeddingConfigError as error:
        return _error("service_unavailable", str(error), 503)
    except EmbeddingError as error:
        return _error("bad_gateway", str(error), 502)

    # The chat client is constructed before the stream starts so configuration
    # errors still get a plain JSON status; upstream failures after ``meta``
    # are reported as an ``error`` event inside the stream.
    chat = None
    if not prepared.gate:
        try:
            chat = service.build_chat_client(current_app.config)
        except ChatError as error:
            return _error("bad_gateway", str(error), 502)

    def generate():
        yield _sse("meta", prepared.meta)
        if prepared.gate:
            yield _sse("done", {})
            return

        try:
            for text in chat.stream(prepared.messages):
                yield _sse("delta", {"text": text})
        except ChatError as error:
            current_app.logger.warning("streaming chat failed: %s", error)
            yield _sse(
                "error",
                {"error": "chat_failed", "message": str(error)},
            )
            return
        except Exception:  # noqa: BLE001 - report a readable stream error
            current_app.logger.exception("unexpected streaming chat failure")
            yield _sse(
                "error",
                {"error": "chat_failed", "message": "生成回答时发生错误，请重试"},
            )
            return

        yield _sse("done", {})

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
