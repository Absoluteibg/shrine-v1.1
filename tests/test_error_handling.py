import asyncio
import logging

from starlette.requests import Request

from app.main import app, unhandled_exception_handler


def _make_request(path: str = "/", method: str = "GET") -> Request:
    """
    A minimal but valid ASGI request scope — bypasses the live
    middleware stack entirely (no need to fight Starlette's debug-mode
    caching, see ARCHITECTURE.md) while still exercising the real
    handler function and real template rendering against the real app.
    """
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "app": app,
        "session": {},
        "router": app.router,
    }
    return Request(scope)


def test_unhandled_exception_renders_500_page_not_a_traceback():
    request = _make_request("/some/page")
    response = asyncio.run(unhandled_exception_handler(request, RuntimeError("intentional test explosion")))

    assert response.status_code == 500
    assert b"Something went wrong" in response.body
    # The actual exception message must never reach the response body —
    # that's exactly the kind of internal detail this handler exists to hide.
    assert b"intentional test explosion" not in response.body


def test_unhandled_exception_under_api_path_returns_json_not_html():
    request = _make_request("/api/v1/works")
    response = asyncio.run(unhandled_exception_handler(request, RuntimeError("boom")))

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")


def test_unhandled_exception_is_logged_server_side(caplog):
    request = _make_request("/broken")
    with caplog.at_level(logging.ERROR, logger="shrine"):
        asyncio.run(unhandled_exception_handler(request, RuntimeError("logged boom")))

    assert any("logged boom" in record.getMessage() or record.exc_text for record in caplog.records) or any(
        "Unhandled exception" in record.getMessage() for record in caplog.records
    )


# ---------------------------------------------------- existing 404 behavior


def test_service_not_found_error_still_renders_404_page(client):
    response = client.get("/novels/does-not-exist")
    assert response.status_code == 404
    assert "isn't in the archive" in response.text


def test_admin_404_stays_plain_for_unmatched_admin_urls(admin_client):
    response = admin_client.get("/admin/this-route-does-not-exist")
    assert response.status_code == 404
    # Deliberately NOT the pretty public 404 page — see app/main.py.
    assert "isn't in the archive" not in response.text
