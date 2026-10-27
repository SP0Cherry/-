"""Class-scoped MCP server registry and host-side bridge.

Teachers register a server (name + Base URL, optional write-only bearer
token). The token is stored server-side only and is never returned by any
API. Connecting performs the MCP handshake and tools/list; the tool list is
cached on this class's record. Disconnecting clears the cache, after which
tool calls are rejected.

None of these routes are on the knowledge-base retrieval / streaming path, so
an unreachable MCP server can never break lesson-5 search or Q&A.
"""
import json
from datetime import datetime, timezone
from urllib.parse import urlparse

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy.exc import IntegrityError

from ..auth.decorators import current_user, login_required, role_required
from ..db import db
from ..models import McpServer, McpToolCallAudit
from . import audit as mcp_audit
from . import service as mcp_service
from .client import MCPClient, MCPError

mcp_bp = Blueprint("mcp", __name__)

MAX_NAME_LEN = 50
MAX_URL_LEN = 255
MAX_TOKEN_LEN = 255
DEFAULT_AUDIT_LIMIT = 50
MAX_AUDIT_LIMIT = 200


def _error(code: str, message: str, status: int):
    return jsonify(error=code, message=message), status


def _normalize_base_url(raw: str) -> str:
    return mcp_service.normalize_base_url(raw)


def _valid_base_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _cached_tools(server: McpServer) -> list[dict]:
    return mcp_service.cached_tools(server)


def _resolve_token(server: McpServer) -> str:
    return mcp_service.resolve_token(server)


def _client_for(server: McpServer) -> MCPClient:
    # ``MCPClient`` stays a module attribute so tests can monkeypatch it here.
    return mcp_service.client_for(server, MCPClient)


def _serialize(server: McpServer) -> dict:
    """Public representation. ``auth_token`` is deliberately excluded."""
    tools = _cached_tools(server)
    return {
        "id": server.id,
        "name": server.name,
        "base_url": server.base_url,
        "has_token": bool(server.auth_token),
        "connected": server.is_connected,
        "connected_at": (
            server.connected_at.isoformat() if server.connected_at else None
        ),
        "tools": [
            {
                "name": tool.get("name"),
                "description": tool.get("description") or "",
            }
            for tool in tools
            if isinstance(tool.get("name"), str)
        ],
        "last_error": server.last_error,
        "created_at": server.created_at.isoformat(),
    }


def _scoped_server(server_id: int) -> McpServer | None:
    user = current_user()
    return McpServer.query.filter_by(
        id=server_id, class_id=user.class_id
    ).first()


def _validate_name(value) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    name = value.strip()
    return name if len(name) <= MAX_NAME_LEN else None


@mcp_bp.get("/mcp/servers")
@login_required
@role_required("teacher")
def list_servers():
    """列出本班已登记的 MCP 服务器。
    ---
    tags:
      - mcp
    summary: 列出本班 MCP 服务器
    security:
      - bearerAuth: []
    responses:
      200:
        description: 本班服务器列表（不含令牌）
        content:
          application/json:
            schema:
              type: object
              properties:
                items:
                  type: array
                  items:
                    $ref: '#/components/schemas/McpServer'
      401:
        description: 未认证
      403:
        description: 学生无权访问
    """
    servers = (
        McpServer.query.filter_by(class_id=current_user().class_id)
        .order_by(McpServer.id.asc())
        .all()
    )
    return jsonify(items=[_serialize(server) for server in servers])


@mcp_bp.post("/mcp/servers")
@login_required
@role_required("teacher")
def create_server():
    """登记本班 MCP 服务器（仅教师）。
    ---
    tags:
      - mcp
    summary: 登记 MCP 服务器
    description: Bearer 令牌仅写入服务端，不会出现在任何响应中。
    security:
      - bearerAuth: []
    requestBody:
      required: true
      content:
        application/json:
          schema:
            type: object
            required: [name, base_url]
            properties:
              name:
                type: string
                maxLength: 50
                example: 课程公式助手
              base_url:
                type: string
                maxLength: 255
                example: http://mcp-demo:8090
              auth_token:
                type: string
                maxLength: 255
                description: 可选；仅写入，留空则使用服务端配置的令牌
    responses:
      201:
        description: 登记成功
        content:
          application/json:
            schema:
              type: object
              properties:
                server:
                  $ref: '#/components/schemas/McpServer'
      400:
        description: 名称或地址不合法
      401:
        description: 未认证
      403:
        description: 学生无权登记
      409:
        description: 本班已存在同名服务器
    """
    payload = request.get_json(silent=True) or {}
    name = _validate_name(payload.get("name"))
    if name is None:
        return _error("bad_request", "服务器名称必填且不超过 50 个字符", 400)

    raw_url = payload.get("base_url")
    if not isinstance(raw_url, str) or not raw_url.strip():
        return _error("bad_request", "Base URL 必填", 400)
    base_url = _normalize_base_url(raw_url)
    if len(base_url) > MAX_URL_LEN or not _valid_base_url(base_url):
        return _error(
            "bad_request", "Base URL 必须是合法的 http:// 或 https:// 地址", 400
        )

    token = payload.get("auth_token")
    if token is not None and not isinstance(token, str):
        return _error("bad_request", "Bearer 令牌格式不正确", 400)
    token = (token or "").strip() or None
    if token is not None and len(token) > MAX_TOKEN_LEN:
        return _error("bad_request", "Bearer 令牌过长", 400)

    user = current_user()
    existing = McpServer.query.filter_by(
        class_id=user.class_id, name=name
    ).first()
    if existing is not None:
        return _error("conflict", "本班已存在同名 MCP 服务器", 409)

    server = McpServer(
        class_id=user.class_id,
        name=name,
        base_url=base_url,
        auth_token=token,
    )
    db.session.add(server)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _error("conflict", "本班已存在同名 MCP 服务器", 409)
    return jsonify(server=_serialize(server)), 201


