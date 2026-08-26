from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.models.associations import work_tags
from app.models.enums import PublishStatus, WorkType, status_enum_type

if TYPE_CHECKING:
    from app.models.chapter import Chapter
    from app.models.tag import Tag


class Work(Base):
    __tablename__ = "works"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_works_slug"),
        Index("ix_works_status_type", "status", "type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)

    # Stable after creation — see WorkService. Regenerating it on every
    # title edit would silently break published URLs/inbound links, so
    # there is deliberately no "update slug" path yet.
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)

    # native_enum=False stores this as VARCHAR + CHECK rather than a
    # native Postgres/SQLite enum type. SQLite has no real enum type
    # anyway, and native Postgres enums are awkward to alter later
    # (adding a value needs special DDL) — VARCHAR+CHECK behaves
    # identically on both databases, which matters given the planned
    # SQLite -> PostgreSQL move.
    type: Mapped[WorkType] = mapped_column(
        SAEnum(
            WorkType,
            native_enum=False,
            length=20,
            create_constraint=True,
            # Persist "novel"/"story"/... (the enum's .value), not the
            # member NAME ("NOVEL"). SQLAlchemy's default is to store
            # .name, which would silently diverge from server_default
            # below and from how these values are serialized in the API.
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Path/URL only — never binary image data. See ARCHITECTURE.md.
    cover_image: Mapped[str | None] = mapped_column(String(500), nullable=True)

    status: Mapped[PublishStatus] = mapped_column(
        status_enum_type(),
        nullable=False,
        default=PublishStatus.DRAFT,
        server_default=PublishStatus.DRAFT.value,
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    # Set the first time status becomes PUBLISHED, then preserved across
    # later unpublish/archive/republish cycles. See app/services/publishing.py.
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    chapters: Mapped[list["Chapter"]] = relationship(
        back_populates="work",
        cascade="all, delete-orphan",
        order_by="Chapter.chapter_number",
    )
    tags: Mapped[list["Tag"]] = relationship(secondary=work_tags, back_populates="works")

    def __repr__(self) -> str:
        return f"Work(id={self.id!r}, slug={self.slug!r}, status={self.status!r})"
