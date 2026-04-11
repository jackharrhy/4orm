"""Media library query functions."""

from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Connection

from app.schema import media


def create_media(
    conn: Connection,
    *,
    user_id: int,
    storage_path: str,
    mime_type: str,
    size_bytes: int,
    width: int | None = None,
    height: int | None = None,
    alt_text: str = "",
):
    result = conn.execute(
        insert(media).values(
            user_id=user_id,
            storage_path=storage_path,
            mime_type=mime_type,
            size_bytes=size_bytes,
            width=width,
            height=height,
            alt_text=alt_text,
        )
    )
    media_id = result.inserted_primary_key[0]
    return conn.execute(select(media).where(media.c.id == media_id)).mappings().first()


def list_media_for_user(conn: Connection, user_id: int):
    q = (
        select(media)
        .where(media.c.user_id == user_id)
        .order_by(media.c.created_at.desc())
    )
    return conn.execute(q).mappings().all()


def get_media_for_user(conn: Connection, user_id: int, media_id: int):
    q = select(media).where(media.c.id == media_id, media.c.user_id == user_id)
    return conn.execute(q).mappings().first()


def update_media_alt_text(conn: Connection, user_id: int, media_id: int, alt_text: str):
    conn.execute(
        update(media)
        .where(media.c.id == media_id, media.c.user_id == user_id)
        .values(alt_text=alt_text)
    )


def update_media_storage_path(
    conn: Connection, user_id: int, media_id: int, storage_path: str
):
    conn.execute(
        update(media)
        .where(media.c.id == media_id, media.c.user_id == user_id)
        .values(storage_path=storage_path)
    )


def delete_media_for_user(conn: Connection, user_id: int, media_id: int):
    conn.execute(
        delete(media).where(media.c.id == media_id, media.c.user_id == user_id)
    )
