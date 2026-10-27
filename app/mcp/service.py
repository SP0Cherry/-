"""Shared MCP registry helpers used by both the MCP routes and skill runtime.

Keeping token resolution, cache parsing and client construction here avoids two
copies drifting apart. Tokens never leave this module's server-side call path.
"""
from __future__ import annotations

import json

from flask import current_app

from ..models import McpServer
from .client import MCPClient, MCPError


def normalize_base_url(raw: str) -> str:
    return raw.strip().rstrip("/")


def cached_tools(server: McpServer) -> list[dict]:
    if not server.tools_json:
        return []
    try:
        tools = json.loads(server.tools_json)
    except (TypeError, ValueError):
        return []
    return [tool for tool in tools if isinstance(tool, dict)]


def cached_tool(server: McpServer, name: str) -> dict | None:
    for tool in cached_tools(server):
        if tool.get("name") == name:
            return tool
    return None


def resolve_token(server: McpServer) -> str:
    """Return the bearer token used to reach this server.

    A per-server token saved by the teacher wins. If none was saved, the
    server-configured token is used only for the configured Compose MCP URL,
    so the demo works without ever echoing the secret to the browser.
    """
    if server.auth_token:
        return server.auth_token
    configured_url = normalize_base_url(current_app.config["MCP_BASE_URL"])
    if normalize_base_url(server.base_url) == configured_url:
        return current_app.config["MCP_AUTH_TOKEN"]
    return ""


def client_for(server: McpServer, client_class=None) -> MCPClient:
    token = resolve_token(server)
    if not token:
        raise MCPError(
            "该服务器未登记 Bearer 令牌，且地址不是服务端配置的 MCP 服务"
        )
    factory = client_class or MCPClient
    return factory(
        base_url=server.base_url,
        token=token,
        timeout=current_app.config["MCP_TIMEOUT"],
    )


def find_server(class_id: int, name: str) -> McpServer | None:
    """Resolve a server name strictly inside one class."""
    return McpServer.query.filter_by(class_id=class_id, name=name).first()
