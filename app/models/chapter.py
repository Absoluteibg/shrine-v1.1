from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.models.enums import PublishStatus, status_enum_type

if TYPE_CHECKING:
    from app.models.work import Work


class Chapter(Base):
    __tablename__ = "chapters"
    __table_args__ = (
        # Slug only needs to be unique *within* a work, not globally —
        # different works can each have a "prologue" chapter.
        UniqueConstraint("work_id", "slug", name="uq_chapters_work_slug"),
        UniqueConstraint("work_id", "chapter_number", name="uq_chapters_work_number"),
        Index("ix_chapters_work_status", "work_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    work_id: Mapped[int] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"), nullable=False)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    chapter_number: Mapped[int] = mapped_column(Integer, nullable=False)

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
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    work: Mapped["Work"] = relationship(back_populates="chapters")

    def __repr__(self) -> str:
        return f"Chapter(id={self.id!r}, work_id={self.work_id!r}, slug={self.slug!r})"
