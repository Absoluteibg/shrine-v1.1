from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import PublishStatus


class ChapterCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    # 500,000 chars (~500KB) is far beyond any real chapter — a novel's
    # entire word count, several times over — so this bounds pathological
    # input (an accidental huge paste, a scripted abuse attempt) without
    # constraining any real use.
    content: str = Field(default="", max_length=500_000)
    chapter_number: int = Field(gt=0)
    slug: str | None = Field(default=None, max_length=255)


class ChapterUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = Field(default=None, max_length=500_000)
    chapter_number: int | None = Field(default=None, gt=0)


class ChapterSummary(BaseModel):
    """Table-of-contents shape — deliberately excludes `content` (can be large)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    work_id: int
    title: str
    slug: str
    chapter_number: int
    status: PublishStatus
    published_at: datetime | None


class ChapterRead(ChapterSummary):
    content: str
    created_at: datetime
    updated_at: datetime
