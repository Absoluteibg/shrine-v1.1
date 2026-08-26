import pytest

from app.models.enums import WorkType
from app.schemas.work import WorkCreate, WorkUpdate
from app.services.exceptions import TagNotFoundError
from app.services.tag_service import TagService
from app.services.work_service import WorkService


@pytest.fixture()
def work_service(db_session):
    return WorkService(db_session)


@pytest.fixture()
def tag_service(db_session):
    return TagService(db_session)


def test_get_by_slug_missing_raises(tag_service):
    with pytest.raises(TagNotFoundError):
        tag_service.get_by_slug("does-not-exist")


def test_list_all_returns_tags_created_via_works(tag_service, work_service):
    work_service.create_work(WorkCreate(title="A", type=WorkType.POEM, tag_names=["loss", "memory"]))
    slugs = {t.slug for t in tag_service.list_all()}
    assert {"loss", "memory"}.issubset(slugs)


def test_delete_unused_removes_orphaned_tags_only(tag_service, work_service):
    work = work_service.create_work(WorkCreate(title="A", type=WorkType.POEM, tag_names=["shared", "orphan"]))
    # Remove "orphan" from the work's tags, leaving it unattached to anything.
    work_service.update_work(work.id, WorkUpdate(tag_names=["shared"]))

    removed = tag_service.delete_unused()

    assert removed == 1
    remaining_slugs = {t.slug for t in tag_service.list_all()}
    assert "shared" in remaining_slugs
    assert "orphan" not in remaining_slugs
