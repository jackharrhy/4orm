from sqlalchemy import insert, select, update
from sqlalchemy.engine import Connection

from app.schema import visitor_counters


def increment_counter(conn: Connection, user_id: int):
    row = conn.execute(
        select(visitor_counters.c.user_id).where(visitor_counters.c.user_id == user_id)
    ).first()
    if row:
        conn.execute(
            update(visitor_counters)
            .where(visitor_counters.c.user_id == user_id)
            .values(total_views=visitor_counters.c.total_views + 1)
        )
    else:
        conn.execute(insert(visitor_counters).values(user_id=user_id, total_views=1))


def get_total_views(conn: Connection, user_id: int) -> int:
    row = conn.execute(
        select(visitor_counters.c.total_views).where(visitor_counters.c.user_id == user_id)
    ).first()
    return int(row[0]) if row else 0