@mcp_bp.delete("/mcp/servers/<int:server_id>")
@login_required
@role_required("teacher")
def delete_server(server_id: int):
    """删除本班 MCP 服务器。
    ---
    tags:
      - mcp
    summary: 删除 MCP 服务器
    security:
      - bearerAuth: []
    parameters:
      - in: path
        name: server_id
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
        description: 服务器不存在或不属于本班
    """
    server = _scoped_server(server_id)
    if server is None:
        return _error("not_found", "MCP 服务器不存在", 404)
    db.session.delete(server)
    db.session.commit()
    return jsonify(deleted=True)


@mcp_bp.post("/mcp/servers/<int:server_id>/connect")
@login_required
@role_required("teacher")
def connect_server(server_id: int):
    """连接本班 MCP 服务器并缓存工具清单。
    ---
    tags:
      - mcp
    summary: 连接服务器
    description: 完成 MCP 握手并执行 tools/list；失败会清空缓存。
    security:
      - bearerAuth: []
    parameters:
      - in: path
        name: server_id
        required: true
        schema:
          type: integer
    responses:
      200:
        description: 连接成功，返回含缓存工具的服务器信息
        content:
          application/json:
            schema:
              type: object
              properties:
                server:
                  $ref: '#/components/schemas/McpServer'
      401:
        description: 未认证
      403:
        description: 学生无权连接
      404:
        description: 服务器不存在或不属于本班
      502:
        description: 远端 MCP 不可达或握手失败
    """
    server = _scoped_server(server_id)
    if server is None:
        return _error("not_found", "MCP 服务器不存在", 404)

    try:
        tools = _client_for(server).list_tools()
    except MCPError as error:
        # A failed connect must not leave a stale cache behind.
        server.tools_json = None
        server.connected_at = None
        server.last_error = str(error)[:500]
        db.session.commit()
        current_app.logger.warning(
            "MCP connect failed for server %s: %s", server.id, error
        )
        return _error("mcp_connect_failed", str(error), 502)

    cached = [
        tool for tool in tools if isinstance(tool, dict) and isinstance(
            tool.get("name"), str
        )
    ]
    server.tools_json = json.dumps(cached, ensure_ascii=False)
    server.connected_at = datetime.now(timezone.utc)
    server.last_error = None
    db.session.commit()
    return jsonify(server=_serialize(server))


@mcp_bp.post("/mcp/servers/<int:server_id>/disconnect")
@login_required
@role_required("teacher")
def disconnect_server(server_id: int):
    """断开本班 MCP 服务器并清空工具缓存。
    ---
    tags:
      - mcp
    summary: 断开服务器
    security:
      - bearerAuth: []
    parameters:
      - in: path
        name: server_id
        required: true
        schema:
          type: integer
    responses:
      200:
        description: 已断开，缓存已清空
      401:
        description: 未认证
      403:
        description: 学生无权断开
      404:
        description: 服务器不存在或不属于本班
    """
    server = _scoped_server(server_id)
    if server is None:
        return _error("not_found", "MCP 服务器不存在", 404)
    server.tools_json = None
    server.connected_at = None
    server.last_error = None
    db.session.commit()
    return jsonify(server=_serialize(server))


