import pytest

from app.models.enums import PublishStatus, WorkType
from app.schemas.work import WorkCreate, WorkUpdate
from app.services.exceptions import InvalidStateTransitionError, WorkNotFoundError
from app.services.work_service import WorkService


@pytest.fixture()
def work_service(db_session):
    return WorkService(db_session)


def test_create_work_generates_slug_and_starts_as_draft(work_service):
    work = work_service.create_work(WorkCreate(title="The Last Summer", type=WorkType.NOVEL))

    assert work.id is not None
    assert work.slug == "the-last-summer"
    assert work.status == PublishStatus.DRAFT
    assert work.published_at is None


def test_duplicate_title_gets_a_unique_slug(work_service):
    first = work_service.create_work(WorkCreate(title="Echoes", type=WorkType.POEM))
    second = work_service.create_work(WorkCreate(title="Echoes", type=WorkType.POEM))

    assert first.slug == "echoes"
    assert second.slug == "echoes-2"


def test_explicit_slug_is_respected(work_service):
    work = work_service.create_work(
        WorkCreate(title="A Long Title Here", type=WorkType.ESSAY, slug="short-slug")
    )
    assert work.slug == "short-slug"


def test_create_work_attaches_tags_deduplicated(work_service):
    work = work_service.create_work(
        WorkCreate(title="Winter", type=WorkType.STORY, tag_names=["nature", "Nature", "seasons"])
    )
    names = sorted(t.name for t in work.tags)
    # "nature" and "Nature" collide on the same slug -> one tag survives,
    # keeping whichever casing was seen first ("nature").
    assert names == ["nature", "seasons"]


def test_reusing_a_tag_name_reuses_the_same_tag(work_service):
    a = work_service.create_work(WorkCreate(title="A", type=WorkType.POEM, tag_names=["grief"]))
    b = work_service.create_work(WorkCreate(title="B", type=WorkType.POEM, tag_names=["grief"]))
    assert a.tags[0].id == b.tags[0].id


def test_draft_work_is_not_visible_via_published_lookup(work_service):
    work = work_service.create_work(WorkCreate(title="Hidden", type=WorkType.NOVEL))
    with pytest.raises(WorkNotFoundError):
        work_service.get_published_by_slug(work.slug)


def test_published_work_is_visible_via_published_lookup(work_service):
    work = work_service.create_work(WorkCreate(title="Visible", type=WorkType.NOVEL))
    work_service.publish(work.id)

    found = work_service.get_published_by_slug("visible")
    assert found.id == work.id
    assert found.status == PublishStatus.PUBLISHED
    assert found.published_at is not None


def test_published_lookup_respects_type_filter(work_service):
    work = work_service.create_work(WorkCreate(title="Sonnet", type=WorkType.POEM))
    work_service.publish(work.id)

    with pytest.raises(WorkNotFoundError):
        work_service.get_published_by_slug("sonnet", type=WorkType.NOVEL)

    assert work_service.get_published_by_slug("sonnet", type=WorkType.POEM).id == work.id


def test_archived_work_is_not_publicly_visible(work_service):
    work = work_service.create_work(WorkCreate(title="Fading", type=WorkType.STORY))
    work_service.publish(work.id)
    work_service.archive(work.id)

    with pytest.raises(WorkNotFoundError):
        work_service.get_published_by_slug("fading")


def test_unpublish_hides_it_again_but_keeps_original_published_at(work_service):
    work = work_service.create_work(WorkCreate(title="On and Off", type=WorkType.ESSAY))
    published = work_service.publish(work.id)
    first_published_at = published.published_at

    unpublished = work_service.unpublish(work.id)
    assert unpublished.status == PublishStatus.DRAFT
    assert unpublished.published_at == first_published_at  # preserved, not cleared

    republished = work_service.publish(work.id)
    assert republished.published_at == first_published_at  # still preserved


def test_archiving_a_never_published_draft_is_rejected(work_service):
    work = work_service.create_work(WorkCreate(title="Too Soon", type=WorkType.STORY))
    with pytest.raises(InvalidStateTransitionError):
        work_service.archive(work.id)


def test_update_work_only_changes_provided_fields(work_service):
    work = work_service.create_work(
        WorkCreate(title="Original", type=WorkType.NOVEL, description="Original description")
    )
    updated = work_service.update_work(work.id, WorkUpdate(description="New description"))

    assert updated.title == "Original"  # untouched
    assert updated.description == "New description"


def test_update_work_slug_is_never_exposed_as_editable(work_service):
    work = work_service.create_work(WorkCreate(title="Stable URL", type=WorkType.NOVEL))
    updated = work_service.update_work(work.id, WorkUpdate(title="Renamed Completely"))
    assert updated.slug == "stable-url"  # unchanged despite the title edit


def test_delete_work_removes_it(work_service):
    work = work_service.create_work(WorkCreate(title="Temporary", type=WorkType.STORY))
    work_service.delete_work(work.id)

    with pytest.raises(WorkNotFoundError):
        work_service.get_for_admin(work.id)


def test_list_for_admin_sees_drafts_list_published_does_not(work_service):
    draft = work_service.create_work(WorkCreate(title="Draft One", type=WorkType.NOVEL))
    published = work_service.create_work(WorkCreate(title="Published One", type=WorkType.NOVEL))
    work_service.publish(published.id)

    admin_ids = {w.id for w in work_service.list_for_admin()}
    public_ids = {w.id for w in work_service.list_published()}

    assert draft.id in admin_ids
    assert published.id in admin_ids
    assert draft.id not in public_ids
    assert published.id in public_ids
