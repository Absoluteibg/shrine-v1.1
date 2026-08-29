"""
Persistence for Chapter. Every query here is scoped to a work_id — this
module never returns a chapter without knowing which work it belongs
to, which keeps "a chapter always belongs to exactly one work" true at
the query layer, not just by convention.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session, defer

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
        #
        # defer(content): every current caller of this method is a
        # table-of-contents-style view (public work page, admin chapter
        # list, prev/next reading nav) that only needs title/number/
        # status/slug. Without this, viewing a 40-chapter novel's table
        # of contents would load every chapter's full body text into
        # memory just to render a list of titles — exactly the "loading
        # entire novels when only metadata is required" case the
        # project brief calls out. The one caller that DOES need body
        # text (the actual reading page) uses get_by_work_and_slug
        # instead, which is unaffected.
        stmt = (
            select(Chapter)
            .options(defer(Chapter.content))
            .where(Chapter.work_id == work_id)
            .order_by(Chapter.chapter_number.asc())
        )
        if status is not None:
            stmt = stmt.where(Chapter.status == status)
        return list(self.db.execute(stmt).scalars().all())

    def list_published_grouped_by_work(self, work_ids: list[int]) -> dict[int, list[Chapter]]:
        """
        Published chapters for MULTIPLE works in one query, grouped by
        work_id. Used by sitemap generation, which needs every published
        work's chapter slugs — querying once per work here would be a
        textbook N+1 (bounded, since work counts are small for a
        personal site, but a real one, and cheap to just not have).
        """
        if not work_ids:
            return {}
        stmt = (
            select(Chapter)
            .options(defer(Chapter.content))
            .where(Chapter.work_id.in_(work_ids), Chapter.status == PublishStatus.PUBLISHED)
            .order_by(Chapter.work_id, Chapter.chapter_number.asc())
        )
        grouped: dict[int, list[Chapter]] = {work_id: [] for work_id in work_ids}
        for chapter in self.db.execute(stmt).scalars().all():
            grouped[chapter.work_id].append(chapter)
        return grouped

    def delete(self, chapter: Chapter) -> None:
        self.db.delete(chapter)
