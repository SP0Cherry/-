"""Best-effort persistence of MCP tool call attempts.

Auditing must never break the caller: any database failure is rolled back and
logged, and the original business result is still returned. Only identifiers,
status and a short readable reason are stored -- never tokens, arguments or
tool output.
"""
from __future__ import annotations

from flask import current_app

from ..db import db
from ..models import McpToolCallAudit

MAX_REASON_LEN = 255
MAX_SERVER_LEN = 50
MAX_TOOL_LEN = 100


def record_call(user, tool_name, server_name, status, reason=None) -> None:
    """Append one audit row for an MCP tool call attempt."""
    if user is None or not server_name:
        return
    try:
        db.session.add(
            McpToolCallAudit(
                class_id=user.class_id,
                user_id=user.id,
                username=user.username,
                server_name=str(server_name)[:MAX_SERVER_LEN],
                tool_name=str(tool_name)[:MAX_TOOL_LEN],
                status=status,
                reason=(str(reason)[:MAX_REASON_LEN] if reason else None),
            )
        )
        db.session.commit()
    except Exception as error:  # noqa: BLE001 - auditing is never load-bearing
        db.session.rollback()
        current_app.logger.warning(
            "failed to record MCP tool audit (%s@%s): %s",
            tool_name,
            server_name,
            error,
        )
