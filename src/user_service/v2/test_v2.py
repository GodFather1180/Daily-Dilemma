import io
import os
import pytest
import itertools
import bcrypt
from fastapi.testclient import TestClient
from user_service.v1.api import app
from datetime import datetime, timedelta
from user_service.v2 import auth_v2 as auth_v2_module

client = TestClient(app)


@pytest.fixture
def user_payload():
    return {"name": "tarun", "email": "tarun@example.com", "password": "secret123"}


@pytest.fixture
def second_user_payload():
    return {"name": "ravi", "email": "ravi@example.com", "password": "pass456"}


########################################
# USERS
########################################


def test_create_user_returns_201(user_payload):
    res = client.post("/v2/users/", json=user_payload)
    assert res.status_code == 201
    data = res.json()
    assert "id" in data
    assert data["name"] == user_payload["name"]
    assert "password" not in data


def test_list_users_returns_all(user_payload):
    client.post("/v2/users/", json=user_payload)
    res = client.get("/v2/users/")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert any(u["name"] == user_payload["name"] for u in data)


def test_get_user_by_id_and_name(user_payload):
    create = client.post("/v2/users/", json=user_payload)
    user_id = create.json()["id"]

    by_id = client.get(f"/v2/users/{user_id}")
    assert by_id.status_code == 200
    assert by_id.json()["id"] == user_id

    by_name = client.get(f"/v2/users/{user_payload['name']}")
    assert by_name.status_code == 200
    assert by_name.json()["name"] == user_payload["name"]


def test_update_user_info_excludes_password(user_payload):
    create = client.post("/v2/users/", json=user_payload)
    user_id = create.json()["id"]

    update = {"email": "updated@example.com"}
    res = client.patch(f"/v2/users/{user_id}", json=update)
    assert res.status_code == 200
    assert res.json()["email"] == "updated@example.com"
    assert "password" not in res.json()


def test_change_password_flow(user_payload):
    create = client.post("/v2/users/", json=user_payload)
    user_id = create.json()["id"]

    # Missing old password
    bad = client.patch(f"/v2/users/{user_id}", json={"new_password": "newpass"})
    assert bad.status_code in (400, 403)

    # Correct flow
    good = client.patch(
        f"/v2/users/{user_id}",
        json={"password": user_payload["password"], "new_password": "newpass"},
    )
    assert good.status_code == 200


def test_delete_user_removes_user(user_payload):
    create = client.post("/v2/users/", json=user_payload)
    user_id = create.json()["id"]

    res = client.delete(f"/v2/users/{user_id}")
    assert res.status_code == 204

    again = client.get(f"/v2/users/{user_id}")
    assert again.status_code == 404


########################################
# PROFILE PICTURES
########################################


def test_upload_and_get_avatar(user_payload):
    create = client.post("/v2/users/", json=user_payload)
    user_id = create.json()["id"]

    img_data = io.BytesIO(b"fakeimagebytes")
    files = {"file": ("avatar.png", img_data, "image/png")}
    upload = client.post(f"/v2/users/{user_id}/avatar", files=files)
    assert upload.status_code == 201

    get_res = client.get(f"/v2/users/{user_id}/avatar")
    assert get_res.status_code == 200
    assert get_res.headers["content-type"].startswith("image/")


def test_update_and_delete_avatar(user_payload):
    create = client.post("/v2/users/", json=user_payload)
    user_id = create.json()["id"]

    files = {"file": ("avatar.png", io.BytesIO(b"img"), "image/png")}
    client.post(f"/v2/users/{user_id}/avatar", files=files)

    new_file = {"file": ("new.png", io.BytesIO(b"newimg"), "image/png")}
    update = client.put(f"/v2/users/{user_id}/avatar", files=new_file)
    assert update.status_code == 200

    delete = client.delete(f"/v2/users/{user_id}/avatar")
    assert delete.status_code == 204


########################################
# FRIEND REQUESTS
########################################


def test_send_and_view_friend_request(user_payload, second_user_payload):
    u1 = client.post("/v2/users/", json=user_payload).json()
    u2 = client.post("/v2/users/", json=second_user_payload).json()

    req = {"from": u1["id"], "to": u2["id"]}
    send = client.post(f"/v2/users/{u1['id']}/friend-requests/", json=req)
    assert send.status_code == 201

    incoming = client.get(f"/v2/users/{u2['id']}/friend-requests/?q=incoming")
    assert incoming.status_code == 200
    assert len(incoming.json()) == 1

    outgoing = client.get(f"/v2/users/{u1['id']}/friend-requests/?q=outgoing")
    assert outgoing.status_code == 200
    assert len(outgoing.json()) == 1


