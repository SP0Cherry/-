"""Material JSON API: list/detail/upload/download (Bearer-auth)."""
import os

from flask import (
    Blueprint,
    current_app,
    jsonify,
    request,
    send_file,
)

from werkzeug.utils import secure_filename

from ..db import db
from ..models import Material
from ..storage import (
    absolute_path,
    delete_stored,
    extension_of,
    is_allowed_file,
    save_file_storage,
    write_bytes,
)
from ..auth.decorators import current_user, login_required, role_required
from ..kb.indexer import index_material
from . import repository

materials_bp = Blueprint("materials", __name__)


def serialize_material(material: Material) -> dict:
    return {
        "id": material.id,
        "original_name": material.original_name,
        "mime_type": material.mime_type,
        "size_bytes": material.size_bytes,
        "uploader": material.uploader.username,
        "class_id": material.class_id,
        "created_at": material.created_at.isoformat(),
    }


@materials_bp.get("/config")
@login_required
def get_client_config():
    """Format lists the upload UI derives its hints from (never hardcoded)."""
    return jsonify(
        allowed_extensions=sorted(current_app.config["ALLOWED_EXTENSIONS"]),
        previewable_extensions=sorted(
            current_app.config["PREVIEWABLE_EXTENSIONS"]
        ),
    )


@materials_bp.get("/materials")
@login_required
def list_materials():
    materials = repository.list_for(current_user())
    return jsonify(items=[serialize_material(m) for m in materials])


@materials_bp.get("/materials/<int:material_id>")
@login_required
def material_detail(material_id: int):
    material = repository.get_scoped_or_404(current_user(), material_id)
    return jsonify(serialize_material(material))


@materials_bp.get("/materials/<int:material_id>/content")
@login_required
def material_content(material_id: int):
    """Raw text of a txt/md material for in-browser preview.

    Reuses the class boundary (cross-class -> 404); non-text formats are not
    served (415); a missing physical file is a server error.
    """
    material = repository.get_scoped_or_404(current_user(), material_id)
    ext = extension_of(material.original_name)
    if ext not in current_app.config["PREVIEWABLE_EXTENSIONS"]:
        return (
            jsonify(error="unsupported_media_type", message="该材料不支持在线预览"),
            415,
        )
    path = absolute_path(material.stored_key)
    if not os.path.isfile(path):
        return jsonify(error="file_missing", message="文件不可用"), 500
    with open(path, "rb") as handle:
        content = handle.read().decode("utf-8")
    return jsonify(
        id=material.id, original_name=material.original_name, ext=ext, content=content
    )


@materials_bp.post("/materials/upload")
@login_required
@role_required("teacher")
def upload_material():
    user = current_user()
    uploaded = request.files.get("file")
    if uploaded is None or not uploaded.filename:
        return jsonify(error="bad_request", message="缺少上传文件"), 400

    if not is_allowed_file(uploaded.filename, uploaded.mimetype):
        return (
            jsonify(error="unsupported_file_type", message="文件类型不被允许"),
            400,
        )

    ext = extension_of(uploaded.filename)
    if ext in current_app.config["PREVIEWABLE_EXTENSIONS"]:
        # Validate UTF-8 strictly before touching disk.
        raw_bytes = uploaded.read()
        try:
            raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return (
                jsonify(
                    error="bad_encoding",
                    message="文本材料必须为有效的 UTF-8 编码",
                ),
                400,
            )
        stored_key, size_bytes = write_bytes(
            current_app.config["UPLOAD_ROOT"], user.class_id, ext, raw_bytes
        )
    else:
        stored_key, size_bytes = save_file_storage(uploaded, user.class_id)
    try:
        material = repository.create_material(
            user=user,
            original_name=uploaded.filename,
            stored_key=stored_key,
            mime_type=uploaded.mimetype,
            size_bytes=size_bytes,
        )
    except Exception:
        db.session.rollback()
        delete_stored(stored_key)  # no orphan files
        current_app.logger.exception("Failed to persist material metadata")
        return jsonify(error="internal_error", message="保存材料失败"), 500

    # Best-effort indexing: a gateway failure must not fail the upload itself.
    # The material stays retrievable and can be picked up by reindex-kb.
    if ext in current_app.config["PREVIEWABLE_EXTENSIONS"]:
        try:
            index_material(material)
        except Exception:
            db.session.rollback()
            current_app.logger.exception(
                "Failed to index material %s after upload", material.id
            )

    return jsonify(**serialize_material(material)), 201


@materials_bp.get("/materials/<int:material_id>/download")
@login_required
def download_material(material_id: int):
    material = repository.get_scoped_or_404(current_user(), material_id)
    path = absolute_path(material.stored_key)
    if not os.path.isfile(path):
        return jsonify(error="file_missing", message="文件不可用"), 500
    safe_name = secure_filename(material.original_name) or material.stored_key
    return send_file(
        path,
        as_attachment=True,
        download_name=safe_name,
        mimetype=material.mime_type,
    )
