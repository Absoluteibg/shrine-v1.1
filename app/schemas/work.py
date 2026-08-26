"""
Work request/response contracts.

Kept separate from app.models.work.Work on purpose: the DB schema and
the API/service contract are allowed to diverge (e.g. the DB gains a
column the API doesn't expose yet) without one forcing a change to the
other.

Two read shapes exist for a reason (see section 15 of the project
brief: don't load more than a view needs):
  - WorkSummary: list views — no description, no tags.
  - WorkRead: single-work detail views — full data.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import PublishStatus, WorkType
from app.schemas.tag import TagRead


class WorkCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    type: WorkType
    description: str | None = Field(default=None, max_length=5000)
    cover_image: str | None = Field(default=None, max_length=500)
    # Omit to auto-derive from title. Provide to control the URL explicitly.
    slug: str | None = Field(default=None, max_length=255)
    tag_names: list[str] = Field(default_factory=list)


class WorkUpdate(BaseModel):
    """All fields optional — only what's provided gets changed. No slug field: see Work.slug."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    type: WorkType | None = None
    description: str | None = Field(default=None, max_length=5000)
    cover_image: str | None = Field(default=None, max_length=500)
    tag_names: list[str] | None = None


class WorkSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    slug: str
    type: WorkType
    status: PublishStatus
    cover_image: str | None
    published_at: datetime | None


class WorkRead(WorkSummary):
    description: str | None
    created_at: datetime
    updated_at: datetime
    tags: list[TagRead] = Field(default_factory=list)
