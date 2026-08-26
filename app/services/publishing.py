"""
Shared publishing-state rules for Work and Chapter.

Both entities use the same DRAFT/PUBLISHED/ARCHIVED vocabulary and the
same rules, so those rules are defined once here instead of as two
copies (in WorkService and ChapterService) that could quietly drift
apart.

This is also the seam a future scheduled-publishing feature ("publish
at 9am tomorrow") would extend: it needs a new field (e.g.
`scheduled_for`) and a new transition here, not a redesign of the
Work/Chapter table shape or the status vocabulary itself.
"""

from datetime import datetime, timezone

from app.models.enums import PublishStatus
from app.services.exceptions import InvalidStateTransitionError

# ARCHIVED means "this was published, then retired" — so a draft that
# was never published can't go straight to ARCHIVED. An unwanted draft
# is deleted outright (a separate operation), not archived.
_ALLOWED_TRANSITIONS: dict[PublishStatus, set[PublishStatus]] = {
    PublishStatus.DRAFT: {PublishStatus.PUBLISHED},
    PublishStatus.PUBLISHED: {PublishStatus.DRAFT, PublishStatus.ARCHIVED},
    PublishStatus.ARCHIVED: {PublishStatus.DRAFT, PublishStatus.PUBLISHED},
}


def apply_transition(
    *,
    current_status: PublishStatus,
    new_status: PublishStatus,
    current_published_at: datetime | None,
) -> datetime | None:
    """
    Validate a status transition and return the `published_at` value the
    entity should have afterward.

    Rules:
      - Every transition must be one of the explicitly allowed edges above.
      - `published_at` is set the first time something becomes PUBLISHED,
        and preserved afterward — unpublishing, archiving, and
        republishing do not erase the original publish date.
    """
    if new_status == current_status:
        return current_published_at

    allowed = _ALLOWED_TRANSITIONS.get(current_status, set())
    if new_status not in allowed:
        raise InvalidStateTransitionError(
            f"Cannot transition from {current_status.value} to {new_status.value}"
        )

    if new_status == PublishStatus.PUBLISHED and current_published_at is None:
        return datetime.now(timezone.utc)

    return current_published_at