@mcp_bp.post("/mcp/servers/<int:server_id>/tools/call")
@login_required
def call_server_tool(server_id: int):
    """手动调用本班服务器上的 MCP 工具。
    ---
    tags:
      - mcp
    summary: 调用 MCP 工具（tools/call）
    description: 仅当服务器已连接且工具在缓存清单内时才发起远端调用；每次尝试都会写入审计。
    security:
      - bearerAuth: []
    parameters:
      - in: path
        name: server_id
        required: true
        schema:
          type: integer
    requestBody:
      required: true
      content:
        application/json:
          schema:
            type: object
            required: [name]
            properties:
              name:
                type: string
                example: formula_hint
              arguments:
                type: object
                description: 工具入参对象
    responses:
      200:
        description: 远端 tools/call 原始结果
        content:
          application/json:
            schema:
              type: object
              properties:
                result:
                  type: object
      400:
        description: 缺少工具名、参数格式错误或工具不在缓存
      401:
        description: 未认证
      404:
        description: 服务器不存在或不属于本班
      409:
        description: 服务器未连接
      502:
        description: 远端调用失败
    """
    server = _scoped_server(server_id)
    user = current_user()
    if server is None:
        return _error("not_found", "MCP 服务器不存在", 404)

    payload = request.get_json(silent=True) or {}
    name = payload.get("name")
    if not server.is_connected:
        # A denied attempt never reaches the remote, but still leaves a trace.
        mcp_audit.record_call(
            user,
            name if isinstance(name, str) and name else "unknown",
            server.name,
            "denied",
            "MCP 服务器未连接",
        )
        return _error(
            "mcp_not_connected", "MCP 服务器未连接，请先在管理界面连接", 409
        )

    arguments = payload.get("arguments")
    if arguments is None:
        arguments = {}
    if not isinstance(name, str) or not name:
        return _error("bad_request", "缺少工具名称 name", 400)
    if not isinstance(arguments, dict):
        return _error("bad_request", "arguments 必须是对象", 400)

    known = {
        tool.get("name")
        for tool in _cached_tools(server)
        if isinstance(tool.get("name"), str)
    }
    if name not in known:
        mcp_audit.record_call(
            user, name, server.name, "denied", "工具不在已缓存的工具清单中"
        )
        return _error(
            "unknown_tool", "该工具不在已缓存的工具清单中", 400
        )

    try:
        result = _client_for(server).call_tool(name, arguments)
    except MCPError as error:
        current_app.logger.warning(
            "MCP tools/call failed for server %s: %s", server.id, error
        )
        mcp_audit.record_call(user, name, server.name, "error", str(error))
        return _error("mcp_unavailable", str(error), 502)

    if isinstance(result, dict) and result.get("isError"):
        mcp_audit.record_call(user, name, server.name, "error", "工具返回错误")
    else:
        mcp_audit.record_call(user, name, server.name, "ok")
    return jsonify(result=result)


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _serialize_audit(row: McpToolCallAudit) -> dict:
    return {
        "id": row.id,
        "ref": row.ref,
        "tool": row.tool_name,
        "server": row.server_name,
        "status": row.status,
        "username": row.username,
        "reason": row.reason,
        "created_at": _iso_utc(row.created_at),
    }


@mcp_bp.get("/mcp/audit")
@login_required
@role_required("teacher")
def list_audit():
    """教师查看本班 MCP 工具调用审计。
    ---
    tags:
      - mcp
    summary: 查询本班 MCP 工具调用审计
    description: 仅返回当前教师所在班级的记录，按时间倒序，不含令牌与工具输出。
    security:
      - bearerAuth: []
    parameters:
      - in: query
        name: limit
        schema:
          type: integer
          default: 50
          minimum: 1
          maximum: 200
        description: 本页最多返回条数（默认 50，最大 200）
      - in: query
        name: offset
        schema:
          type: integer
          default: 0
          minimum: 0
        description: 跳过的记录条数
    responses:
      200:
        description: 按时间倒序的审计分页
        content:
          application/json:
            schema:
              type: object
              properties:
                items:
                  type: array
                  items:
                    $ref: '#/components/schemas/AuditItem'
                has_more:
                  type: boolean
      400:
        description: 分页参数不是整数
      401:
        description: 未认证
      403:
        description: 学生无权查看审计
    """
    try:
        limit = int(request.args.get("limit", DEFAULT_AUDIT_LIMIT))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        return _error("bad_request", "limit 与 offset 必须是整数", 400)
    limit = max(1, min(limit, MAX_AUDIT_LIMIT))
    offset = max(0, offset)

    rows = (
        McpToolCallAudit.query.filter_by(class_id=current_user().class_id)
        .order_by(McpToolCallAudit.created_at.desc(), McpToolCallAudit.id.desc())
        .offset(offset)
        .limit(limit + 1)
        .all()
    )
    has_more = len(rows) > limit
    return jsonify(
        items=[_serialize_audit(row) for row in rows[:limit]],
        has_more=has_more,
    )


@mcp_bp.get("/mcp/tools")
@login_required
def list_cached_tools():
    """All tools cached from connected servers of the acting user's class.
    ---
    tags:
      - mcp
    summary: 列出本班已连接服务器的工具清单
    security:
      - bearerAuth: []
    responses:
      200:
        description: 缓存工具清单（含服务器与入参 schema）
        content:
          application/json:
            schema:
              type: object
              properties:
                tools:
                  type: array
                  items:
                    $ref: '#/components/schemas/CachedTool'
      401:
        description: 未认证
    """
    servers = McpServer.query.filter(
        McpServer.class_id == current_user().class_id,
        McpServer.connected_at.isnot(None),
    ).all()
    items = []
    for server in servers:
        for tool in _cached_tools(server):
            name = tool.get("name")
            if not isinstance(name, str):
                continue
            items.append(
                {
                    "server_id": server.id,
                    "server_name": server.name,
                    "name": name,
                    "description": tool.get("description") or "",
                    "input_schema": tool.get("inputSchema") or {},
                }
            )
    return jsonify(tools=items)
