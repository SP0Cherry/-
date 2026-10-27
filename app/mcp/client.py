"""Minimal JSON-RPC 2.0 client for the self-hosted MCP server.

The host application talks to the MCP container over the Compose network using
``MCP_BASE_URL``; tool logic lives in the MCP server, not here. The bearer token
stays server-side and is never returned to the browser.
"""
from __future__ import annotations

import itertools

import requests

PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "campusclaw", "version": "1.0.0"}


class MCPError(RuntimeError):
    """The MCP server is unreachable, rejected auth, or returned an error."""


class MCPClient:
    def __init__(self, base_url: str, token: str, timeout: int = 10):
        if not base_url:
            raise MCPError("缺少 MCP_BASE_URL")
        if not token:
            raise MCPError("缺少 MCP_AUTH_TOKEN")
        self.endpoint = base_url.rstrip("/") + "/mcp"
        self.token = token
        self.timeout = timeout
        self._ids = itertools.count(1)
        self._initialized = False

    def _post(self, payload: dict) -> requests.Response:
        try:
            return requests.post(
                self.endpoint,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise MCPError(f"MCP 服务不可达（{self.endpoint}）：{error}") from error

    def _rpc(self, method: str, params: dict | None = None) -> dict:
        payload = {"jsonrpc": "2.0", "id": next(self._ids), "method": method}
        if params is not None:
            payload["params"] = params

        response = self._post(payload)
        if response.status_code == 401:
            raise MCPError("MCP 服务拒绝了访问令牌（HTTP 401）")
        if not response.ok:
            raise MCPError(f"MCP 服务返回 HTTP {response.status_code}")

        try:
            body = response.json()
        except ValueError as error:
            raise MCPError("MCP 服务返回了非 JSON 响应") from error

        error = body.get("error")
        if error:
            message = error.get("message") if isinstance(error, dict) else None
            raise MCPError(message or "MCP 调用失败")
        return body.get("result") or {}

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        self._rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": CLIENT_INFO,
            },
        )
        # Notification: JSON-RPC notifications carry no id and expect no result.
        response = self._post(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}
        )
        if not response.ok:
            raise MCPError(
                f"MCP 初始化通知失败（HTTP {response.status_code}）"
            )
        self._initialized = True

    def list_tools(self) -> list[dict]:
        self._ensure_initialized()
        result = self._rpc("tools/list", {})
        tools = result.get("tools")
        return tools if isinstance(tools, list) else []

    def call_tool(self, name: str, arguments: dict) -> dict:
        self._ensure_initialized()
        return self._rpc(
            "tools/call", {"name": name, "arguments": arguments}
        )
