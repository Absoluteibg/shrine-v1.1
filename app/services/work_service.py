"""
Business rules for Work.

Routers (Phase 3/4) should never import WorkRepository directly — every
Work operation, including "what counts as published", goes through this
service. The service owns the transaction boundary: repository methods
add/flush but never commit, so a multi-step operation (e.g. create a
work AND attach several tags) either fully succeeds or fully rolls back.
"""

from sqlalchemy.orm import Session

from app.core.slugs import slugify
from app.models.enums import PublishStatus, WorkType
from app.models.tag import Tag
from app.models.work import Work
from app.repositories.tag import TagRepository
from app.repositories.work import WorkRepository
from app.schemas.work import WorkCreate, WorkUpdate
from app.services.exceptions import WorkNotFoundError
from app.services.publishing import apply_transition


class WorkService:
    def __init__(self, db: Session):
        self.db = db
        self.works = WorkRepository(db)
        self.tags = TagRepository(db)

    # ---------------------------------------------------------------- reads

    def get_for_admin(self, work_id: int) -> Work:
        """Fetch a work regardless of status — for the CMS, never the public site."""
        work = self.works.get_by_id(work_id)
        if work is None:
            raise WorkNotFoundError(f"Work {work_id} not found")
        return work

    def get_published_by_slug(self, slug: str, *, type: WorkType | None = None) -> Work:
        """
        Fetch a work for public display. Raises WorkNotFoundError for
        anything not PUBLISHED — a draft or archived work is treated as
        not existing from the public site's point of view, on purpose.
        """
        work = self.works.get_by_slug(slug)
        if work is None or work.status != PublishStatus.PUBLISHED:
            raise WorkNotFoundError(f"Published work '{slug}' not found")
        if type is not None and work.type != type:
            raise WorkNotFoundError(f"Published work '{slug}' not found")
        return work

    def list_for_admin(
        self,
        *,
        status: PublishStatus | None = None,
        type: WorkType | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Work]:
        return self.works.list_all(status=status, type=type, limit=limit, offset=offset)

    def list_published(
        self, *, type: WorkType | None = None, limit: int = 50, offset: int = 0
    ) -> list[Work]:
        return self.works.list_published(type=type, limit=limit, offset=offset)

    # --------------------------------------------------------------- writes

    def create_work(self, data: WorkCreate) -> Work:
        work = Work(
            title=data.title,
            slug=self._unique_slug(data.slug or data.title),
            type=data.type,
            description=data.description,
            cover_image=data.cover_image,
            status=PublishStatus.DRAFT,
        )
        work.tags = self._resolve_tags(data.tag_names)
        self.works.create(work)
        self.db.commit()
        self.db.refresh(work)
        return work

    def update_work(self, work_id: int, data: WorkUpdate) -> Work:
        work = self.get_for_admin(work_id)

        if data.title is not None:
            work.title = data.title
        if data.type is not None:
            work.type = data.type
        if data.description is not None:
            work.description = data.description
        if data.cover_image is not None:
            work.cover_image = data.cover_image
        if data.tag_names is not None:
            work.tags = self._resolve_tags(data.tag_names)

        self.db.commit()
        self.db.refresh(work)
        return work

    def set_status(self, work_id: int, new_status: PublishStatus) -> Work:
        work = self.get_for_admin(work_id)
        work.published_at = apply_transition(
            current_status=work.status,
            new_status=new_status,
            current_published_at=work.published_at,
        )
        work.status = new_status
        self.db.commit()
        self.db.refresh(work)
        return work

    def publish(self, work_id: int) -> Work:
        return self.set_status(work_id, PublishStatus.PUBLISHED)

    def unpublish(self, work_id: int) -> Work:
        return self.set_status(work_id, PublishStatus.DRAFT)

    def archive(self, work_id: int) -> Work:
        return self.set_status(work_id, PublishStatus.ARCHIVED)

    def delete_work(self, work_id: int) -> None:
        """Deletes the work AND its chapters (cascade — see Work.chapters)."""
        work = self.get_for_admin(work_id)
        self.works.delete(work)
        self.db.commit()

    # ------------------------------------------------------------ internals

    def _resolve_tags(self, tag_names: list[str]) -> list[Tag]:
        # Dedupe by the RESOLVED tag's id, not the raw input string.
        # get_or_create normalizes case/accents via slug (see
        # TagRepository.get_or_create), so "nature" and "Nature" resolve
        # to the same Tag object — deduping on the raw strings instead
        # would leave that object in the list twice, and SQLAlchemy
        # would try to insert the same (work_id, tag_id) row twice on
        # flush.
        resolved: dict[int, Tag] = {}
        for raw in tag_names:
            name = raw.strip()
            if not name:
                continue
            tag = self.tags.get_or_create(name)
            resolved[tag.id] = tag
        return list(resolved.values())

    def _unique_slug(self, seed: str, *, exclude_id: int | None = None) -> str:
        base = slugify(seed)
        candidate = base
        n = 2
        while self.works.slug_exists(candidate, exclude_id=exclude_id):
            candidate = f"{base}-{n}"
            n += 1
        return candidate
