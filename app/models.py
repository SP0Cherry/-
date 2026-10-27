"""Database models: Class, User, Material."""
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Index, Integer, UniqueConstraint

from .db import db


class Class(db.Model):
    __tablename__ = "classes"

    id = db.Column(Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)

    users = db.relationship("User", back_populates="class_")
    materials = db.relationship("Material", back_populates="class_")
    mcp_servers = db.relationship(
        "McpServer", back_populates="class_", cascade="all, delete-orphan"
    )
    skills = db.relationship(
        "Skill", back_populates="class_", cascade="all, delete-orphan"
    )
    prompt_templates = db.relationship(
        "PromptTemplate", back_populates="class_", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Class {self.name}>"


class User(db.Model):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('teacher', 'student')", name="ck_user_role"),
    )

    id = db.Column(Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(10), nullable=False)
    class_id = db.Column(
        Integer, db.ForeignKey("classes.id"), nullable=False, index=True
    )

    class_ = db.relationship("Class", back_populates="users")
    uploaded_materials = db.relationship("Material", back_populates="uploader")

    @property
    def is_teacher(self) -> bool:
        return self.role == "teacher"

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<User {self.username} ({self.role})>"


class Material(db.Model):
    __tablename__ = "materials"
    __table_args__ = (
        Index("ix_materials_class_created", "class_id", "created_at"),
    )

    id = db.Column(Integer, primary_key=True)
    original_name = db.Column(db.String(255), nullable=False)
    stored_key = db.Column(db.String(255), unique=True, nullable=False)
    mime_type = db.Column(db.String(100), nullable=False)
    size_bytes = db.Column(Integer, nullable=False)
    uploader_id = db.Column(
        Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    class_id = db.Column(
        Integer, db.ForeignKey("classes.id"), nullable=False
    )
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    # NULL for non-text or not-yet-indexed materials; also the backfill marker
    # used by `flask reindex-kb`.
    indexed_at = db.Column(db.DateTime, nullable=True)

    uploader = db.relationship("User", back_populates="uploaded_materials")
    class_ = db.relationship("Class", back_populates="materials")
    chunks = db.relationship(
        "KbChunk", back_populates="material", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Material {self.original_name}>"


class KbChunk(db.Model):
    """A text fragment of a txt/md material, class-scoped.

    Vectors live in the separate sqlite-vec virtual table (kb_vectors),
    keyed by this row's id.
    """

    __tablename__ = "kb_chunks"
    __table_args__ = (
        UniqueConstraint("material_id", "chunk_index", name="uq_kb_chunk"),
        Index("ix_kb_chunks_class", "class_id"),
    )

    id = db.Column(Integer, primary_key=True)
    material_id = db.Column(
        Integer, db.ForeignKey("materials.id"), nullable=False
    )
    # Redundant class column with an index: the physical guarantee that every
    # chunk read can be filtered to the acting user's class.
    class_id = db.Column(Integer, nullable=False)
    chunk_index = db.Column(Integer, nullable=False)
    char_start = db.Column(Integer, nullable=False)
    line_no = db.Column(Integer, nullable=False)
    heading = db.Column(db.String(255), nullable=True)
    heading_slug = db.Column(db.String(255), nullable=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    material = db.relationship("Material", back_populates="chunks")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<KbChunk material={self.material_id} idx={self.chunk_index}>"


class McpServer(db.Model):
    """A teacher-registered MCP server for one class.

    ``auth_token`` is a write-only server-side secret: it is stored here and
    used when the host connects over Compose DNS, but it is never serialized
    into an API response. ``tools_json`` is the tools/list cache; disconnecting
    clears it together with ``connected_at`` so tools cannot be called.
    """

    __tablename__ = "mcp_servers"
    __table_args__ = (
        UniqueConstraint("class_id", "name", name="uq_mcp_server_name"),
    )

    id = db.Column(Integer, primary_key=True)
    class_id = db.Column(
        Integer, db.ForeignKey("classes.id"), nullable=False, index=True
    )
    name = db.Column(db.String(50), nullable=False)
    base_url = db.Column(db.String(255), nullable=False)
    auth_token = db.Column(db.String(255), nullable=True)
    tools_json = db.Column(db.Text, nullable=True)
    connected_at = db.Column(db.DateTime, nullable=True)
    last_error = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    class_ = db.relationship("Class", back_populates="mcp_servers")

    @property
    def is_connected(self) -> bool:
        return self.connected_at is not None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<McpServer {self.name} class={self.class_id}>"


class McpToolCallAudit(db.Model):
    """One MCP ``tools/call`` attempt, scoped to the acting user's class.

    ``username`` is a snapshot so later renames do not rewrite history. Tokens,
    arguments and tool output are deliberately not stored. Rows are written
    best-effort and must never block the Q&A / tool-call main path.
    """

    __tablename__ = "mcp_tool_call_audits"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ok', 'denied', 'error')", name="ck_mcp_audit_status"
        ),
        Index("ix_mcp_audits_class_created", "class_id", "created_at"),
        Index("ix_mcp_audits_user", "user_id"),
    )

    id = db.Column(Integer, primary_key=True)
    class_id = db.Column(Integer, nullable=False)
    user_id = db.Column(Integer, nullable=False)
    username = db.Column(db.String(50), nullable=False)
    server_name = db.Column(db.String(50), nullable=False)
    tool_name = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(10), nullable=False)
    reason = db.Column(db.String(255), nullable=True)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    @property
    def ref(self) -> str:
        return f"{self.tool_name}@{self.server_name}"

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<McpToolCallAudit {self.ref} {self.status}>"


class Skill(db.Model):
    """A teacher-uploaded SKILL.md, scoped to one class.

    ``keywords_json`` and ``tools_json`` are the parsed metadata. Tool
    references store the server *name*, so runtime resolution always stays
    inside the acting user's class. ``body`` is the guidance text after the
    first blank line and is never returned by list/manage APIs.
    """

    __tablename__ = "skills"
    __table_args__ = (
        UniqueConstraint("class_id", "name", name="uq_skill_name"),
    )

    id = db.Column(Integer, primary_key=True)
    class_id = db.Column(
        Integer, db.ForeignKey("classes.id"), nullable=False, index=True
    )
    name = db.Column(db.String(100), nullable=False)
    subject = db.Column(db.String(50), nullable=True)
    keywords_json = db.Column(db.Text, nullable=False)
    tools_json = db.Column(db.Text, nullable=False)
    body = db.Column(db.Text, nullable=False)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    created_by_id = db.Column(
        Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    class_ = db.relationship("Class", back_populates="skills")
    creator = db.relationship("User")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Skill {self.name} class={self.class_id}>"


class PromptTemplate(db.Model):
    """A teacher-uploaded prompt template, scoped to one class.

    ``body`` holds the template text with fixed ``{{...}}`` placeholders; the
    placeholders themselves are derived from ``body`` on demand and never
    stored. A template is layered as an *additional* system section after the
    base assistant instructions, so it can never override the base constraints.
    """

    __tablename__ = "prompt_templates"
    __table_args__ = (
        UniqueConstraint("class_id", "name", name="uq_prompt_template_name"),
    )

    id = db.Column(Integer, primary_key=True)
    class_id = db.Column(
        Integer, db.ForeignKey("classes.id"), nullable=False, index=True
    )
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    body = db.Column(db.Text, nullable=False)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    created_by_id = db.Column(
        Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    class_ = db.relationship("Class", back_populates="prompt_templates")
    creator = db.relationship("User")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<PromptTemplate {self.name} class={self.class_id}>"
