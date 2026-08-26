import pytest

from app.models.enums import PublishStatus, WorkType
from app.schemas.chapter import ChapterCreate, ChapterUpdate
from app.schemas.work import WorkCreate
from app.services.chapter_service import ChapterService
from app.services.exceptions import ChapterNotFoundError, DuplicateChapterNumberError, WorkNotFoundError
from app.services.work_service import WorkService


@pytest.fixture()
def work_service(db_session):
    return WorkService(db_session)


@pytest.fixture()
def chapter_service(db_session):
    return ChapterService(db_session)


@pytest.fixture()
def a_work(work_service):
    return work_service.create_work(WorkCreate(title="The Long Road", type=WorkType.NOVEL))


def test_create_chapter_generates_slug_and_starts_as_draft(chapter_service, a_work):
    chapter = chapter_service.create_chapter(
        a_work.id, ChapterCreate(title="A Beginning", content="It was a dark night.", chapter_number=1)
    )
    assert chapter.slug == "a-beginning"
    assert chapter.status == PublishStatus.DRAFT
    assert chapter.work_id == a_work.id


def test_create_chapter_for_missing_work_raises(chapter_service):
    with pytest.raises(WorkNotFoundError):
        chapter_service.create_chapter(999999, ChapterCreate(title="Nowhere", chapter_number=1))


def test_duplicate_chapter_number_within_work_is_rejected(chapter_service, a_work):
    chapter_service.create_chapter(a_work.id, ChapterCreate(title="One", chapter_number=1))
    with pytest.raises(DuplicateChapterNumberError):
        chapter_service.create_chapter(a_work.id, ChapterCreate(title="One Again", chapter_number=1))


def test_same_chapter_number_allowed_across_different_works(chapter_service, work_service, a_work):
    other_work = work_service.create_work(WorkCreate(title="A Different Book", type=WorkType.NOVEL))
    chapter_service.create_chapter(a_work.id, ChapterCreate(title="Ch1", chapter_number=1))
    # Should not raise — chapter numbers are scoped per work.
    chapter_service.create_chapter(other_work.id, ChapterCreate(title="Ch1", chapter_number=1))


def test_duplicate_title_within_same_work_gets_unique_slug(chapter_service, a_work):
    first = chapter_service.create_chapter(a_work.id, ChapterCreate(title="Prologue", chapter_number=1))
    second = chapter_service.create_chapter(a_work.id, ChapterCreate(title="Prologue", chapter_number=2))
    assert first.slug == "prologue"
    assert second.slug == "prologue-2"


def test_same_chapter_slug_allowed_across_different_works(chapter_service, work_service, a_work):
    other_work = work_service.create_work(WorkCreate(title="Yet Another Book", type=WorkType.NOVEL))
    a = chapter_service.create_chapter(a_work.id, ChapterCreate(title="Prologue", chapter_number=1))
    b = chapter_service.create_chapter(other_work.id, ChapterCreate(title="Prologue", chapter_number=1))
    assert a.slug == b.slug == "prologue"


def test_chapter_not_visible_if_work_is_draft_even_if_chapter_is_published(
    chapter_service, work_service, a_work
):
    chapter = chapter_service.create_chapter(a_work.id, ChapterCreate(title="Ch1", chapter_number=1))
    chapter_service.publish(chapter.id)
    # a_work itself was never published.
    with pytest.raises(ChapterNotFoundError):
        chapter_service.get_published_by_work_and_slug(a_work.slug, chapter.slug)


def test_chapter_not_visible_if_draft_even_if_work_is_published(chapter_service, work_service, a_work):
    chapter = chapter_service.create_chapter(a_work.id, ChapterCreate(title="Ch1", chapter_number=1))
    work_service.publish(a_work.id)
    # chapter itself was never published.
    with pytest.raises(ChapterNotFoundError):
        chapter_service.get_published_by_work_and_slug(a_work.slug, chapter.slug)


def test_chapter_visible_when_both_work_and_chapter_are_published(chapter_service, work_service, a_work):
    chapter = chapter_service.create_chapter(a_work.id, ChapterCreate(title="Ch1", chapter_number=1))
    work_service.publish(a_work.id)
    chapter_service.publish(chapter.id)

    found = chapter_service.get_published_by_work_and_slug(a_work.slug, chapter.slug)
    assert found.id == chapter.id


def test_update_chapter_number_checks_for_collision(chapter_service, a_work):
    chapter_service.create_chapter(a_work.id, ChapterCreate(title="One", chapter_number=1))
    two = chapter_service.create_chapter(a_work.id, ChapterCreate(title="Two", chapter_number=2))

    with pytest.raises(DuplicateChapterNumberError):
        chapter_service.update_chapter(two.id, ChapterUpdate(chapter_number=1))


def test_update_chapter_to_its_own_number_is_fine(chapter_service, a_work):
    chapter = chapter_service.create_chapter(a_work.id, ChapterCreate(title="One", chapter_number=1))
    updated = chapter_service.update_chapter(chapter.id, ChapterUpdate(chapter_number=1, title="One (revised)"))
    assert updated.chapter_number == 1
    assert updated.title == "One (revised)"


def test_list_published_for_work_excludes_drafts(chapter_service, a_work):
    published = chapter_service.create_chapter(a_work.id, ChapterCreate(title="Live", chapter_number=1))
    chapter_service.create_chapter(a_work.id, ChapterCreate(title="Not yet", chapter_number=2))
    chapter_service.publish(published.id)

    result = chapter_service.list_published_for_work(a_work.id)
    assert [c.id for c in result] == [published.id]


def test_delete_chapter_removes_it(chapter_service, a_work):
    chapter = chapter_service.create_chapter(a_work.id, ChapterCreate(title="Gone Soon", chapter_number=1))
    chapter_service.delete_chapter(chapter.id)

    with pytest.raises(ChapterNotFoundError):
        chapter_service.get_for_admin(chapter.id)


def test_deleting_a_work_cascades_to_its_chapters(chapter_service, work_service, a_work, db_session):
    chapter = chapter_service.create_chapter(a_work.id, ChapterCreate(title="Doomed", chapter_number=1))
    work_service.delete_work(a_work.id)

    with pytest.raises(ChapterNotFoundError):
        chapter_service.get_for_admin(chapter.id)
