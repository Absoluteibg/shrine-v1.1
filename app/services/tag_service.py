"""
Business rules for Tag.

Deliberately thin: most tag creation happens implicitly, through
WorkService.get_or_create when a work is tagged by name. This service
covers standalone tag operations — browsing all tags and admin cleanup.
"""

from sqlalchemy.orm import Session

from app.models.tag import Tag
from app.repositories.tag import TagRepository
from app.services.exceptions import TagNotFoundError


class TagService:
    def __init__(self, db: Session):
        self.db = db
        self.tags = TagRepository(db)

    def list_all(self) -> list[Tag]:
        return self.tags.list_all()

    def get_by_slug(self, slug: str) -> Tag:
        tag = self.tags.get_by_slug(slug)
        if tag is None:
            raise TagNotFoundError(f"Tag '{slug}' not found")
        return tag

    def delete_unused(self) -> int:
        """
        Remove tags with no associated works. Returns the number removed.
        Admin housekeeping after untagging or deleting works — not
        called automatically, since a temporarily-unused tag (e.g. on a
        draft mid-edit) shouldn't vanish on its own.
        """
        removed = 0
        for tag in self.tags.list_all():
            if not tag.works:
                self.tags.delete(tag)
                removed += 1
        if removed:
            self.db.commit()
        return removed
