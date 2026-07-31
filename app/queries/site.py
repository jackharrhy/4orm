from sqlalchemy import select

from app.schema import site_settings


def get_site_banner(conn):
    return (
        conn.execute(select(site_settings).where(site_settings.c.id == 1))
        .mappings()
        .first()
    )
