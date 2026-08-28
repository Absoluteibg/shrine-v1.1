import pytest

from app.core.config import get_settings
from tests.conftest import csrf_from


@pytest.mark.parametrize("path", ["/admin", "/admin/works", "/admin/works/new"])
def test_unauthenticated_admin_routes_redirect_to_login(client, path):
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


def test_login_page_renders_with_csrf_token(client):
    response = client.get("/admin/login")
    assert response.status_code == 200
    assert csrf_from(response.text)


def test_wrong_password_is_rejected(client):
    page = client.get("/admin/login")
    settings = get_settings()
    response = client.post(
        "/admin/login",
        data={"username": settings.ADMIN_USERNAME, "password": "wrong", "csrf_token": csrf_from(page.text)},
    )
    assert response.status_code == 401
    assert "Incorrect username or password" in response.text


def test_wrong_username_is_rejected(client):
    page = client.get("/admin/login")
    response = client.post(
        "/admin/login",
        data={"username": "not-the-admin", "password": "changeme123", "csrf_token": csrf_from(page.text)},
    )
    assert response.status_code == 401


def test_correct_login_redirects_to_dashboard(client):
    page = client.get("/admin/login")
    settings = get_settings()
    response = client.post(
        "/admin/login",
        data={"username": settings.ADMIN_USERNAME, "password": "changeme123", "csrf_token": csrf_from(page.text)},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/admin"


def test_login_with_bad_csrf_token_is_rejected(client):
    client.get("/admin/login")  # establishes a session + real csrf token
    settings = get_settings()
    response = client.post(
        "/admin/login",
        data={"username": settings.ADMIN_USERNAME, "password": "changeme123", "csrf_token": "forged-token"},
    )
    assert response.status_code == 403


def test_already_logged_in_visiting_login_redirects_to_dashboard(admin_client):
    response = admin_client.get("/admin/login", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin"


def test_repeated_failed_logins_lock_out(client):
    settings = get_settings()
    page = client.get("/admin/login")
    csrf = csrf_from(page.text)

    for _ in range(5):
        response = client.post(
            "/admin/login",
            data={"username": settings.ADMIN_USERNAME, "password": "wrong", "csrf_token": csrf},
        )
        assert response.status_code == 401

    # 6th attempt, even with the CORRECT password, is locked out.
    response = client.post(
        "/admin/login",
        data={"username": settings.ADMIN_USERNAME, "password": "changeme123", "csrf_token": csrf},
    )
    assert response.status_code == 429
    assert "Too many failed attempts" in response.text


def test_admin_client_fixture_reaches_dashboard(admin_client):
    response = admin_client.get("/admin")
    assert response.status_code == 200
    assert "Dashboard" in response.text


def test_logout_clears_session(admin_client):
    page = admin_client.get("/admin")
    response = admin_client.post("/admin/logout", data={"csrf_token": csrf_from(page.text)}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"

    # session is gone — dashboard bounces back to login again
    response = admin_client.get("/admin", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


def test_logout_requires_csrf(admin_client):
    response = admin_client.post("/admin/logout", data={"csrf_token": "forged"})
    assert response.status_code == 403
    # still logged in — the forged request didn't clear the session
    assert admin_client.get("/admin").status_code == 200
