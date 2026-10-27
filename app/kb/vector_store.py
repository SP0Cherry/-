"""sqlite-vec vector storage: extension setup, runtime schema migration and
vector DML/KNN against the ``kb_vectors`` virtual table.

The virtual table lives in the same SQLite file as the main schema, so it is
persisted on the existing data volume without a second store.
"""
import sqlite_vec
from flask import current_app

from ..db import db

VIRTUAL_TABLE = "kb_vectors"


def _ddl(dim: int) -> str:
    return (
        f"CREATE VIRTUAL TABLE IF NOT EXISTS {VIRTUAL_TABLE} "
        f"USING vec0(chunk_id INTEGER PRIMARY KEY, embedding FLOAT[{dim}])"
    )


def ensure_runtime_schema(dim: int | None = None) -> None:
    """Idempotent upgrade for existing volumes.

    ``db.create_all()`` never alters pre-existing tables, so: add the nullable
    ``materials.indexed_at`` column when missing, and ensure the vector table
    exists. Safe to run repeatedly; no Alembic.
    """
    dim = dim or current_app.config["EMBEDDING_DIM"]
    engine = db.engine

    with engine.begin() as conn:
        rows = conn.exec_driver_sql("PRAGMA table_info(materials)").fetchall()
        columns = {row[1] for row in rows}
        if rows and "indexed_at" not in columns:
            conn.exec_driver_sql(
                "ALTER TABLE materials ADD COLUMN indexed_at DATETIME"
            )

    # Separate transaction: CREATE VIRTUAL TABLE is DDL.
    with engine.begin() as conn:
        conn.exec_driver_sql(_ddl(dim))


def _raw_connection():
    # DBAPI sqlite3 connection held by the current session's transaction.
    return db.session.connection().connection


def insert_vectors(pairs) -> None:
    """pairs: iterable of (chunk_id, vector: list[float])."""
    raw = _raw_connection()
    cursor = raw.cursor()
    try:
        for chunk_id, vector in pairs:
            serialized = sqlite_vec.serialize_float32(list(vector))
            cursor.execute(
                f"INSERT INTO {VIRTUAL_TABLE} (chunk_id, embedding) VALUES (?, ?)",
                (int(chunk_id), serialized),
            )
    finally:
        cursor.close()


def delete_for_material(material_id: int) -> None:
    """Remove vectors belonging to one material (chunks identified in SQL)."""
    raw = _raw_connection()
    cursor = raw.cursor()
    try:
        cursor.execute(
            f"DELETE FROM {VIRTUAL_TABLE} WHERE chunk_id IN "
            "(SELECT id FROM kb_chunks WHERE material_id = ?)",
            (int(material_id),),
        )
    finally:
        cursor.close()


def knn(query_vector, candidate_limit: int):
    """Full-library KNN. Returns [(chunk_id, distance), ...].

    Candidate filtering by class happens afterwards in the repository (vec0
    cannot filter by arbitrary metadata); a high bound is used rather than
    truncating early.
    """
    raw = _raw_connection()
    serialized = sqlite_vec.serialize_float32(list(query_vector))
    cursor = raw.cursor()
    try:
        cursor.execute(
            f"SELECT chunk_id, distance FROM {VIRTUAL_TABLE} "
            "WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
            (serialized, int(candidate_limit)),
        )
        return [(row[0], row[1]) for row in cursor.fetchall()]
    finally:
        cursor.close()
