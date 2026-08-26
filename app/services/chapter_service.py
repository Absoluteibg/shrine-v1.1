"""
Business rules for Chapter. Every operation is scoped to a parent Work,
and a chapter can never be published while its parent work is not
published in practice — see get_published_by_work_and_slug, which is
the only read path the public site should use.
"""

from sqlalchemy.orm import Session

from app.core.slugs import slugify
from app.models.chapter import Chapter
from app.models.enums import PublishStatus
from app.repositories.chapter import ChapterRepository
from app.repositories.work import WorkRepository
from app.schemas.chapter import ChapterCreate, ChapterUpdate
from app.services.exceptions import ChapterNotFoundError, DuplicateChapterNumberError, WorkNotFoundError
from app.services.publishing import apply_transition


class ChapterService:
    def __init__(self, db: Session):
        self.db = db
        self.chapters = ChapterRepository(db)
        self.works = WorkRepository(db)

    # ---------------------------------------------------------------- reads

    def get_for_admin(self, chapter_id: int) -> Chapter:
        chapter = self.chapters.get_by_id(chapter_id)
        if chapter is None:
            raise ChapterNotFoundError(f"Chapter {chapter_id} not found")
        return chapter

    def get_published_by_work_and_slug(self, work_slug: str, chapter_slug: str) -> Chapter:
        """
        Fetch a chapter for public display. A chapter is only reachable
        publicly when BOTH it and its parent work are PUBLISHED — an
        archived/draft parent hides all of its chapters regardless of
        their own status.
        """
        _, chapter = self.get_published_chapter_with_work(work_slug, chapter_slug)
        return chapter

    def get_published_chapter_with_work(self, work_slug: str, chapter_slug: str):
        """
        Like get_published_by_work_and_slug, but also returns the parent
        Work. The chapter reading page needs both (breadcrumb, work
        title, work type) — this does one work lookup instead of two.
        """
        work = self.works.get_by_slug(work_slug)
        if work is None or work.status != PublishStatus.PUBLISHED:
            raise ChapterNotFoundError(f"Published chapter '{chapter_slug}' not found")

        chapter = self.chapters.get_by_work_and_slug(work.id, chapter_slug)
        if chapter is None or chapter.status != PublishStatus.PUBLISHED:
            raise ChapterNotFoundError(f"Published chapter '{chapter_slug}' not found")
        return work, chapter

    def get_navigation(self, chapter: Chapter) -> tuple[Chapter | None, Chapter | None]:
        """
        (previous, next) published chapters within the same work, for
        reading navigation. Chapters per work are inherently few, so
        this just reuses list_published_for_work rather than a bespoke
        query — no pagination needed at this scale.
        """
        siblings = self.list_published_for_work(chapter.work_id)
        ids = [c.id for c in siblings]
        idx = ids.index(chapter.id)
        previous = siblings[idx - 1] if idx > 0 else None
        upcoming = siblings[idx + 1] if idx < len(siblings) - 1 else None
        return previous, upcoming

    def list_for_admin(self, work_id: int) -> list[Chapter]:
        return self.chapters.list_by_work(work_id)

    def list_published_for_work(self, work_id: int) -> list[Chapter]:
        return self.chapters.list_by_work(work_id, status=PublishStatus.PUBLISHED)

    # --------------------------------------------------------------- writes

    def create_chapter(self, work_id: int, data: ChapterCreate) -> Chapter:
        if self.works.get_by_id(work_id) is None:
            raise WorkNotFoundError(f"Work {work_id} not found")

        if self.chapters.chapter_number_exists(work_id, data.chapter_number):
            raise DuplicateChapterNumberError(
                f"Chapter number {data.chapter_number} already exists for work {work_id}"
            )

        chapter = Chapter(
            work_id=work_id,
            title=data.title,
            slug=self._unique_slug(work_id, data.slug or data.title),
            content=data.content,
            chapter_number=data.chapter_number,
            status=PublishStatus.DRAFT,
        )
        self.chapters.create(chapter)
        self.db.commit()
        self.db.refresh(chapter)
        return chapter

    def update_chapter(self, chapter_id: int, data: ChapterUpdate) -> Chapter:
        chapter = self.get_for_admin(chapter_id)

        if data.title is not None:
            chapter.title = data.title
        if data.content is not None:
            chapter.content = data.content
        if data.chapter_number is not None and data.chapter_number != chapter.chapter_number:
            if self.chapters.chapter_number_exists(chapter.work_id, data.chapter_number, exclude_id=chapter.id):
                raise DuplicateChapterNumberError(
                    f"Chapter number {data.chapter_number} already exists for work {chapter.work_id}"
                )
            chapter.chapter_number = data.chapter_number

        self.db.commit()
        self.db.refresh(chapter)
        return chapter

    def set_status(self, chapter_id: int, new_status: PublishStatus) -> Chapter:
        chapter = self.get_for_admin(chapter_id)
        chapter.published_at = apply_transition(
            current_status=chapter.status,
            new_status=new_status,
            current_published_at=chapter.published_at,
        )
        chapter.status = new_status
        self.db.commit()
        self.db.refresh(chapter)
        return chapter

    def publish(self, chapter_id: int) -> Chapter:
        return self.set_status(chapter_id, PublishStatus.PUBLISHED)

    def unpublish(self, chapter_id: int) -> Chapter:
        return self.set_status(chapter_id, PublishStatus.DRAFT)

    def archive(self, chapter_id: int) -> Chapter:
        return self.set_status(chapter_id, PublishStatus.ARCHIVED)

    def delete_chapter(self, chapter_id: int) -> None:
        chapter = self.get_for_admin(chapter_id)
        self.chapters.delete(chapter)
        self.db.commit()

    # ------------------------------------------------------------ internals

    def _unique_slug(self, work_id: int, seed: str, *, exclude_id: int | None = None) -> str:
        base = slugify(seed)
        candidate = base
        n = 2
        while self.chapters.slug_exists_for_work(work_id, candidate, exclude_id=exclude_id):
            candidate = f"{base}-{n}"
            n += 1
        return candidate
