from urllib.error import HTTPError

import pytest
from sqlalchemy import insert, select, update

from app import enrollment
from app import enrollment_completion as completion
from app.queries.users import create_invite
from app.schema import (
    auth_enrollments,
    enrollment_completions,
    external_identities,
    invites,
    users,
)


def new_profile(conn, seed_user):
    code = create_invite(conn, seed_user["id"])
    row = enrollment.reserve(conn, code)
    enrollment.claim(conn, row["id"], "new-subject", "newmember", "New Member")
    user = enrollment.finish(conn, row["id"], completion.ISSUER, "new-subject")
    return row["id"], user


def test_only_committed_new_profile_qualifies_after_expiry(test_engine, seed_user):
    with test_engine.begin() as conn:
        request_id, user = new_profile(conn, seed_user)
        conn.execute(update(auth_enrollments).values(expires_at=1))
        conn.execute(update(invites).values(disabled=True))
        assert completion.proof(conn, request_id) == {
            "requestId": request_id,
            "subject": "new-subject",
            "issuer": completion.ISSUER,
            "userId": user["id"],
            "completed": True,
            "createdProfile": True,
            "enabled": True,
        }
        with pytest.raises(ValueError):
            completion.reserve(conn, request_id, "maps", "wrong-subject", "attempt")
        with pytest.raises(ValueError):
            completion.reserve(conn, request_id, "artbin", "new-subject", "attempt")
        conn.execute(
            update(users).where(users.c.id == user["id"]).values(is_disabled=True)
        )
        with pytest.raises(ValueError):
            completion.reserve(conn, request_id, "maps", "new-subject", "attempt")
    with test_engine.begin() as conn:
        code = create_invite(conn, seed_user["id"])
        row = enrollment.reserve(conn, code)
        with pytest.raises(ValueError):
            completion.proof(conn, row["id"])


def test_existing_member_never_creates_event(test_engine, seed_user):
    with test_engine.begin() as conn:
        conn.execute(
            insert(external_identities).values(
                issuer=completion.ISSUER,
                subject="existing",
                user_id=seed_user["id"],
            )
        )
        code = create_invite(conn, seed_user["id"])
        row = enrollment.reserve(conn, code)
        enrollment.claim(conn, row["id"], "existing", "ignored", "Ignored")
        enrollment.finish(conn, row["id"], completion.ISSUER, "existing")
        assert completion.proof(conn, row["id"])["createdProfile"] is False
        assert conn.execute(select(enrollment_completions)).first() is None
        with pytest.raises(ValueError):
            completion.reserve(conn, row["id"], "maps", "existing", "retry")


def test_reservation_original_owner_and_terminal_receipt_survive_replay(
    test_engine, seed_user
):
    with test_engine.begin() as conn:
        request_id, _ = new_profile(conn, seed_user)
    for attempt in ["original", "concurrent", "retry"]:
        with test_engine.begin() as conn:
            result = completion.reserve(
                conn, request_id, "maps", "new-subject", attempt
            )
            assert result["attemptId"] == "original"
            assert result["state"] == "reserved"
    with test_engine.begin() as conn:
        with pytest.raises(ValueError):
            completion.finish(
                conn, request_id, "maps", "new-subject", "other", "123", "created"
            )
        for _ in range(2):
            result = completion.finish(
                conn, request_id, "maps", "new-subject", "original", "123", "created"
            )
            assert result["state"] == "done"
        with pytest.raises(ValueError):
            completion.finish(
                conn, request_id, "maps", "new-subject", "original", "456", "created"
            )
        assert (
            completion.reserve(conn, request_id, "maps", "new-subject", "later")[
                "state"
            ]
            == "done"
        )
        assert (
            completion.reserve(conn, request_id, "burger", "new-subject", "separate")[
                "state"
            ]
            == "reserved"
        )


