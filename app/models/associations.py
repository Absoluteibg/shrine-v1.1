"""
Pure join tables — no columns beyond the foreign keys, so these are
plain SQLAlchemy Core Tables rather than mapped classes. Kept in their
own module so work.py and tag.py don't need to import each other just
to declare the many-to-many relationship.
"""

from sqlalchemy import Column, ForeignKey, Table

from app.db.database import Base

work_tags = Table(
    "work_tags",
    Base.metadata,
    Column("work_id", ForeignKey("works.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)
