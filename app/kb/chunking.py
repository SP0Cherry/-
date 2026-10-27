"""Deterministic text chunking for the class knowledge base.

Pure functions, no I/O. A chunk keeps enough metadata for answer sources and
for the preview page to anchor: char_start / line_no of the first NEW line of
the chunk, plus the most recent heading (and its slug) at that position.

The slug rule is shared with js/preview.js slugify(): ASCII-lowercase, strip
everything except unicode letters/numbers/whitespace/hyphen, whitespace runs
become single hyphens.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_HEADING_MD = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
_HEADING_TEXT = re.compile(
    r"^\s*(第[一二三四五六七八九十百\d]+[章节讲部分篇]"
    r"|[一二三四五六七八九十]+、\s*|\d+(?:\.\d+)*[、.]\s*)"
)


def slugify(text: str) -> str:
    """Shared slug; keep CJK characters and digits, drop other punctuation."""
    kept = "".join(
        ch for ch in text.lower() if ch.isalnum() or ch.isspace() or ch == "-"
    )
    kept = re.sub(r"\s+", "-", kept.strip())
    kept = re.sub(r"-+", "-", kept)
    return kept.strip("-")


def _heading_of(line: str) -> str | None:
    """Return heading text for markdown/Chinese document titles, else None."""
    md = _HEADING_MD.match(line)
    if md:
        return md.group(2).strip()
    stripped = line.strip()
    if _HEADING_TEXT.match(stripped) and len(stripped) <= 40:
        return stripped
    return None


@dataclass(frozen=True)
class Paragraph:
    line_no: int
    char_start: int
    text: str
    heading: str | None


@dataclass(frozen=True)
class Chunk:
    content: str
    char_start: int
    line_no: int
    heading: str | None
    heading_slug: str | None


def _iter_paragraphs(text: str):
    """Group consecutive non-empty lines into paragraphs; track offsets."""
    pos = 0
    current: list[tuple[int, int, str]] = []
    current_heading: str | None = None

    def flush():
        if not current:
            return None
        line_no, char_start, _first = current[0]
        joined = "\n".join(item[2] for item in current)
        para = Paragraph(line_no, char_start, joined, current_heading)
        current.clear()
        return para

    for idx, raw in enumerate(text.split("\n"), start=1):
        heading = _heading_of(raw)
        if heading is not None:
            flushed = flush()
            if flushed:
                yield flushed
            current_heading = heading
        elif raw.strip():
            current.append((idx, pos, raw))
        else:
            flushed = flush()
            if flushed:
                yield flushed
        pos += len(raw) + 1  # account for the split newline

    flushed = flush()
    if flushed:
        yield flushed


def split_text(text: str, chunk_chars: int = 400, overlap: int = 80) -> list[Chunk]:
    """Greedy paragraph packing with a trailing-context overlap window."""
    paragraphs = list(_iter_paragraphs(text))
    if not paragraphs:
        return []

    chunks: list[Chunk] = []
    body_parts: list[str] = []
    anchor: Paragraph | None = None
    prev_full = ""

    def make_chunk(full_text: str, para: Paragraph):
        chunks.append(
            Chunk(
                content=full_text,
                char_start=para.char_start,
                line_no=para.line_no,
                heading=para.heading,
                heading_slug=slugify(para.heading) if para.heading else None,
            )
        )

    for para in paragraphs:
        addition = para.text
        if body_parts and len("\n".join(body_parts + [addition])) > chunk_chars:
            # Current body is full; finalize it and start a context-overlap chunk.
            prev_full = "\n".join(body_parts)
            make_chunk(prev_full, anchor)
            seed = prev_full[-overlap:] if overlap and len(prev_full) > overlap else ""
            body_parts = [seed, addition] if seed else [addition]
            anchor = para
        else:
            if anchor is None:
                anchor = para
            body_parts.append(addition)

    if body_parts and anchor is not None:
        make_chunk("\n".join(body_parts), anchor)

    return chunks