def test_accept_and_cancel_friend_request(user_payload, second_user_payload):
    u1 = client.post("/v2/users/", json=user_payload).json()
    u2 = client.post("/v2/users/", json=second_user_payload).json()

    client.post(
        f"/v2/users/{u1['id']}/friend-requests/",
        json={"from": u1["id"], "to": u2["id"]},
    )

    # Accept request
    accept = client.patch(
        f"/v2/users/{u2['id']}/friend-requests/{u1['id']}", json={"status": "accepted"}
    )
    assert accept.status_code == 200

    # Cancel (should now delete friendship)
    cancel = client.delete(f"/v2/users/{u1['id']}/friend-requests/{u2['id']}")
    assert cancel.status_code in (200, 204)


########################################
# FRIENDS
########################################


def test_list_and_delete_friend(user_payload, second_user_payload):
    u1 = client.post("/v2/users/", json=user_payload).json()
    u2 = client.post("/v2/users/", json=second_user_payload).json()

    # Create a friend relationship (pretend accepted)
    client.post(
        f"/v2/users/{u1['id']}/friend-requests/",
        json={"from": u1["id"], "to": u2["id"]},
    )
    client.patch(
        f"/v2/users/{u2['id']}/friend-requests/{u1['id']}", json={"status": "accepted"}
    )

    friends = client.get(f"/v2/users/{u1['id']}/friends/")
    assert friends.status_code == 200
    assert any(f["id"] == u2["id"] for f in friends.json())

    delete_by_id = client.delete(f"/v2/users/{u1['id']}/friends/{u2['id']}")
    assert delete_by_id.status_code in (200, 204)


def test_get_and_delete_friend_by_name(user_payload, second_user_payload):
    # Create two users
    u1 = client.post("/v2/users/", json=user_payload).json()
    u2 = client.post("/v2/users/", json=second_user_payload).json()

    # u1 sends friend request to u2, u2 accepts
    client.post(
        f"/v2/users/{u1['id']}/friend-requests/",
        json={"from": u1["id"], "to": u2["id"]},
    )
    client.patch(
        f"/v2/users/{u2['id']}/friend-requests/{u1['id']}", json={"status": "accepted"}
    )

    # Verify friendship appears in u1’s list
    friends = client.get(f"/v2/users/{u1['id']}/friends/")
    assert friends.status_code == 200
    assert any(f["name"] == u2["name"] for f in friends.json())

    # Get friend by name
    get_by_name = client.get(f"/v2/users/{u1['id']}/friends/{u2['name']}")
    assert get_by_name.status_code == 200
    assert get_by_name.json()["name"] == u2["name"]
    assert "password" not in get_by_name.json()

    # Delete friendship by name
    delete_by_name = client.delete(f"/v2/users/{u1['id']}/friends/{u2['name']}")
    assert delete_by_name.status_code in (200, 204)

    # Confirm friendship gone
    friends_after = client.get(f"/v2/users/{u1['id']}/friends/")
    assert not any(f["name"] == u2["name"] for f in friends_after.json())


def test_delete_user_cleans_up_avatar(user_payload):
    u = client.post("/v2/users/", json=user_payload).json()
    client.post(
        f"/v2/users/{u['id']}/avatar",
        files={"file": ("a.png", io.BytesIO(b"x"), "image/png")},
    )

    # Delete user
    del_res = client.delete(f"/v2/users/{u['id']}")
    assert del_res.status_code == 204

    # Avatar endpoints should now 404
    assert client.get(f"/v2/users/{u['id']}/avatar").status_code in (404, 410)
    assert client.put(
        f"/v2/users/{u['id']}/avatar",
        files={"file": ("b.png", io.BytesIO(b"y"), "image/png")},
    ).status_code in (404, 410)


