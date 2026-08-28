import re

from tests.conftest import csrf_from


def _create_work(admin_client, title="A Book"):
    page = admin_client.get("/admin/works/new")
    response = admin_client.post(
        "/admin/works/new",
        data={
            "csrf_token": csrf_from(page.text),
            "title": title,
            "work_type": "novel",
            "description": "",
            "cover_image": "",
            "slug": "",
            "tag_names": "",
        },
        follow_redirects=False,
    )
    work_id = re.search(r"/admin/works/(\d+)/edit", response.headers["location"]).group(1)
    return work_id, response.headers["location"]


def _create_chapter(admin_client, work_id, **overrides):
    page = admin_client.get(f"/admin/works/{work_id}/chapters/new")
    data = {
        "csrf_token": csrf_from(page.text),
        "title": "Departure",
        "chapter_number": "1",
        "content": "We left before dawn.",
        "slug": "",
    }
    data.update(overrides)
    return admin_client.post(f"/admin/works/{work_id}/chapters/new", data=data, follow_redirects=False)


def _chapter_id_from_location(response) -> str:
    match = re.search(r"/admin/chapters/(\d+)/edit", response.headers["location"])
    assert match, f"unexpected redirect location: {response.headers.get('location')}"
    return match.group(1)


# ------------------------------------------------------------------ create


def test_create_chapter_redirects_to_its_edit_page(admin_client):
    work_id, _ = _create_work(admin_client)
    response = _create_chapter(admin_client, work_id)
    assert response.status_code == 303
    assert "/admin/chapters/" in response.headers["location"]


def test_created_chapter_starts_as_draft(admin_client):
    work_id, _ = _create_work(admin_client)
    response = _create_chapter(admin_client, work_id)
    edit_page = admin_client.get(response.headers["location"])
    assert "Departure" in edit_page.text
    assert "status-badge--draft" in edit_page.text


def test_new_chapter_form_shows_parent_work_breadcrumb(admin_client):
    work_id, _ = _create_work(admin_client, title="The Long Road")
    page = admin_client.get(f"/admin/works/{work_id}/chapters/new")
    assert "The Long Road" in page.text


def test_create_chapter_missing_title_shows_validation_error(admin_client):
    work_id, _ = _create_work(admin_client)
    response = _create_chapter(admin_client, work_id, title="")
    assert response.status_code == 422
    assert "form-error" in response.text


def test_create_chapter_duplicate_number_shows_error(admin_client):
    work_id, _ = _create_work(admin_client)
    _create_chapter(admin_client, work_id, chapter_number="1")
    response = _create_chapter(admin_client, work_id, title="Another One", chapter_number="1")
    assert response.status_code == 422
    assert "already exists" in response.text


def test_create_chapter_for_missing_work_redirects_with_flash(admin_client):
    page = admin_client.get("/admin/works/new")  # just to get a valid csrf token
    response = admin_client.post(
        "/admin/works/999999/chapters/new",
        data={"csrf_token": csrf_from(page.text), "title": "X", "chapter_number": "1", "content": "", "slug": ""},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/works"


def test_create_chapter_requires_csrf(admin_client):
    work_id, _ = _create_work(admin_client)
    response = admin_client.post(
        f"/admin/works/{work_id}/chapters/new",
        data={"csrf_token": "forged", "title": "X", "chapter_number": "1", "content": ""},
    )
    assert response.status_code == 403


# -------------------------------------------------------------------- edit


def test_edit_chapter_updates_content(admin_client):
    work_id, _ = _create_work(admin_client)
    created = _create_chapter(admin_client, work_id)
    chapter_url = created.headers["location"]

    edit_page = admin_client.get(chapter_url)
    admin_client.post(
        chapter_url,
        data={
            "csrf_token": csrf_from(edit_page.text),
            "title": "Departure",
            "chapter_number": "1",
            "content": "We left before the sun rose.",
        },
    )

    updated = admin_client.get(chapter_url)
    assert "We left before the sun rose." in updated.text


def test_edit_chapter_to_a_taken_number_shows_error(admin_client):
    work_id, _ = _create_work(admin_client)
    _create_chapter(admin_client, work_id, chapter_number="1")
    second = _create_chapter(admin_client, work_id, title="Second", chapter_number="2")
    chapter_url = second.headers["location"]

    edit_page = admin_client.get(chapter_url)
    response = admin_client.post(
        chapter_url,
        data={
            "csrf_token": csrf_from(edit_page.text),
            "title": "Second",
            "chapter_number": "1",
            "content": "",
        },
    )
    assert response.status_code == 422
    assert "already exists" in response.text


def test_editing_nonexistent_chapter_redirects_with_flash(admin_client):
    response = admin_client.get("/admin/chapters/999999/edit", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/works"


# --------------------------------------------------------------- publishing


def test_chapter_publish_unpublish_archive_flow(admin_client):
    work_id, _ = _create_work(admin_client)
    created = _create_chapter(admin_client, work_id)
    chapter_id = _chapter_id_from_location(created)
    chapter_url = created.headers["location"]
    csrf = csrf_from(admin_client.get(chapter_url).text)

    admin_client.post(f"/admin/chapters/{chapter_id}/publish", data={"csrf_token": csrf})
    assert "status-badge--published" in admin_client.get(chapter_url).text

    admin_client.post(f"/admin/chapters/{chapter_id}/unpublish", data={"csrf_token": csrf})
    assert "status-badge--draft" in admin_client.get(chapter_url).text

    admin_client.post(f"/admin/chapters/{chapter_id}/publish", data={"csrf_token": csrf})
    admin_client.post(f"/admin/chapters/{chapter_id}/archive", data={"csrf_token": csrf})
    assert "status-badge--archived" in admin_client.get(chapter_url).text


# ------------------------------------------------------------------ delete


def test_delete_chapter_redirects_to_parent_work(admin_client):
    work_id, work_url = _create_work(admin_client)
    created = _create_chapter(admin_client, work_id)
    chapter_id = _chapter_id_from_location(created)
    chapter_url = created.headers["location"]
    csrf = csrf_from(admin_client.get(chapter_url).text)

    response = admin_client.post(
        f"/admin/chapters/{chapter_id}/delete", data={"csrf_token": csrf}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == work_url

    work_page = admin_client.get(work_url)
    assert "No chapters yet" in work_page.text


def test_deleted_work_chapters_disappear_from_admin_too(admin_client):
    work_id, work_url = _create_work(admin_client)
    _create_chapter(admin_client, work_id)
    csrf = csrf_from(admin_client.get(work_url).text)

    admin_client.post(f"/admin/works/{work_id}/delete", data={"csrf_token": csrf})
    listing = admin_client.get("/admin/works")
    assert "A Book" not in listing.text
