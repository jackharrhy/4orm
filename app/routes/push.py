"""Push notification subscription routes."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import delete, insert, select, update

from app.deps import current_user, get_engine, is_htmx, templates, wants_json
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
    device_id = body.get("device_id", "")
    device_name = body.get("device_name", "")

    if not endpoint or not p256dh or not auth or not device_id:
        raise HTTPException(400, detail="invalid subscription")

    with get_engine(request).begin() as conn:
        # Upsert by user_id + device_id: one subscription per device per user
        existing = conn.execute(
            select(push_subscriptions.c.id).where(
                push_subscriptions.c.user_id == me["id"],
                push_subscriptions.c.device_id == device_id,
            )
        ).first()

        if existing:
            conn.execute(
                update(push_subscriptions)
                .where(push_subscriptions.c.id == existing[0])
                .values(
                    endpoint=endpoint,
                    p256dh_key=p256dh,
                    auth_key=auth,
                    device_name=device_name,
                )
            )
        else:
            conn.execute(
                insert(push_subscriptions).values(
                    user_id=me["id"],
                    device_id=device_id,
                    device_name=device_name,
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
    device_id = body.get("device_id", "")
    if not device_id:
        raise HTTPException(400)

    with get_engine(request).begin() as conn:
        conn.execute(
            delete(push_subscriptions).where(
                push_subscriptions.c.user_id == me["id"],
                push_subscriptions.c.device_id == device_id,
            )
        )

    return JSONResponse({"ok": True})


@router.get("/devices", response_class=HTMLResponse, summary="List push devices")
def list_devices(request: Request):
    """List the current user's registered push devices."""
    me = current_user(request)
    if not me:
        raise HTTPException(401)

    with get_engine(request).begin() as conn:
        devices = (
            conn.execute(
                select(
                    push_subscriptions.c.id,
                    push_subscriptions.c.device_id,
                    push_subscriptions.c.device_name,
                    push_subscriptions.c.created_at,
                ).where(push_subscriptions.c.user_id == me["id"])
            )
            .mappings()
            .all()
        )

    if wants_json(request):
        return JSONResponse(
            [
                {
                    "id": d["id"],
                    "device_id": d["device_id"],
                    "device_name": d["device_name"],
                    "created_at": str(d["created_at"]) if d["created_at"] else None,
                }
                for d in devices
            ]
        )

    return templates.TemplateResponse(
        request,
        "fragments/push_devices.html",
        {"devices": devices},
    )


@router.post("/devices/{device_db_id}/delete")
def delete_device(request: Request, device_db_id: int):
    me = current_user(request)
    if not me:
        raise HTTPException(401)

    with get_engine(request).begin() as conn:
        conn.execute(
            delete(push_subscriptions).where(
                push_subscriptions.c.id == device_db_id,
                push_subscriptions.c.user_id == me["id"],
            )
        )

    if is_htmx(request):
        return list_devices(request)
    return JSONResponse({"ok": True})
