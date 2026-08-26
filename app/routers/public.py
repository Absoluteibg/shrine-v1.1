"""
Public-facing routes: the read-only literary site any visitor can reach.

No authentication. Every read here goes through WorkService/ChapterService
using their PUBLISHED-only lookups (get_published_by_slug,
get_published_chapter_with_work, list_published, ...) — draft and
archived content is never reachable from this router, because that rule
lives in the service layer, not here. See ARCHITECTURE.md.
"""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy.orm import Session

from app.core.templating import templates
from app.db.database import get_db
from app.models.enums import WorkType
from app.services.chapter_service import ChapterService
from app.services.work_service import WorkService

router = APIRouter(tags=["public"])

PAGE_SIZE = 20

# The one place that maps a WorkType to its URL segment and display
# label — every route and template below reads from this instead of
# repeating the mapping.
_SEGMENT_BY_TYPE: dict[WorkType, str] = {
    WorkType.NOVEL: "novels",
    WorkType.STORY: "stories",
    WorkType.POEM: "poems",
    WorkType.ESSAY: "essays",
}
_LABEL_BY_TYPE: dict[WorkType, str] = {
    WorkType.NOVEL: "Novels",
    WorkType.STORY: "Stories",
    WorkType.POEM: "Poems",
    WorkType.ESSAY: "Essays",
}


def segment_for(work_type: WorkType) -> str:
    return _SEGMENT_BY_TYPE[work_type]


# ------------------------------------------------------------------- home


@router.get("/")
def home(request: Request, db: Session = Depends(get_db)):
    recent = WorkService(db).list_published(limit=6)
    return templates.TemplateResponse(
        request,
        "home.html",
        {"recent_works": recent, "segment_for": segment_for},
    )


@router.get("/about")
def about(request: Request):
    return templates.TemplateResponse(request, "about.html", {"nav_active": "about"})


# --------------------------------------------------------------- listings


def _render_listing(request: Request, db: Session, work_type: WorkType, page: int):
    segment = _SEGMENT_BY_TYPE[work_type]
    offset = (page - 1) * PAGE_SIZE
    # Fetch one extra row to know whether an "older" page exists, without
    # a separate COUNT(*) query.
    works = WorkService(db).list_published(type=work_type, limit=PAGE_SIZE + 1, offset=offset)
    has_more = len(works) > PAGE_SIZE
    works = works[:PAGE_SIZE]
    return templates.TemplateResponse(
        request,
        "works.html",
        {
            "works": works,
            "segment": segment,
            "label": _LABEL_BY_TYPE[work_type],
            "nav_active": segment,
            "page": page,
            "has_prev": page > 1,
            "has_more": has_more,
        },
    )


@router.get("/novels")
def list_novels(request: Request, db: Session = Depends(get_db), page: int = Query(1, ge=1)):
    return _render_listing(request, db, WorkType.NOVEL, page)


@router.get("/stories")
def list_stories(request: Request, db: Session = Depends(get_db), page: int = Query(1, ge=1)):
    return _render_listing(request, db, WorkType.STORY, page)


@router.get("/poems")
def list_poems(request: Request, db: Session = Depends(get_db), page: int = Query(1, ge=1)):
    return _render_listing(request, db, WorkType.POEM, page)


@router.get("/essays")
def list_essays(request: Request, db: Session = Depends(get_db), page: int = Query(1, ge=1)):
    return _render_listing(request, db, WorkType.ESSAY, page)


# ----------------------------------------------------------- work detail


def _render_detail(request: Request, db: Session, work_type: WorkType, slug: str):
    work_service = WorkService(db)
    work = work_service.get_published_by_slug(slug, type=work_type)
    chapters = ChapterService(db).list_published_for_work(work.id)
    segment = _SEGMENT_BY_TYPE[work_type]
    return templates.TemplateResponse(
        request,
        "work.html",
        {"work": work, "chapters": chapters, "segment": segment, "nav_active": segment},
    )


@router.get("/novels/{slug}")
def novel_detail(slug: str, request: Request, db: Session = Depends(get_db)):
    return _render_detail(request, db, WorkType.NOVEL, slug)


@router.get("/stories/{slug}")
def story_detail(slug: str, request: Request, db: Session = Depends(get_db)):
    return _render_detail(request, db, WorkType.STORY, slug)


@router.get("/poems/{slug}")
def poem_detail(slug: str, request: Request, db: Session = Depends(get_db)):
    return _render_detail(request, db, WorkType.POEM, slug)


@router.get("/essays/{slug}")
def essay_detail(slug: str, request: Request, db: Session = Depends(get_db)):
    return _render_detail(request, db, WorkType.ESSAY, slug)


# --------------------------------------------------------------- chapter


@router.get("/works/{work_slug}/chapters/{chapter_slug}")
def read_chapter(work_slug: str, chapter_slug: str, request: Request, db: Session = Depends(get_db)):
    chapter_service = ChapterService(db)
    work, chapter = chapter_service.get_published_chapter_with_work(work_slug, chapter_slug)
    prev_chapter, next_chapter = chapter_service.get_navigation(chapter)
    return templates.TemplateResponse(
        request,
        "chapter.html",
        {
            "work": work,
            "chapter": chapter,
            "prev_chapter": prev_chapter,
            "next_chapter": next_chapter,
            "segment": _SEGMENT_BY_TYPE[work.type],
        },
    )


# ------------------------------------------------------------------- seo


@router.get("/robots.txt", include_in_schema=False)
def robots_txt() -> PlainTextResponse:
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /admin",
        "Disallow: /api/",
        "Sitemap: /sitemap.xml",
    ]
    return PlainTextResponse("\n".join(lines))


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap_xml(request: Request, db: Session = Depends(get_db)) -> Response:
    base = f"{request.url.scheme}://{request.url.netloc}"
    work_service = WorkService(db)
    chapter_service = ChapterService(db)

    urls: list[str] = [base + "/", base + "/about"]
    urls += [f"{base}/{segment}" for segment in _SEGMENT_BY_TYPE.values()]

    # A personal archive's total URL count is small enough that listing
    # every published work/chapter here in one pass is fine; revisit
    # with a paginated/indexed sitemap only if that stops being true.
    for work_type, segment in _SEGMENT_BY_TYPE.items():
        for work in work_service.list_published(type=work_type, limit=200):
            urls.append(f"{base}/{segment}/{work.slug}")
            for chapter in chapter_service.list_published_for_work(work.id):
                urls.append(f"{base}/works/{work.slug}/chapters/{chapter.slug}")

    body = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    body += [f"<url><loc>{url}</loc></url>" for url in urls]
    body.append("</urlset>")

    return Response("\n".join(body), media_type="application/xml")
