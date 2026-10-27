"""CampusClaw MCP server (JSON-RPC 2.0 over HTTP).

- ``POST /mcp``: Streamable-HTTP style endpoint. Supports ``initialize``,
  ``notifications/initialized``, ``ping``, ``tools/list`` and ``tools/call``.
- ``GET /health``: unauthenticated health check used by Docker Compose.
- ``Authorization: Bearer <MCP_AUTH_TOKEN>`` is required on ``/mcp``. The token
  comes from the environment only (never baked into the image, never sent to
  the browser). Missing/empty/wrong token -> HTTP 401.
"""

from __future__ import annotations

import hmac
import json
import os

from flask import Flask, jsonify, request

from mcp_tools import TOOLS, ToolError

SERVER_NAME = "campusclaw-mcp"
SERVER_VERSION = "1.0.0"
SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
DEFAULT_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]

app = Flask(__name__)
app.json.ensure_ascii = False
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024


# ------------------------------------------------------------ JSON-RPC helpers


def _result(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id, code, message, data=None):
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def _initialize_result(request_id, params):
    requested = params.get("protocolVersion") if isinstance(params, dict) else None
    version = (
        requested
        if requested in SUPPORTED_PROTOCOL_VERSIONS
        else DEFAULT_PROTOCOL_VERSION
    )
    return _result(
        request_id,
        {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": "课程助教的本地工具：公式提示与单位换算。",
        },
    )


def _list_tools_result(request_id):
    return _result(
        request_id,
        {
            "tools": [
                {
                    "name": name,
                    "description": spec["description"],
                    "inputSchema": spec["inputSchema"],
                }
                for name, spec in TOOLS.items()
            ]
        },
    )


def _call_tool_result(request_id, params):
    if not isinstance(params, dict):
        return _error(request_id, -32602, "无效参数：params 必须是对象")

    name = params.get("name")
    if not isinstance(name, str) or not name:
        return _error(request_id, -32602, "无效参数：缺少工具名称 name")

    arguments = params.get("arguments", {})
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return _error(request_id, -32602, "无效参数：arguments 必须是对象")

    spec = TOOLS.get(name)
    if spec is None:
        return _error(
            request_id,
            -32602,
            f"无效参数：未知工具 {name}",
            {"available_tools": sorted(TOOLS)},
        )

    try:
        text = spec["handler"](arguments)
    except ToolError as error:
        return _result(
            request_id,
            {"content": [{"type": "text", "text": str(error)}], "isError": True},
        )
    return _result(
        request_id,
        {"content": [{"type": "text", "text": text}], "isError": False},
    )


def _dispatch(payload):
    if not isinstance(payload, dict):
        return _error(
            None, -32600, "无效请求：请求体必须是单个 JSON-RPC 对象（不支持批量请求）"
        )

    request_id = payload.get("id")
    if payload.get("jsonrpc") != "2.0":
        return _error(request_id, -32600, '无效请求：jsonrpc 必须为 "2.0"')

    method = payload.get("method")
    if not isinstance(method, str) or not method:
        return _error(request_id, -32600, "无效请求：缺少 method")

    params = payload.get("params", {})
    if params is None:
        params = {}

    if method == "initialize":
        return _initialize_result(request_id, params)
    if method == "notifications/initialized":
        return _result(request_id, {})
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _list_tools_result(request_id)
    if method == "tools/call":
        return _call_tool_result(request_id, params)

    return _error(
        request_id,
        -32601,
        f"方法不存在：{method}",
        {
            "supported_methods": [
                "initialize",
                "notifications/initialized",
                "ping",
                "tools/list",
                "tools/call",
            ]
        },
    )


# ------------------------------------------------------------------ HTTP layer


def _authorized() -> bool:
    header = request.headers.get("Authorization", "")
    parts = header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return False

    candidate = parts[1].strip()
    expected = os.environ.get("MCP_AUTH_TOKEN", "").strip()
    if not candidate or not expected:
        # Fail closed: no configured token means no access.
        return False
    return hmac.compare_digest(candidate.encode(), expected.encode())


@app.get("/health")
def health():
    return jsonify(
        status="ok",
        server=SERVER_NAME,
        version=SERVER_VERSION,
        tools=len(TOOLS),
    )


@app.post("/mcp")
def mcp():
    if not _authorized():
        response = jsonify(
            _error(None, -32001, "未授权：缺少或错误的 Bearer 令牌")
        )
        response.status_code = 401
        response.headers["WWW-Authenticate"] = 'Bearer realm="campusclaw-mcp"'
        return response

    raw = request.get_data(cache=False)
    try:
        payload = json.loads(raw) if raw else None
    except (TypeError, ValueError):
        return jsonify(_error(None, -32700, "解析错误：请求体不是合法 JSON")), 400

    # JSON-RPC notifications get no response body (HTTP 202).
    if (
        isinstance(payload, dict)
        and "id" not in payload
        and str(payload.get("method", "")).startswith("notifications/")
    ):
        return "", 202

    return jsonify(_dispatch(payload)), 200


if __name__ == "__main__":
    port = int(os.environ.get("MCP_PORT", "8090"))
    app.run(host="0.0.0.0", port=port)
