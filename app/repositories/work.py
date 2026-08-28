"""
Persistence for Work.

Services call these methods instead of writing `select()` statements
directly, so query logic — including what "published" means at the
query level — lives in exactly one place.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.enums import PublishStatus, WorkType
from app.models.work import Work

# Hard ceiling on list queries regardless of what a caller asks for —
# see project brief section 15 ("avoid unbounded database queries").
_MAX_LIMIT = 200


class WorkRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, work: Work) -> Work:
        self.db.add(work)
        self.db.flush()
        return work

    def get_by_id(self, work_id: int) -> Work | None:
        return self.db.get(Work, work_id)

    def get_by_slug(self, slug: str) -> Work | None:
        # Eager-load tags: WorkRead always needs them, so load them in
        # the same query instead of lazy-loading per access (N+1).
        stmt = select(Work).where(Work.slug == slug).options(selectinload(Work.tags))
        return self.db.execute(stmt).scalar_one_or_none()

    def slug_exists(self, slug: str, *, exclude_id: int | None = None) -> bool:
        stmt = select(Work.id).where(Work.slug == slug)
        if exclude_id is not None:
            stmt = stmt.where(Work.id != exclude_id)
        return self.db.execute(stmt).first() is not None

    def list_all(
        self,
        *,
        status: PublishStatus | None = None,
        type: WorkType | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Work]:
        limit = max(1, min(limit, _MAX_LIMIT))
        offset = max(0, offset)

        stmt = select(Work).order_by(Work.created_at.desc())
        if status is not None:
            stmt = stmt.where(Work.status == status)
        if type is not None:
            stmt = stmt.where(Work.type == type)
        stmt = stmt.limit(limit).offset(offset)
        return list(self.db.execute(stmt).scalars().all())

    def list_published(
        self, *, type: WorkType | None = None, limit: int = 50, offset: int = 0
    ) -> list[Work]:
        return self.list_all(status=PublishStatus.PUBLISHED, type=type, limit=limit, offset=offset)

    def count_all(self, *, status: PublishStatus | None = None, type: WorkType | None = None) -> int:
        """Row count without loading rows — used by the admin dashboard's status tiles."""
        stmt = select(func.count()).select_from(Work)
        if status is not None:
            stmt = stmt.where(Work.status == status)
        if type is not None:
            stmt = stmt.where(Work.type == type)
        return self.db.execute(stmt).scalar_one()

    def delete(self, work: Work) -> None:
        self.db.delete(work)
