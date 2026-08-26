from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.models.associations import work_tags

if TYPE_CHECKING:
    from app.models.work import Work


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("name", name="uq_tags_name"),
        UniqueConstraint("slug", name="uq_tags_slug"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    works: Mapped[list["Work"]] = relationship(secondary=work_tags, back_populates="tags")

    def __repr__(self) -> str:
        return f"Tag(id={self.id!r}, slug={self.slug!r})"
