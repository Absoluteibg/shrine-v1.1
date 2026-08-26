"""
Persistence for Tag. `get_or_create` is here (not in the service) because
"does a tag with this name already exist" is a query concern.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.slugs import slugify
from app.models.tag import Tag


class TagRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_slug(self, slug: str) -> Tag | None:
        return self.db.execute(select(Tag).where(Tag.slug == slug)).scalar_one_or_none()

    def get_by_name(self, name: str) -> Tag | None:
        return self.db.execute(select(Tag).where(Tag.name == name)).scalar_one_or_none()

    def get_or_create(self, name: str) -> Tag:
        """
        Look up by SLUG, not name — "Nature" and "nature" must resolve
        to the same tag. `name` only controls the display label the
        *first* time a given slug is created.
        """
        name = name.strip()
        slug = slugify(name)
        existing = self.get_by_slug(slug)
        if existing is not None:
            return existing
        tag = Tag(name=name, slug=slug)
        self.db.add(tag)
        self.db.flush()
        return tag

    def list_all(self) -> list[Tag]:
        return list(self.db.execute(select(Tag).order_by(Tag.name.asc())).scalars().all())

    def delete(self, tag: Tag) -> None:
        self.db.delete(tag)
