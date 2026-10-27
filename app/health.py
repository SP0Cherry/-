"""Unauthenticated health check endpoint."""
from flask import Blueprint, jsonify

from .db import db

health_bp = Blueprint("health", __name__)


@health_bp.get("/health")
def health():
    try:
        db.session.execute(db.text("SELECT 1"))
    except Exception:
        db.session.rollback()
        return jsonify(status="error"), 503
    return jsonify(status="ok"), 200
