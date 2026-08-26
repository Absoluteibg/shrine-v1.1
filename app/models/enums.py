"""
Domain enums shared by ORM models (app/models) and API/service schemas
(app/schemas). Defined once here so the vocabulary can't drift between
the two layers.
"""

import enum

from sqlalchemy import Enum as SAEnum


class WorkType(str, enum.Enum):
    NOVEL = "novel"
    STORY = "story"
    POEM = "poem"
    ESSAY = "essay"


class PublishStatus(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


def status_enum_type() -> SAEnum:
    """
    Shared SQLAlchemy column type for PublishStatus, used by both Work
    and Chapter so "how status is stored" (lowercase values + a CHECK
    constraint) is defined once instead of as two copies that could
    quietly drift apart.
    """
    return SAEnum(
        PublishStatus,
        native_enum=False,
        length=20,
        create_constraint=True,
        # Persist "draft"/"published"/"archived" (the enum's .value),
        # not the member NAME ("DRAFT"). SQLAlchemy's default is to
        # store .name, which would silently diverge from server_default
        # and from how these values are serialized in the API.
        values_callable=lambda enum_cls: [member.value for member in enum_cls],
    )
