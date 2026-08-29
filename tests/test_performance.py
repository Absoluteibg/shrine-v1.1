"""
Performance regression tests.

These count actual SQL statements executed (via a SQLAlchemy event
listener) rather than asserting on response content — the point is to
catch an N+1 pattern coming back, not to re-test business logic already
covered elsewhere.
"""

from contextlib import contextmanager

from sqlalchemy import event

from app.models.enums import WorkType
from app.schemas.chapter import ChapterCreate
from app.schemas.work import WorkCreate
from app.services.chapter_service import ChapterService
from app.services.work_service import WorkService


@contextmanager
def _count_queries(engine):
    count = 0

    def _on_execute(*args, **kwargs):
        nonlocal count
        count += 1

    event.listen(engine, "before_cursor_execute", _on_execute)
    try:
        yield lambda: count
    finally:
        event.remove(engine, "before_cursor_execute", _on_execute)


def test_sitemap_query_count_does_not_scale_with_work_count(client, db_session, test_engine):
    """
    Regression guard for the N+1 fixed in Phase 5: sitemap generation
    used to run one extra chapter query per published work. Creating
    several works with several chapters each and asserting the query
    count stays low (not proportional to work/chapter count) would
    catch that pattern coming back.
    """
    work_service = WorkService(db_session)
    chapter_service = ChapterService(db_session)

    for i in range(6):
        work = work_service.create_work(WorkCreate(title=f"Work {i}", type=WorkType.NOVEL))
        work_service.publish(work.id)
        for n in range(1, 4):
            chapter = chapter_service.create_chapter(
                work.id, ChapterCreate(title=f"Chapter {n}", chapter_number=n)
            )
            chapter_service.publish(chapter.id)

    with _count_queries(test_engine) as get_count:
        response = client.get("/sitemap.xml")

    assert response.status_code == 200
    assert "/novels/work-5" in response.text
    # 4 queries (one per work type) + 1 grouped chapter query, plus a
    # small constant for session/transaction bookkeeping — nowhere near
    # "6 works x 1 query each" (6+) if the N+1 had come back, let alone
    # 6 works x 3 chapters worth of per-row queries.
    assert get_count() <= 10, f"expected a small constant number of queries, got {get_count()}"
