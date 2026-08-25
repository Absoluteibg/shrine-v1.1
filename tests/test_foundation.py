"""
Phase 1 smoke tests.

These don't test domain logic (there isn't any yet) — they prove the
foundation itself works: the app boots, a route renders through Jinja2,
and static assets are served. This is the bar Phase 2 builds on top of.
"""


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app"] == "SHRINE"


def test_home_page_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "SHRINE" in response.text


def test_static_css_is_served(client):
    response = client.get("/static/css/style.css")
    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]
