"""Flask CLI commands: init-db / seed."""
import os

import click
from flask import current_app
from flask.cli import with_appcontext

from .db import db
from .models import Material
from .seed import run_seed
from .storage import extension_of


def init_app(app) -> None:
    app.cli.add_command(init_db_command)
    app.cli.add_command(seed_command)
    app.cli.add_command(reindex_kb_command)


@click.command("init-db")
@with_appcontext
def init_db_command():
    """Create database tables (idempotent)."""
    os.makedirs(current_app.config["UPLOAD_ROOT"], exist_ok=True)
    db.create_all()
    from .kb.vector_store import ensure_runtime_schema

    ensure_runtime_schema()
    click.echo("Database tables created.")


@click.command("seed")
@with_appcontext
def seed_command():
    """Insert demo classes, accounts and a sample material (idempotent)."""
    counts = run_seed()
    click.echo(
        f"Seed complete: {counts['classes']} classes, "
        f"{counts['users']} users, {counts['materials']} materials."
    )


@click.command("reindex-kb")
@click.option("--all", "reindex_all", is_flag=True, help="重建全部文本材料")
@click.option("--material-id", type=int, default=None, help="只重建指定材料")
@with_appcontext
def reindex_kb_command(reindex_all: bool, material_id: int | None):
    """(Re)build knowledge-base chunks and vectors (idempotent)."""
    from .kb.indexer import index_material
    from .kb.repository import list_materials

    previewable = current_app.config["PREVIEWABLE_EXTENSIONS"]

    if material_id is not None:
        material = db.session.get(Material, material_id)
        if material is None:
            raise click.ClickException(f"材料 {material_id} 不存在")
        count = index_material(material)
        click.echo(f"材料 {material_id} 重建完成：{count} 块")
        return

    materials = list_materials(only_missing=not reindex_all)
    processed = 0
    total_chunks = 0
    failed = 0
    for material in materials:
        if extension_of(material.original_name) not in previewable:
            continue
        try:
            total_chunks += index_material(material)
            processed += 1
        except Exception:
            failed += 1
            current_app.logger.exception(
                "reindex-kb: material %s failed", material.id
            )
    click.echo(
        f"重建完成：{processed} 份材料，{total_chunks} 个块，{failed} 份失败"
    )
