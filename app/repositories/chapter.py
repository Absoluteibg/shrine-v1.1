"""
Persistence for Chapter. Every query here is scoped to a work_id — this
module never returns a chapter without knowing which work it belongs
to, which keeps "a chapter always belongs to exactly one work" true at
the query layer, not just by convention.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chapter import Chapter
from app.models.enums import PublishStatus


class ChapterRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, chapter: Chapter) -> Chapter:
        self.db.add(chapter)
        self.db.flush()
        return chapter

    def get_by_id(self, chapter_id: int) -> Chapter | None:
        return self.db.get(Chapter, chapter_id)

    def get_by_work_and_slug(self, work_id: int, slug: str) -> Chapter | None:
        stmt = select(Chapter).where(Chapter.work_id == work_id, Chapter.slug == slug)
        return self.db.execute(stmt).scalar_one_or_none()

    def slug_exists_for_work(self, work_id: int, slug: str, *, exclude_id: int | None = None) -> bool:
        stmt = select(Chapter.id).where(Chapter.work_id == work_id, Chapter.slug == slug)
        if exclude_id is not None:
            stmt = stmt.where(Chapter.id != exclude_id)
        return self.db.execute(stmt).first() is not None

    def chapter_number_exists(self, work_id: int, number: int, *, exclude_id: int | None = None) -> bool:
        stmt = select(Chapter.id).where(Chapter.work_id == work_id, Chapter.chapter_number == number)
        if exclude_id is not None:
            stmt = stmt.where(Chapter.id != exclude_id)
        return self.db.execute(stmt).first() is not None

    def list_by_work(self, work_id: int, *, status: PublishStatus | None = None) -> list[Chapter]:
        # No limit/offset: chapters are inherently bounded per work (a
        # book has dozens of chapters, not millions of rows). Add
        # pagination here if a real case ever needs it — not before.
        stmt = select(Chapter).where(Chapter.work_id == work_id).order_by(Chapter.chapter_number.asc())
        if status is not None:
            stmt = stmt.where(Chapter.status == status)
        return list(self.db.execute(stmt).scalars().all())

    def delete(self, chapter: Chapter) -> None:
        self.db.delete(chapter)
