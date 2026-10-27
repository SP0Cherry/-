"""Class-scoped data access for knowledge-base chunks and search.

Chunk replacement runs in a single transaction (rows + vectors), and search
always filters candidate chunks by the acting user's class — cross-class
content can never appear in results or answer sources.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..db import db
from ..models import KbChunk, Material
from . import vector_store


def replace_chunks(material: Material, chunks, vectors) -> int:
    """Re-index one material atomically; returns the number of chunks stored."""
    # Vectors first (rows still exist so the material-scoped DELETE resolves),
    # then the old rows, then insert everything new.
    vector_store.delete_for_material(material.id)
    KbChunk.query.filter_by(material_id=material.id).delete(
        synchronize_session="fetch"
    )

    rows = []
    for index, (chunk, vector) in enumerate(zip(chunks, vectors)):
        row = KbChunk(
            material_id=material.id,
            class_id=material.class_id,
            chunk_index=index,
            char_start=chunk.char_start,
            line_no=chunk.line_no,
            heading=chunk.heading,
            heading_slug=chunk.heading_slug,
            content=chunk.content,
        )
        db.session.add(row)
        rows.append((row, vector))

    db.session.flush()  # assign chunk ids used as virtual-table keys
    vector_store.insert_vectors((row.id, vector) for row, vector in rows)
    material.indexed_at = datetime.now(timezone.utc)
    db.session.commit()
    return len(rows)


def search_scoped(user, query_vector, top_k: int):
    """KNN followed by class filtering. Returns [(KbChunk, distance), ...]."""
    # vec0 cannot filter on metadata; over-fetch candidates so the class filter
    # still leaves top_k rows in an evenly split library.
    candidate_bound = max(top_k * 50, 200)
    candidates = vector_store.knn(query_vector, candidate_bound)
    if not candidates:
        return []
    ids = [chunk_id for chunk_id, _distance in candidates]
    scoped = {
        row.id: row
        for row in db.session.query(KbChunk)
        .filter(KbChunk.id.in_(ids), KbChunk.class_id == user.class_id)
        .all()
    }
    results = []
    for chunk_id, distance in candidates:
        chunk = scoped.get(chunk_id)
        if chunk is not None:
            results.append((chunk, distance))
            if len(results) >= top_k:
                break
    return results


def list_materials(*, only_missing: bool = False) -> list[Material]:
    query = Material.query
    if only_missing:
        query = query.filter(Material.indexed_at.is_(None))
    return query.order_by(Material.id.asc()).all()
