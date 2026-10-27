"""Render a validated template body by replacing fixed placeholders."""
from __future__ import annotations

from .parser import PLACEHOLDER_PATTERN

EMPTY_MARKER = "（无）"


def _render_sources(sources) -> str:
    lines = []
    for index, source in enumerate(sources or [], start=1):
        heading = source.get("heading") or "无"
        lines.append(
            f"[{index}]《{source.get('material_name', '')}》"
            f"{heading}（行号：{source.get('line_no', '')}）"
        )
    # Only the citation list is rendered (not the full snippets, which already
    # appear in the base system prompt) so the template can cite the sources
    # without duplicating the whole retrieved context.
    return "\n".join(lines) if lines else EMPTY_MARKER


def _render_skills(skills) -> str:
    names = [name for name in (skills or []) if name]
    return "、".join(names) if names else EMPTY_MARKER


def render_template(body: str, *, question: str, sources=None, skills=None) -> str:
    """Replace ``{{question}}`` / ``{{sources}}`` / ``{{skills}}`` in ``body``."""
    replacements = {
        "question": question or "",
        "sources": _render_sources(sources),
        "skills": _render_skills(skills),
    }

    def _substitute(match) -> str:
        return replacements[match.group(1).strip()]

    return PLACEHOLDER_PATTERN.sub(_substitute, body)