def test_delete_user_cleans_up_friend_requests_and_friendships(
    user_payload, second_user_payload
):
    u1 = client.post("/v2/users/", json=user_payload).json()
    u2 = client.post("/v2/users/", json=second_user_payload).json()

    # u1 -> u2 request, u2 accepts (creates friendship)
    client.post(
        f"/v2/users/{u1['id']}/friend-requests/",
        json={"from": u1["id"], "to": u2["id"]},
    )
    client.patch(
        f"/v2/users/{u2['id']}/friend-requests/{u1['id']}", json={"status": "accepted"}
    )

    # Sanity: both see each other as friends
    assert any(
        f["id"] == u2["id"] for f in client.get(f"/v2/users/{u1['id']}/friends/").json()
    )
    assert any(
        f["id"] == u1["id"] for f in client.get(f"/v2/users/{u2['id']}/friends/").json()
    )

    # Delete u1; should remove friendships and requests involving u1
    assert client.delete(f"/v2/users/{u1['id']}").status_code == 204

    # u2’s friends list no longer includes u1
    friends_u2 = client.get(f"/v2/users/{u2['id']}/friends/")
    assert friends_u2.status_code == 200
    assert not any(f["id"] == u1["id"] for f in friends_u2.json())

    # Incoming/outgoing requests filtered by u2 should be empty
    assert client.get(f"/v2/users/{u2['id']}/friend-requests/?q=incoming").json() == []
    assert client.get(f"/v2/users/{u2['id']}/friend-requests/?q=outgoing").json() == []

    # Direct lookups by u1’s id/name should 404
    assert client.get(f"/v2/users/{u1['id']}").status_code == 404


def test_delete_user_removes_name_based_friend_routes(
    user_payload, second_user_payload
):
    u1 = client.post("/v2/users/", json=user_payload).json()
    u2 = client.post("/v2/users/", json=second_user_payload).json()

    client.post(
        f"/v2/users/{u1['id']}/friend-requests/",
        json={"from": u1["id"], "to": u2["id"]},
    )
    client.patch(
        f"/v2/users/{u2['id']}/friend-requests/{u1['id']}", json={"status": "accepted"}
    )

    # Delete u2
    assert client.delete(f"/v2/users/{u2['id']}").status_code == 204

    # u1 can't fetch or delete friend-by-name anymore
    assert client.get(f"/v2/users/{u1['id']}/friends/{u2['name']}").status_code in (
        404,
        410,
    )
    assert client.delete(f"/v2/users/{u1['id']}/friends/{u2['name']}").status_code in (
        404,
        410,
    )


########################################
# EVENTS
########################################


def test_events_create_and_query_minimal():
    # user event
    r1 = client.post(
        "/v2/events/",
        json={
            "when": "2025-10-15 10:00:00",
            "source": "http://localhost/page",
            "type": "click",
            "payload": {"x": 1},
            "user": "u-1",
        },
    )
    assert r1.status_code == 201

    # anon event
    r2 = client.post(
        "/v2/events/",
        json={
            "when": "2025-10-15 10:05:00",
            "source": "http://localhost/page",
            "type": "view",
            "payload": {},
            "user": None,
        },
    )
    assert r2.status_code == 201

    # filter by time window
    q = client.get(
        "/v2/events/",
        params={
            "after": "2025-10-15 09:59:00",
            "before": "2025-10-15 10:10:00",
            "source": "http://localhost/page",
        },
    )
    assert q.status_code == 200
    out = q.json()
    assert isinstance(out, list)
    assert any(e["type"] == "click" for e in out)
    assert any(e["type"] == "view" for e in out)


def test_events_are_immutable():
    # No update/delete routes should exist
    assert client.put("/v2/events/1").status_code in (404, 405)
    assert client.patch("/v2/events/1", json={}).status_code in (404, 405)
    assert client.delete("/v2/events/1").status_code in (404, 405)


@pytest.fixture(autouse=True)
def _reset_events_store():
    from user_service.v2 import events as ev

    ev._EVENTS.clear()
    ev._NEXT_EID = itertools.count(1)


def test_events_invalid_datetime_query_returns_400():
    # Our GET parser should reject bad 'after'/'before'
    r = client.get("/v2/events/", params={"after": "not-a-time"})
    assert r.status_code == 400


def test_events_time_bounds_inclusive():
    # Create events exactly on the bounds
    client.post(
        "/v2/events/",
        json={
            "when": "2025-10-15 10:00:00",
            "source": "http://localhost/page",
            "type": "t1",
            "payload": {},
        },
    )
    client.post(
        "/v2/events/",
        json={
            "when": "2025-10-15 10:10:00",
            "source": "http://localhost/page",
            "type": "t2",
            "payload": {},
        },
    )

    q = client.get(
        "/v2/events/",
        params={
            "after": "2025-10-15 10:00:00",
            "before": "2025-10-15 10:10:00",
            "source": "http://localhost/page",
        },
    )
    assert q.status_code == 200
    types = [e["type"] for e in q.json()]
    assert "t1" in types and "t2" in types  # inclusive at both ends


