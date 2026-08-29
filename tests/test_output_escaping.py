"""
Output-escaping (XSS) verification.

Confirms Jinja2's autoescaping — which the app relies on everywhere
instead of manual escaping — actually does its job at every place
user-authored content reaches HTML: public titles/descriptions/chapter
bodies, and admin form fields that echo back submitted values (a
classic attribute-injection vector if handled wrong).
"""

from app.models.enums import WorkType
from app.schemas.chapter import ChapterCreate
from app.schemas.work import WorkCreate
from tests.conftest import csrf_from

PAYLOAD = '<script>alert("xss")</script>'
ESCAPED = "&lt;script&gt;alert(&#34;xss&#34;)&lt;/script&gt;"


def test_work_title_is_escaped_on_public_pages(client, services):
    work_service, _ = services
    work = work_service.create_work(WorkCreate(title=PAYLOAD, type=WorkType.ESSAY))
    work_service.publish(work.id)

    response = client.get(f"/essays/{work.slug}")
    assert PAYLOAD not in response.text
    assert ESCAPED in response.text


def test_work_description_is_escaped_in_listings(client, services):
    work_service, _ = services
    work = work_service.create_work(WorkCreate(title="Safe Title", type=WorkType.ESSAY, description=PAYLOAD))
    work_service.publish(work.id)

    response = client.get("/essays")
    assert PAYLOAD not in response.text
    assert ESCAPED in response.text


def test_chapter_content_is_escaped_on_reading_page(client, services):
    work_service, chapter_service = services
    work = work_service.create_work(WorkCreate(title="A Work", type=WorkType.STORY))
    chapter = chapter_service.create_chapter(work.id, ChapterCreate(title="Ch1", chapter_number=1, content=PAYLOAD))
    work_service.publish(work.id)
    chapter_service.publish(chapter.id)

    response = client.get(f"/works/{work.slug}/chapters/{chapter.slug}")
    assert PAYLOAD not in response.text
    assert ESCAPED in response.text


def test_home_page_recent_list_escapes_titles(client, services):
    work_service, _ = services
    work = work_service.create_work(WorkCreate(title=PAYLOAD, type=WorkType.POEM))
    work_service.publish(work.id)

    response = client.get("/")
    assert PAYLOAD not in response.text
    assert ESCAPED in response.text


def test_admin_form_repopulation_escapes_attribute_values(admin_client):
    """
    Admin forms echo submitted values back into value="..." attributes
    on validation failure. A title containing a double-quote must not
    be able to break out of that attribute.
    """
    page = admin_client.get("/admin/works/new")
    response = admin_client.post(
        "/admin/works/new",
        data={
            "csrf_token": csrf_from(page.text),
            "title": '"><script>alert(1)</script>',
            "work_type": "",  # left blank on purpose to force a validation error and re-render
            "description": "",
            "cover_image": "",
            "slug": "",
            "tag_names": "",
        },
    )
    assert response.status_code == 422
    assert "<script>alert(1)</script>" not in response.text
    assert 'value="&#34;&gt;&lt;script&gt;' in response.text or "&lt;script&gt;" in response.text


def test_admin_dashboard_escapes_recent_work_titles(admin_client):
    page = admin_client.get("/admin/works/new")
    admin_client.post(
        "/admin/works/new",
        data={
            "csrf_token": csrf_from(page.text),
            "title": PAYLOAD,
            "work_type": "novel",
            "description": "",
            "cover_image": "",
            "slug": "",
            "tag_names": "",
        },
    )
    response = admin_client.get("/admin")
    assert PAYLOAD not in response.text
    assert ESCAPED in response.text
