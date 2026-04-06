from sqlalchemy import insert, select
from sqlalchemy.engine import Connection

from app.schema import pages, users


def list_public_pages_for_user(conn: Connection, username: str):
    q = (
        select(pages.c.slug, pages.c.title)
        .select_from(pages.join(users, pages.c.user_id == users.c.id))
        .where(users.c.username == username, pages.c.is_public.is_(True))
        .order_by(pages.c.updated_at.desc())
    )
    return conn.execute(q).mappings().all()


def get_public_page(conn: Connection, username: str, slug: str):
    q = (
        select(pages.c.title, pages.c.content_html, users.c.username, users.c.display_name)
        .select_from(pages.join(users, pages.c.user_id == users.c.id))
        .where(users.c.username == username, pages.c.slug == slug, pages.c.is_public.is_(True))
    )
    return conn.execute(q).mappings().first()


def create_page(conn: Connection, user_id: int, slug: str, title: str, content_html: str, is_public: bool = True):
    conn.execute(
        insert(pages).values(
            user_id=user_id,
            slug=slug,
            title=title,
            content_html=content_html,
            is_public=is_public,
        )
    )