def test_events_rejects_bad_datetime():
    r = client.post(
        "/v2/events/",
        json={
            "when": "not-a-time",
            "source": "http://localhost/x",
            "type": "click",
            "payload": {},
            "user": None,
        },
    )
    assert r.status_code in (400, 422)  # whichever your validator returns


def test_events_query_no_matches_returns_empty_list():
    r = client.get("/v2/events/", params={"type": "nope"})
    assert r.status_code == 200
    assert r.json() == []


###############################
# Extra coverage for /v2/events
###############################


def test_events_filter_by_type_and_user_together():
    # two types, two users; then filter t=click & user=u1
    client.post(
        "/v2/events/",
        json={
            "when": "2025-10-15 10:00:00",
            "source": "http://s",
            "type": "click",
            "payload": {},
            "user": "u1",
        },
    )
    client.post(
        "/v2/events/",
        json={
            "when": "2025-10-15 10:01:00",
            "source": "http://s",
            "type": "view",
            "payload": {},
            "user": "u1",
        },
    )
    client.post(
        "/v2/events/",
        json={
            "when": "2025-10-15 10:02:00",
            "source": "http://s",
            "type": "click",
            "payload": {},
            "user": "u2",
        },
    )

    r = client.get("/v2/events/", params={"type": "click", "user": "u1"})
    assert r.status_code == 200
    out = r.json()
    assert all(e["type"] == "click" for e in out)
    assert all(e.get("user") == "u1" for e in out)
    # Should only be the first event
    assert len(out) == 1


def test_events_invalid_before_returns_400():
    r = client.get("/v2/events/", params={"before": "nope"})
    assert r.status_code == 400


def test_events_after_greater_than_before_either_400_or_empty():
    # If your handler validates window, it should 400; if not, it should return []
    r = client.get(
        "/v2/events/",
        params={
            "after": "2025-10-15 11:00:00",
            "before": "2025-10-15 10:00:00",
            "source": "http://s",
        },
    )
    assert r.status_code in (200, 400)
    if r.status_code == 200:
        assert r.json() == []


def test_events_reject_empty_type_on_post():
    r = client.post(
        "/v2/events/",
        json={
            "when": "2025-10-15 10:00:00",
            "source": "http://localhost/x",
            "type": "",  # invalid
            "payload": {},
            "user": None,
        },
    )
    assert r.status_code in (400, 422)


def test_events_source_filter_exact_match_only():
    client.post(
        "/v2/events/",
        json={
            "when": "2025-10-15 10:00:00",
            "source": "http://a",
            "type": "x",
            "payload": {},
        },
    )
    client.post(
        "/v2/events/",
        json={
            "when": "2025-10-15 10:00:01",
            "source": "http://b",
            "type": "x",
            "payload": {},
        },
    )
    r = client.get("/v2/events/", params={"source": "http://a"})
    assert r.status_code == 200
    out = r.json()
    assert len(out) == 1
    assert out[0]["source"] == "http://a"


########################################
# ANALYTICS
########################################


def test_analytics_shapes_minimal():
    # Before implementation this will 404 (RED). After, it should be 200 with keys.
    res = client.get("/v2/analytics")
    assert res.status_code == 200
    js = res.json()
    assert set(js["session_length"].keys()) == {"min", "max", "mean", "median", "p95"}
    assert set(js["active_users"].keys()) == {"current", "max"}


def test_analytics_on_and_since_have_expected_structure():
    # Seed a couple of events across two days for a single user
    client.post(
        "/v2/events/",
        json={
            "when": "2025-10-15 10:00:00",
            "source": "http://x",
            "type": "view",
            "payload": {},
            "user": "u-1",
        },
    )
    client.post(
        "/v2/events/",
        json={
            "when": "2025-10-16 11:00:00",
            "source": "http://y",
            "type": "click",
            "payload": {},
            "user": "u-1",
        },
    )

    r_on = client.get("/v2/analytics", params={"on": "2025-10-15"})
    assert r_on.status_code == 200
    js_on = r_on.json()
    assert set(js_on["session_length"].keys()) == {
        "min",
        "max",
        "mean",
        "median",
        "p95",
    }
    assert set(js_on["active_users"].keys()) == {"current", "max"}

    r_since = client.get("/v2/analytics", params={"since": "2025-10-15"})
    assert r_since.status_code == 200
    js_since = r_since.json()
    assert set(js_since["session_length"].keys()) == {
        "min",
        "max",
        "mean",
        "median",
        "p95",
    }
    assert set(js_since["active_users"].keys()) == {"current", "max"}


