"""
Importing this package registers every ORM model on the shared
declarative Base (app/db/database.py). Alembic's env.py does
`import app.models` for exactly this reason — autogenerate can only see
tables whose model classes have actually been imported somewhere.
"""

from app.models.associations import work_tags
from app.models.chapter import Chapter
from app.models.enums import PublishStatus, WorkType
from app.models.tag import Tag
from app.models.work import Work

__all__ = [
    "Work",
    "Chapter",
    "Tag",
    "work_tags",
    "WorkType",
    "PublishStatus",
]
