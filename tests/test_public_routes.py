import re

import pytest

from app.models.enums import WorkType
from app.schemas.chapter import ChapterCreate
from app.schemas.work import WorkCreate
from app.services.chapter_service import ChapterService
from app.services.work_service import WorkService


@pytest.fixture()
def services(db_session):
    return WorkService(db_session), ChapterService(db_session)


# ------------------------------------------------------------- end to end


def test_create_publish_visit_read_end_to_end(client, services):
    """
    The exact flow called out in the project brief: create a work,
    create a chapter, publish the work, visit the public page, read the
    chapter.
    """
    work_service, chapter_service = services

    work = work_service.create_work(
        WorkCreate(title="The Long Road", type=WorkType.NOVEL, description="A journey north.")
    )
    chapter = chapter_service.create_chapter(
        work.id, ChapterCreate(title="Departure", chapter_number=1, content="We left before dawn.")
    )

    # Not visible yet — nothing has been published.
    assert client.get("/novels/the-long-road").status_code == 404

    work_service.publish(work.id)
    chapter_service.publish(chapter.id)

    detail = client.get("/novels/the-long-road")
    assert detail.status_code == 200
    assert "The Long Road" in detail.text

    reading = client.get("/works/the-long-road/chapters/departure")
    assert reading.status_code == 200
    assert "We left before dawn." in reading.text
    assert 'class="reading"' in reading.text  # the signature parchment surface is active


# --------------------------------------------------------------- home page


def test_home_page_empty_state(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Nothing has been published here yet" in response.text


def test_home_page_lists_published_work(client, services):
    work_service, _ = services
    work = work_service.create_work(WorkCreate(title="Winter Light", type=WorkType.STORY))
    work_service.publish(work.id)

    response = client.get("/")
    assert "Winter Light" in response.text


def test_home_page_hides_drafts(client, services):
    work_service, _ = services
    work_service.create_work(WorkCreate(title="Unfinished Business", type=WorkType.ESSAY))

    response = client.get("/")
    assert "Unfinished Business" not in response.text
    assert "Nothing has been published here yet" in response.text


# ------------------------------------------------------------ visibility


def test_draft_work_detail_returns_404(client, services):
    work_service, _ = services
    work = work_service.create_work(WorkCreate(title="Hidden", type=WorkType.NOVEL))

    response = client.get(f"/novels/{work.slug}")
    assert response.status_code == 404
    assert "isn't in the archive" in response.text


def test_work_not_visible_under_wrong_type_segment(client, services):
    work_service, _ = services
    work = work_service.create_work(WorkCreate(title="A Sonnet", type=WorkType.POEM))
    work_service.publish(work.id)

    assert client.get(f"/poems/{work.slug}").status_code == 200
    assert client.get(f"/novels/{work.slug}").status_code == 404


def test_draft_chapter_hidden_even_when_work_is_published(client, services):
    work_service, chapter_service = services
    work = work_service.create_work(WorkCreate(title="Partly Live", type=WorkType.NOVEL))
    chapter = chapter_service.create_chapter(work.id, ChapterCreate(title="Ch1", chapter_number=1))
    work_service.publish(work.id)
    # chapter itself was never published

    assert client.get(f"/works/{work.slug}/chapters/{chapter.slug}").status_code == 404

    # And it shouldn't appear in the work's table of contents either.
    detail = client.get(f"/novels/{work.slug}")
    assert "Ch1" not in detail.text
    assert "No chapters have been published" in detail.text


def test_listing_page_only_shows_published_works_of_matching_type(client, services):
    work_service, _ = services
    published_novel = work_service.create_work(WorkCreate(title="Live Novel", type=WorkType.NOVEL))
    work_service.publish(published_novel.id)
    work_service.create_work(WorkCreate(title="Draft Novel", type=WorkType.NOVEL))
    published_poem = work_service.create_work(WorkCreate(title="Live Poem", type=WorkType.POEM))
    work_service.publish(published_poem.id)

    response = client.get("/novels")
    assert "Live Novel" in response.text
    assert "Draft Novel" not in response.text
    assert "Live Poem" not in response.text


# --------------------------------------------------------- chapter reading


def test_chapter_navigation_links_to_siblings(client, services):
    work_service, chapter_service = services
    work = work_service.create_work(WorkCreate(title="Trilogy", type=WorkType.NOVEL))
    one = chapter_service.create_chapter(work.id, ChapterCreate(title="One", chapter_number=1))
    two = chapter_service.create_chapter(work.id, ChapterCreate(title="Two", chapter_number=2))
    three = chapter_service.create_chapter(work.id, ChapterCreate(title="Three", chapter_number=3))
    work_service.publish(work.id)
    for c in (one, two, three):
        chapter_service.publish(c.id)

    middle = client.get(f"/works/{work.slug}/chapters/{two.slug}")
    assert f"/works/{work.slug}/chapters/{one.slug}" in middle.text
    assert f"/works/{work.slug}/chapters/{three.slug}" in middle.text

    first = client.get(f"/works/{work.slug}/chapters/{one.slug}")
    assert f"/works/{work.slug}/chapters/{two.slug}" in first.text
    # No previous link on the first chapter.
    assert "Previous" not in first.text


# --------------------------------------------------------------------- seo


def test_sitemap_includes_only_published_urls(client, services):
    work_service, chapter_service = services
    published = work_service.create_work(WorkCreate(title="Visible Work", type=WorkType.NOVEL))
    chapter = chapter_service.create_chapter(published.id, ChapterCreate(title="Ch", chapter_number=1))
    work_service.publish(published.id)
    chapter_service.publish(chapter.id)
    work_service.create_work(WorkCreate(title="Invisible Work", type=WorkType.NOVEL))

    response = client.get("/sitemap.xml")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert "/novels/visible-work" in response.text
    assert f"/works/visible-work/chapters/{chapter.slug}" in response.text
    assert "invisible-work" not in response.text


def test_robots_txt_disallows_admin(client):
    response = client.get("/robots.txt")
    assert response.status_code == 200
    assert "Disallow: /admin" in response.text
    assert "Sitemap: /sitemap.xml" in response.text


def test_unmatched_url_renders_custom_404(client):
    response = client.get("/this-page-does-not-exist")
    assert response.status_code == 404
    assert "isn't in the archive" in response.text


def test_about_page_renders(client):
    response = client.get("/about")
    assert response.status_code == 200
    assert "About" in response.text


# --------------------------------------------------------------- pagination


def test_pagination_flags_next_page(client, services, monkeypatch):
    import app.routers.public as public_router

    monkeypatch.setattr(public_router, "PAGE_SIZE", 2)

    work_service, _ = services
    for title in ["First", "Second", "Third"]:
        work = work_service.create_work(WorkCreate(title=title, type=WorkType.NOVEL))
        work_service.publish(work.id)

    page_one = client.get("/novels")
    assert "Older" in page_one.text
    assert re.search(r'href="\?page=2"', page_one.text)

    page_two = client.get("/novels?page=2")
    assert "Newer" in page_two.text