@pytest.fixture(autouse=True)
def _reset_events_and_ttl():
    from user_service.v2 import events as ev

    ev._EVENTS.clear()
    ev._NEXT_EID = itertools.count(1)
    old = os.environ.get("AUTH_TTL_SECONDS")
    os.environ["AUTH_TTL_SECONDS"] = "60"  # 60s TTL for clear splits/overlaps
    yield
    if old is None:
        os.environ.pop("AUTH_TTL_SECONDS", None)
    else:
        os.environ["AUTH_TTL_SECONDS"] = old


def test_analytics_splits_sessions_when_gap_exceeds_ttl():
    # One user, three events; a >60s gap should split into 2 sessions.
    # Session 1: 10:00:00 & 10:00:30  -> ends at 10:01:30 (60s after last)
    # Session 2: 10:02:00             -> ends at 10:03:00
    # Durations: [90, 60] seconds  -> min=60, max=90, mean=75, median=60, p95=90
    client.post(
        "/v2/events/",
        json={
            "when": "2025-10-15 10:00:00",
            "source": "http://x",
            "type": "view",
            "payload": {},
            "user": "u1",
        },
    )
    client.post(
        "/v2/events/",
        json={
            "when": "2025-10-15 10:00:30",
            "source": "http://x",
            "type": "view",
            "payload": {},
            "user": "u1",
        },
    )
    client.post(
        "/v2/events/",
        json={
            "when": "2025-10-15 10:02:00",
            "source": "http://x",
            "type": "view",
            "payload": {},
            "user": "u1",
        },
    )

    res = client.get("/v2/analytics", params={"on": "2025-10-15"})
    assert res.status_code == 200
    stats = res.json()["session_length"]
    # exact expectations given our percentile/median implementation
    assert stats["min"] == 60.0
    assert stats["max"] == 90.0
    assert stats["mean"] == pytest.approx(75.0, abs=1e-9)
    assert stats["median"] == 60.0  # with 2 items our median picks index 0
    assert stats["p95"] == 90.0

    # Not active at end of day with short TTL
    assert res.json()["active_users"]["current"] == 0


def test_analytics_max_concurrent_users_with_overlap_windows():
    # With TTL=60s, three users fire at staggered times creating a 3-way overlap:
    # A: [10:00:00, 10:01:00], B: [10:00:30, 10:01:30], C: [10:01:00, 10:02:00]
    # At 10:01:00 we expect max concurrent = 3 (starts processed before ends).
    for when, user in [
        ("2025-10-16 10:00:00", "A"),
        ("2025-10-16 10:00:30", "B"),
        ("2025-10-16 10:01:00", "C"),
    ]:
        client.post(
            "/v2/events/",
            json={
                "when": when,
                "source": "http://x",
                "type": "ping",
                "payload": {},
                "user": user,
            },
        )

    res = client.get("/v2/analytics", params={"on": "2025-10-16"})
    assert res.status_code == 200
    active = res.json()["active_users"]
    assert active["max"] == 3
    # End-of-day "current" should be 0 with short TTL
    assert active["current"] == 0


########################################
# Authorization Coverage
########################################


