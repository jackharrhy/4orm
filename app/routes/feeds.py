"""RSS feed routes."""

from html import escape

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app.deps import _format_rfc2822, get_engine
from app.queries.pages import list_public_pages_for_rss, list_public_pages_for_user_rss
from app.queries.users import get_user_by_username

router = APIRouter()


def build_rss_feed(
    *, title: str, link: str, description: str, items: list[dict]
) -> str:
    entries = []
    for item in items:
        entries.append(
            "<item>"
            f"<title>{escape(item['title'])}</title>"
            f"<link>{escape(item['link'])}</link>"
            f"<guid>{escape(item['guid'])}</guid>"
            f"<pubDate>{_format_rfc2822(item.get('updated_at'))}</pubDate>"
            "</item>"
        )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0"><channel>'
        f"<title>{escape(title)}</title>"
        f"<link>{escape(link)}</link>"
        f"<description>{escape(description)}</description>"
        f"{''.join(entries)}"
        "</channel></rss>"
    )


@router.get("/feed.xml")
def global_feed(request: Request):
    with get_engine(request).begin() as conn:
        pages = list_public_pages_for_rss(conn, limit=100)

    site_url = str(request.base_url).rstrip("/")
    items = []
    for p in pages:
        link = f"{site_url}/u/{p['username']}/page/{p['slug']}"
        items.append(
            {
                "title": f"{p['display_name']}: {p['title']}",
                "link": link,
                "guid": f"{link}#{p['updated_at']}",
                "updated_at": p["updated_at"],
            }
        )

    xml = build_rss_feed(
        title="4orm updates",
        link=f"{site_url}/",
        description="Recent public page updates",
        items=items,
    )
    return Response(content=xml, media_type="application/rss+xml; charset=utf-8")


@router.get("/u/{username}/feed.xml")
def user_feed(request: Request, username: str):
    with get_engine(request).begin() as conn:
        profile = get_user_by_username(conn, username)
        if not profile:
            raise HTTPException(404)
        pages = list_public_pages_for_user_rss(conn, username, limit=100)

    site_url = str(request.base_url).rstrip("/")
    items = []
    for p in pages:
        link = f"{site_url}/u/{p['username']}/page/{p['slug']}"
        items.append(
            {
                "title": p["title"],
                "link": link,
                "guid": f"{link}#{p['updated_at']}",
                "updated_at": p["updated_at"],
            }
        )

    xml = build_rss_feed(
        title=f"4orm updates from {profile['display_name']}",
        link=f"{site_url}/u/{username}",
        description="Recent public page updates",
        items=items,
    )
    return Response(content=xml, media_type="application/rss+xml; charset=utf-8")
