"""Web Push notification sending."""

import json
import logging

from pywebpush import WebPushException, webpush
from sqlalchemy import delete, select
from sqlalchemy.engine import Connection

from app.deps import VAPID_EMAIL, VAPID_PRIVATE_KEY
from app.schema import push_subscriptions, users

logger = logging.getLogger("4orm.push")


def send_notification(
    conn: Connection, user_id: int, title: str, body: str, url: str = "/"
):
    """Send a push notification to all of a user's subscriptions."""
    # Check if user has notifications enabled
    enabled = conn.execute(
        select(users.c.notifications_enabled).where(users.c.id == user_id)
    ).scalar()
    if not enabled:
        return

    if not VAPID_PRIVATE_KEY:
        logger.warning("VAPID_PRIVATE_KEY not set, skipping push")
        return

    subs = (
        conn.execute(
            select(push_subscriptions).where(push_subscriptions.c.user_id == user_id)
        )
        .mappings()
        .all()
    )

    payload = json.dumps({"title": title, "body": body, "url": url})

    for sub in subs:
        subscription_info = {
            "endpoint": sub["endpoint"],
            "keys": {
                "p256dh": sub["p256dh_key"],
                "auth": sub["auth_key"],
            },
        }
        try:
            webpush(
                subscription_info=subscription_info,
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": VAPID_EMAIL},
            )
        except WebPushException as e:
            if e.response and e.response.status_code == 410:
                # Subscription expired, remove it
                conn.execute(
                    delete(push_subscriptions).where(
                        push_subscriptions.c.id == sub["id"]
                    )
                )
                logger.info("Removed expired subscription %s", sub["endpoint"][:50])
            else:
                logger.error("Push failed for %s: %s", sub["endpoint"][:50], e)
        except Exception as e:
            logger.error("Push failed for %s: %s", sub["endpoint"][:50], e)
