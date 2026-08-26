from datetime import datetime, timezone

import pytest

from app.models.enums import PublishStatus
from app.services.exceptions import InvalidStateTransitionError
from app.services.publishing import apply_transition

DRAFT = PublishStatus.DRAFT
PUBLISHED = PublishStatus.PUBLISHED
ARCHIVED = PublishStatus.ARCHIVED


def test_draft_to_published_sets_published_at():
    result = apply_transition(current_status=DRAFT, new_status=PUBLISHED, current_published_at=None)
    assert isinstance(result, datetime)


def test_unpublish_preserves_original_published_at():
    original = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = apply_transition(current_status=PUBLISHED, new_status=DRAFT, current_published_at=original)
    assert result == original


def test_republishing_does_not_reset_published_at():
    original = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = apply_transition(current_status=DRAFT, new_status=PUBLISHED, current_published_at=original)
    assert result == original


def test_archiving_preserves_published_at():
    original = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = apply_transition(current_status=PUBLISHED, new_status=ARCHIVED, current_published_at=original)
    assert result == original


def test_restoring_from_archive_to_draft_is_allowed():
    original = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = apply_transition(current_status=ARCHIVED, new_status=DRAFT, current_published_at=original)
    assert result == original


def test_republishing_directly_from_archive_is_allowed():
    original = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = apply_transition(current_status=ARCHIVED, new_status=PUBLISHED, current_published_at=original)
    assert result == original


def test_setting_the_same_status_is_a_noop():
    original = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = apply_transition(current_status=PUBLISHED, new_status=PUBLISHED, current_published_at=original)
    assert result == original


def test_a_never_published_draft_cannot_be_archived():
    """
    ARCHIVED means "was published, then retired". A draft that was
    never published has nothing to retire — it should be deleted
    outright instead, so this transition is rejected.
    """
    with pytest.raises(InvalidStateTransitionError):
        apply_transition(current_status=DRAFT, new_status=ARCHIVED, current_published_at=None)
