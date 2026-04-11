"""Push notification subscription routes."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import delete, insert

from app.deps import current_user, get_engine
from app.schema import push_subscriptions

router = APIRouter(prefix="/api/push", tags=["push"])


@router.post("/subscribe")
async def push_subscribe(request: Request):
    me = current_user(request)
    if not me:
        raise HTTPException(401)

    body = await request.json()

    endpoint = body.get("endpoint")
    keys = body.get("keys", {})
    p256dh = keys.get("p256dh")
    auth = keys.get("auth")

    if not endpoint or not p256dh or not auth:
        raise HTTPException(400, detail="invalid subscription")

    with get_engine(request).begin() as conn:
        # Upsert: delete existing sub for this endpoint, then insert
        conn.execute(
            delete(push_subscriptions).where(push_subscriptions.c.endpoint == endpoint)
        )
        conn.execute(
            insert(push_subscriptions).values(
                user_id=me["id"],
                endpoint=endpoint,
                p256dh_key=p256dh,
                auth_key=auth,
            )
        )

    return JSONResponse({"ok": True})


@router.post("/unsubscribe")
async def push_unsubscribe(request: Request):
    me = current_user(request)
    if not me:
        raise HTTPException(401)

    body = await request.json()
    endpoint = body.get("endpoint")
    if not endpoint:
        raise HTTPException(400)

    with get_engine(request).begin() as conn:
        conn.execute(
            delete(push_subscriptions).where(
                push_subscriptions.c.endpoint == endpoint,
                push_subscriptions.c.user_id == me["id"],
            )
        )

    return JSONResponse({"ok": True})