def _expiry_str(hours: int = 1) -> str:
    """Return an expiry string HOURS in the future."""
    return (datetime.utcnow() + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")


def _auth_v2(name: str, password: str, expiry: str | None = None):
    """Helper to call the v2 authentication endpoint."""
    if expiry is None:
        expiry = _expiry_str()

    return client.post(
        "/v2/authentications/",
        json={
            "name": name,
            "password": password,
            "expiry": expiry,
        },
    )


@pytest.fixture
def auth_v2_fake_repo(user_payload):
    """
    Fake UserRepository for auth_v2 tests.

    It returns a single user whose password hash matches user_payload["password"].
    """

    # Hash the known password the same way auth_v2 expects
    password_hash = bcrypt.hashpw(
        user_payload["password"].encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")

    class FakeUser:
        def __init__(self):
            self.id = 1
            self.name = user_payload["name"]
            self.password_hash = password_hash
            self.tier = 1  # default tier

    class FakeRepo:
        async def get_by_name(self, name: str):
            if name == user_payload["name"]:
                return FakeUser()
            return None

    return FakeRepo()


def test_v2_auth_success_returns_token(user_payload, auth_v2_fake_repo):
    # Override the get_user_repository dependency to use our fake repo
    app.dependency_overrides[auth_v2_module.get_user_repository] = (
        lambda: auth_v2_fake_repo
    )
    try:
        res = _auth_v2(user_payload["name"], user_payload["password"])
        assert res.status_code in (200, 201)

        body = res.json()
        # auth_v2 returns AuthenticationResponse(jwt=...)
        assert "jwt" in body
        assert isinstance(body["jwt"], str)
        assert body["jwt"]  # non-empty
    finally:
        # Clean up the override so other tests are unaffected
        app.dependency_overrides.pop(auth_v2_module.get_user_repository, None)


def test_v2_auth_invalid_credentials_returns_401(user_payload, auth_v2_fake_repo):
    # Same fake repo, but wrong password → bcrypt.checkpw should fail
    app.dependency_overrides[auth_v2_module.get_user_repository] = (
        lambda: auth_v2_fake_repo
    )
    try:
        res = _auth_v2(user_payload["name"], "wrong-password")
        assert res.status_code == 401
    finally:
        app.dependency_overrides.pop(auth_v2_module.get_user_repository, None)


def test_v2_auth_unknown_user_returns_401(user_payload):
    """If the repo returns no user, auth_v2 should 401."""

    class NoUserRepo:
        async def get_by_name(self, name: str):
            return None

    app.dependency_overrides[auth_v2_module.get_user_repository] = lambda: NoUserRepo()
    try:
        res = _auth_v2("does-not-exist", "whatever")
        assert res.status_code == 401
    finally:
        app.dependency_overrides.pop(auth_v2_module.get_user_repository, None)


def test_v2_auth_user_missing_password_hash_returns_401(user_payload):
    """If user has no password_hash, auth_v2 should 401."""

    class UserNoPassword:
        def __init__(self):
            self.id = 1
            self.name = user_payload["name"]
            self.password_hash = None
            self.tier = 1

    class RepoNoPassword:
        async def get_by_name(self, name: str):
            if name == user_payload["name"]:
                return UserNoPassword()
            return None

    app.dependency_overrides[auth_v2_module.get_user_repository] = (
        lambda: RepoNoPassword()
    )
    try:
        res = _auth_v2(user_payload["name"], user_payload["password"])
        assert res.status_code == 401
    finally:
        app.dependency_overrides.pop(auth_v2_module.get_user_repository, None)


def test_v2_auth_invalid_expiry_returns_400(user_payload, auth_v2_fake_repo):
    """Bad expiry string should bubble up as HTTP 400 from auth_v2."""
    app.dependency_overrides[auth_v2_module.get_user_repository] = (
        lambda: auth_v2_fake_repo
    )
    try:
        res = _auth_v2(
            user_payload["name"],
            user_payload["password"],
            expiry="not-a-date",
        )
        assert res.status_code == 400
    finally:
        app.dependency_overrides.pop(auth_v2_module.get_user_repository, None)


def test_v2_delete_authentication_success(user_payload, auth_v2_fake_repo):
    """Delete v2 authentication should expire a valid token."""
    # First get a valid JWT via auth_v2
    app.dependency_overrides[auth_v2_module.get_user_repository] = (
        lambda: auth_v2_fake_repo
    )
    try:
        res = _auth_v2(user_payload["name"], user_payload["password"])
        assert res.status_code in (200, 201)
        token = res.json()["jwt"]
    finally:
        app.dependency_overrides.pop(auth_v2_module.get_user_repository, None)

    # Now delete the token via the v2 DELETE endpoint
    del_res = client.request(
        "DELETE",
        "/v2/authentications/",
        json={"jwt": token},
    )
    # Your implementation returns 200 with a JSON body
    assert del_res.status_code == 200
    body = del_res.json()
    assert body.get("message") == "Token expired successfully"


def test_v2_delete_authentication_invalid_token_returns_400():
    """Invalid / already-expired token should return HTTP 400."""
    res = client.request(
        "DELETE",
        "/v2/authentications/",
        json={"jwt": "not-a-token"},
    )
    assert res.status_code == 400
    body = res.json()
    assert body.get("detail") == "Invalid token"
