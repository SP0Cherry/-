"""Indexing pipeline: file -> chunks -> embeddings -> atomic persistence."""
from __future__ import annotations

from flask import current_app

from ..storage import absolute_path, extension_of
from . import repository
from .chunking import split_text
from .embeddings import Embedder, build_embedder


def index_material(material, embedder: Embedder | None = None) -> int:
    """(Re)index one txt/md material. Raises ValueError for other formats."""
    ext = extension_of(material.original_name)
    if ext not in current_app.config["PREVIEWABLE_EXTENSIONS"]:
        raise ValueError(f"材料 {material.id} 不是可索引的文本格式")

    with open(absolute_path(material.stored_key), "rb") as handle:
        text = handle.read().decode("utf-8")  # validated at upload time

    chunks = split_text(
        text,
        chunk_chars=current_app.config["KB_CHUNK_CHARS"],
        overlap=current_app.config["KB_CHUNK_OVERLAP"],
    )
    embedder = embedder or build_embedder(current_app.config)
    vectors = embedder.embed_batch([chunk.content for chunk in chunks])
    return repository.replace_chunks(material, chunks, vectors)