def test_delivery_retries_outage_but_stops_on_unknown_outcome(
    test_engine, seed_user, monkeypatch
):
    with test_engine.begin() as conn:
        request_id, _ = new_profile(conn, seed_user)
    monkeypatch.setattr(enrollment, "integration_key", lambda: "test-key")
    calls = []

    def broker(url, *, headers, json_body):
        calls.append(json_body)
        raise HTTPError(url, 502, "unavailable", {}, None)

    monkeypatch.setattr(completion.oidc, "provider_json", broker)
    assert completion.deliver(test_engine, request_id) == 502
    assert completion.deliver(test_engine, request_id) == 502

    def ambiguous(url, **kwargs):
        raise HTTPError(url, 409, "unknown outcome", {}, None)

    monkeypatch.setattr(completion.oidc, "provider_json", ambiguous)
    assert completion.deliver(test_engine, request_id) == 409
    assert completion.deliver(test_engine, request_id) is None
    with test_engine.begin() as conn:
        assert completion.proof(conn, request_id)["completed"]
        assert (
            conn.execute(select(enrollment_completions.c.delivered_at)).scalar_one()
            is None
        )
        conn.execute(update(enrollment_completions).values(last_status=502))
    monkeypatch.setattr(
        completion.oidc,
        "provider_json",
        lambda *args, **kwargs: {"requestId": request_id, "completed": True},
    )
    assert completion.deliver(test_engine, request_id) == 200
    assert completion.deliver(test_engine, request_id) is None
    assert calls == [{"requestId": request_id, "subject": "new-subject"}] * 2


def test_completion_endpoints_auth_and_strict_contract(
    client, test_engine, seed_user, tmp_path, monkeypatch
):
    import json

    key = tmp_path / "key.json"
    key.write_text(json.dumps({"token": "test-secret" * 8}))
    monkeypatch.setenv("CENTRAL_AUTH_ENROLLMENT_KEY_FILE", str(key))
    headers = {"Authorization": "Bearer " + "test-secret" * 8}
    with test_engine.begin() as conn:
        request_id, _ = new_profile(conn, seed_user)
    path = f"/internal/auth/enrollments/{request_id}/completion"
    assert client.get(path).status_code == 401
    assert client.get(path, headers=headers).json()["createdProfile"]
    body = {"subject": "new-subject", "attemptId": "attempt"}
    assert (
        client.post(
            path + "/maps/reserve", headers=headers, json=body | {"role": "admin"}
        ).status_code
        == 422
    )
    assert (
        client.post(path + "/maps/reserve", headers=headers, json=body).json()["state"]
        == "reserved"
    )
    assert (
        client.post(
            path + "/maps/finish",
            headers=headers,
            json=body | {"grantId": "123", "outcome": "created"},
        ).json()["state"]
        == "done"
    )


def test_profile_transaction_rollback_leaves_no_completion(test_engine, seed_user):
    with pytest.raises(RuntimeError), test_engine.begin() as conn:
        new_profile(conn, seed_user)
        raise RuntimeError("callback transaction interrupted")
    with test_engine.connect() as conn:
        assert conn.execute(select(enrollment_completions)).first() is None
        assert (
            conn.execute(
                select(users.c.id).where(users.c.username == "newmember")
            ).first()
            is None
        )


def test_concurrent_reservations_have_one_durable_owner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from sqlalchemy import create_engine

    from app.schema import metadata

    engine = create_engine("sqlite:///" + str(tmp_path / "concurrent.db"))
    metadata.create_all(engine)
    with engine.begin() as conn:
        uid = conn.execute(
            insert(users).values(
                username="inviter", display_name="Inviter", password_hash="unused"
            )
        ).inserted_primary_key[0]
        request_id, _ = new_profile(conn, {"id": uid})

    def reserve(attempt):
        with engine.begin() as conn:
            return completion.reserve(conn, request_id, "maps", "new-subject", attempt)[
                "attemptId"
            ]

    with ThreadPoolExecutor(max_workers=2) as pool:
        owners = list(pool.map(reserve, ["one", "two"]))
    assert owners[0] == owners[1]
    engine.dispose()
