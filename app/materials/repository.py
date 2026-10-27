"""Sole data-access module for Material.

Every read/write here is scoped by the acting user's class. Business code must
never query Material directly, so no unfiltered cross-class query can exist.
"""
from ..db import db
from ..models import Material


def list_for(user) -> list[Material]:
    return (
        Material.query.filter_by(class_id=user.class_id)
        .order_by(Material.created_at.desc())
        .all()
    )


def get_scoped_or_404(user, material_id: int) -> Material:
    material = Material.query.filter_by(
        id=material_id, class_id=user.class_id
    ).first()
    if material is None:
        # Same response for "does not exist" and "belongs to another class":
        # never confirm the resource exists.
        from flask import abort

        abort(404)
    return material


def create_material(
    *,
    user,
    original_name: str,
    stored_key: str,
    mime_type: str,
    size_bytes: int,
) -> Material:
    material = Material(
        original_name=original_name,
        stored_key=stored_key,
        mime_type=mime_type,
        size_bytes=size_bytes,
        uploader_id=user.id,
        class_id=user.class_id,  # identity comes ONLY from the authenticated user
    )
    db.session.add(material)
    db.session.commit()
    return material
