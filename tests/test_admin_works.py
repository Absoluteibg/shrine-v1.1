import re

from tests.conftest import csrf_from


def _create_work(admin_client, **overrides):
    page = admin_client.get("/admin/works/new")
    data = {
        "csrf_token": csrf_from(page.text),
        "title": "The Long Road",
        "work_type": "novel",
        "description": "A journey north.",
        "cover_image": "",
        "slug": "",
        "tag_names": "travel, grief",
    }
    data.update(overrides)
    return admin_client.post("/admin/works/new", data=data, follow_redirects=False)


def _work_id_from_location(response) -> str:
    match = re.search(r"/admin/works/(\d+)/edit", response.headers["location"])
    assert match, f"unexpected redirect location: {response.headers.get('location')}"
    return match.group(1)


# ------------------------------------------------------------------ create


def test_create_work_redirects_to_edit_page(admin_client):
    response = _create_work(admin_client)
    assert response.status_code == 303
    assert "/admin/works/" in response.headers["location"]
    assert response.headers["location"].endswith("/edit")


def test_created_work_starts_as_draft_and_appears_on_edit_page(admin_client):
    response = _create_work(admin_client)
    edit_page = admin_client.get(response.headers["location"])
    assert "The Long Road" in edit_page.text
    assert "status-badge--draft" in edit_page.text


def test_create_work_missing_title_shows_inline_validation_error(admin_client):
    response = _create_work(admin_client, title="")
    assert response.status_code == 422
    assert "form-error" in response.text


def test_create_work_missing_type_shows_inline_validation_error(admin_client):
    response = _create_work(admin_client, work_type="")
    assert response.status_code == 422


def test_create_work_explicit_slug_is_respected(admin_client):
    response = _create_work(admin_client, slug="custom-url")
    edit_page = admin_client.get(response.headers["location"])
    assert "/novels/custom-url" in edit_page.text


def test_create_work_colliding_slug_gets_flash_note(admin_client):
    _create_work(admin_client, slug="taken")
    response = _create_work(admin_client, title="A Different Book", slug="taken")
    edit_page = admin_client.get(response.headers["location"])
    assert "already taken" in edit_page.text


def test_create_work_requires_csrf(admin_client):
    response = admin_client.post(
        "/admin/works/new",
        data={"csrf_token": "forged", "title": "X", "work_type": "novel"},
    )
    assert response.status_code == 403


def test_create_work_requires_authentication(client):
    response = client.post(
        "/admin/works/new",
        data={"csrf_token": "whatever", "title": "X", "work_type": "novel"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


# -------------------------------------------------------------------- edit


def test_edit_work_updates_fields(admin_client):
    created = _create_work(admin_client)
    work_url = created.headers["location"]

    edit_page = admin_client.get(work_url)
    response = admin_client.post(
        work_url,
        data={
            "csrf_token": csrf_from(edit_page.text),
            "title": "The Longer Road",
            "work_type": "novel",
            "description": "An even longer journey.",
            "cover_image": "",
            "tag_names": "travel",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    updated_page = admin_client.get(work_url)
    assert "The Longer Road" in updated_page.text
    assert "An even longer journey." in updated_page.text


def test_edit_work_form_has_no_editable_slug_field(admin_client):
    created = _create_work(admin_client, slug="stable-url")
    edit_page = admin_client.get(created.headers["location"])
    assert 'name="slug"' not in edit_page.text
    assert "/novels/stable-url" in edit_page.text  # shown read-only instead


def test_edit_work_title_change_does_not_change_slug(admin_client):
    created = _create_work(admin_client, slug="stable-url")
    work_url = created.headers["location"]
    edit_page = admin_client.get(work_url)

    admin_client.post(
        work_url,
        data={
            "csrf_token": csrf_from(edit_page.text),
            "title": "Completely Different Title",
            "work_type": "novel",
            "description": "",
            "cover_image": "",
            "tag_names": "",
        },
    )

    updated_page = admin_client.get(work_url)
    assert "/novels/stable-url" in updated_page.text


def test_editing_nonexistent_work_redirects_with_flash(admin_client):
    response = admin_client.get("/admin/works/999999/edit", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/works"
    listing = admin_client.get(response.headers["location"])
    assert "no longer exists" in listing.text


# --------------------------------------------------------------- publishing


def test_publish_unpublish_archive_flow(admin_client):
    created = _create_work(admin_client)
    work_url = created.headers["location"]
    work_id = _work_id_from_location(created)
    page = admin_client.get(work_url)
    csrf = csrf_from(page.text)

    response = admin_client.post(f"/admin/works/{work_id}/publish", data={"csrf_token": csrf}, follow_redirects=False)
    assert response.status_code == 303
    assert "status-badge--published" in admin_client.get(work_url).text

    admin_client.post(f"/admin/works/{work_id}/unpublish", data={"csrf_token": csrf})
    assert "status-badge--draft" in admin_client.get(work_url).text

    admin_client.post(f"/admin/works/{work_id}/publish", data={"csrf_token": csrf})
    admin_client.post(f"/admin/works/{work_id}/archive", data={"csrf_token": csrf})
    assert "status-badge--archived" in admin_client.get(work_url).text


def test_archiving_a_never_published_draft_shows_error_flash(admin_client):
    created = _create_work(admin_client)
    work_id = _work_id_from_location(created)
    page = admin_client.get(created.headers["location"])
    csrf = csrf_from(page.text)

    response = admin_client.post(f"/admin/works/{work_id}/archive", data={"csrf_token": csrf}, follow_redirects=True)
    assert response.status_code == 200
    assert "Cannot transition" in response.text


def test_publish_requires_csrf(admin_client):
    created = _create_work(admin_client)
    work_id = _work_id_from_location(created)
    response = admin_client.post(f"/admin/works/{work_id}/publish", data={"csrf_token": "forged"})
    assert response.status_code == 403


# ------------------------------------------------------------------ delete


def test_delete_work_removes_it(admin_client):
    created = _create_work(admin_client)
    work_url = created.headers["location"]
    work_id = _work_id_from_location(created)
    page = admin_client.get(work_url)

    response = admin_client.post(
        f"/admin/works/{work_id}/delete", data={"csrf_token": csrf_from(page.text)}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/works"

    edit_attempt = admin_client.get(work_url, follow_redirects=False)
    assert edit_attempt.status_code == 303  # redirected away — work no longer exists


# ------------------------------------------------------------------- lists


def test_admin_works_list_shows_all_statuses(admin_client):
    _create_work(admin_client, title="Draft Work")
    published = _create_work(admin_client, title="Published Work")
    work_id = _work_id_from_location(published)
    page = admin_client.get(published.headers["location"])
    admin_client.post(f"/admin/works/{work_id}/publish", data={"csrf_token": csrf_from(page.text)})

    listing = admin_client.get("/admin/works")
    assert "Draft Work" in listing.text
    assert "Published Work" in listing.text


def test_admin_works_list_status_filter(admin_client):
    created = _create_work(admin_client, title="Draft Only")
    admin_client.get(created.headers["location"])  # consume the "created as draft" flash first
    listing = admin_client.get("/admin/works?status=published")
    assert "Draft Only" not in listing.text
    assert "Nothing here yet" in listing.text


def test_dashboard_counts_reflect_status(admin_client):
    _create_work(admin_client, title="One Draft")
    dashboard = admin_client.get("/admin")
    assert "1" in dashboard.text  # at least the draft tile shows a nonzero count
