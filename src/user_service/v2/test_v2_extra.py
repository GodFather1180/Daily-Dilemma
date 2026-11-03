import io
import uuid
from fastapi.testclient import TestClient
from PIL import Image

from user_service.v1.api import app
from user_service.v2 import user_v2 as u

client = TestClient(app)


def _u(name_prefix="user"):
    s = uuid.uuid4().hex[:8]
    return {
        "name": f"{name_prefix}_{s}",
        "email": f"{name_prefix}_{s}@ex.com",
        "password": "pw",
    }


# =========================
# Helpers (direct coverage)
# =========================
def test_hash_deterministic():
    h1 = u._hash("abc")
    h2 = u._hash("abc")
    h3 = u._hash("xyz")
    assert h1 == h2 and h1 != h3 and h1.startswith("sha256$")


def test_find_by_name_email_and_ensure_unique_exclude_ok():
    p = _u("alice")
    created = client.post("/v2/users/", json=p).json()
    # happy path: found
    found = u._find_by_name_email(p["name"], p["email"])
    assert found and found["id"] == created["id"]
    # exclude path: changing to same name with exclude should not raise
    u._ensure_unique_name(p["name"], exclude_user_id=found["id"])
    # conflict path already covered in other test files


def test_find_by_name_email_returns_none_when_no_match():
    # Use a name/email combo we will never create
    result = u._find_by_name_email("no-such-name", "no-such@example.com")
    assert result is None


# =========================
# Users – extra branches
# =========================
def test_update_with_no_fields_is_noop():
    p = _u("noop")
    uid = client.post("/v2/users/", json=p).json()["id"]
    # no changes provided -> still 200 and unchanged public fields
    r = client.patch(f"/v2/users/{uid}", json={})
    assert r.status_code == 200
    js = r.json()
    assert js["id"] == uid and js["name"] == p["name"] and js["email"] == p["email"]


def test_update_user_changes_name_and_prevents_duplicate():
    # First user
    p1 = _u("rename1")
    u1 = client.post("/v2/users/", json=p1).json()

    # Change name to a new unique value (happy path)
    new_name = p1["name"] + "_new"
    r_ok = client.patch(f"/v2/users/{u1['id']}", json={"name": new_name})
    assert r_ok.status_code == 200
    assert r_ok.json()["name"] == new_name

    # Second user
    p2 = _u("rename2")
    u2 = client.post("/v2/users/", json=p2).json()

    # Try to change second user to use the same name as user1 -> 409
    r_conflict = client.patch(f"/v2/users/{u2['id']}", json={"name": new_name})
    assert r_conflict.status_code == 409


def test_change_password_rejects_incorrect_original_password():
    p = _u("wrongpw")
    user = client.post("/v2/users/", json=p).json()

    r = client.patch(
        f"/v2/users/{user['id']}",
        json={"password": "definitely-wrong", "new_password": "newpw"},
    )
    assert r.status_code == 403


def test_delete_unknown_user_returns_404():
    r = client.delete("/v2/users/999999")
    assert r.status_code == 404


# =========================
# Avatars – missing branches
# =========================
def test_delete_avatar_when_file_missing_returns_204():
    p = _u("ava-missing")
    uid = client.post("/v2/users/", json=p).json()["id"]
    # never uploaded; delete should swallow FileNotFoundError and return 204
    r = client.delete(f"/v2/users/{uid}/avatar")
    assert r.status_code == 204


def test_upload_then_update_avatar_still_ok_with_real_bytes():
    p = _u("ava-ok")
    uid = client.post("/v2/users/", json=p).json()["id"]
    up = client.post(
        f"/v2/users/{uid}/avatar",
        files={"file": ("a.png", io.BytesIO(b"\x89PNG\r\n\x1a\nx"), "image/png")},
    )
    assert up.status_code == 201
    put = client.put(
        f"/v2/users/{uid}/avatar",
        files={"file": ("b.jpg", io.BytesIO(b"\xff\xd8\xff"), "image/jpeg")},
    )
    assert put.status_code == 200


def test_get_avatar_for_user_with_no_file_returns_404():
    p = _u("ava-nofile")
    uid = client.post("/v2/users/", json=p).json()["id"]

    r = client.get(f"/v2/users/{uid}/avatar")
    assert r.status_code == 404


def _make_small_png_bytes():
    buf = io.BytesIO()
    img = Image.new("RGBA", (2, 2), (255, 0, 0, 255))
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_upload_avatar_uses_image_pipeline_and_can_be_fetched():
    p = _u("ava-pipe")
    uid = client.post("/v2/users/", json=p).json()["id"]

    png_bytes = _make_small_png_bytes()
    up = client.post(
        f"/v2/users/{uid}/avatar",
        files={"file": ("avatar.png", io.BytesIO(png_bytes), "image/png")},
    )
    assert up.status_code == 201

    get_res = client.get(f"/v2/users/{uid}/avatar")
    assert get_res.status_code == 200
    assert get_res.headers["content-type"].startswith("image/")


# =========================
# Friend requests – all paths
# =========================
def test_put_answer_friend_request_decline_path():
    a = client.post("/v2/users/", json=_u("a")).json()
    b = client.post("/v2/users/", json=_u("b")).json()
    client.post(f"/v2/users/{a['id']}/friend-requests/", json={"to": b["id"]})
    r = client.put(
        f"/v2/users/{b['id']}/friend-requests/{a['id']}", json={"accept": False}
    )
    assert r.status_code == 200
    # not friends after decline
    assert client.get(f"/v2/users/{a['id']}/friends/").json() == []


def test_patch_answer_invalid_status_400():
    a = client.post("/v2/users/", json=_u("pa")).json()
    b = client.post("/v2/users/", json=_u("pb")).json()
    client.post(f"/v2/users/{a['id']}/friend-requests/", json={"to": b["id"]})
    r = client.patch(
        f"/v2/users/{b['id']}/friend-requests/{a['id']}", json={"status": "MAYBE"}
    )
    assert r.status_code == 400


def test_cancel_friend_request_all_three_paths():
    # 1) pending exists -> DELETE cancels (204)
    a = client.post("/v2/users/", json=_u("p1")).json()
    b = client.post("/v2/users/", json=_u("p2")).json()
    client.post(f"/v2/users/{a['id']}/friend-requests/", json={"to": b["id"]})
    r1 = client.delete(f"/v2/users/{a['id']}/friend-requests/{b['id']}")
    assert r1.status_code == 204

    # 2) no pending, but friends -> DELETE unfriends (204)
    a2 = client.post("/v2/users/", json=_u("f1")).json()
    b2 = client.post("/v2/users/", json=_u("f2")).json()
    client.post(f"/v2/users/{a2['id']}/friend-requests/", json={"to": b2["id"]})
    client.patch(
        f"/v2/users/{b2['id']}/friend-requests/{a2['id']}", json={"status": "accepted"}
    )
    r2 = client.delete(f"/v2/users/{a2['id']}/friend-requests/{b2['id']}")
    assert r2.status_code in (200, 204)
    assert client.get(f"/v2/users/{a2['id']}/friends/").json() == []

    # 3) neither pending nor friends -> 404
    x = client.post("/v2/users/", json=_u("x")).json()
    y = client.post("/v2/users/", json=_u("y")).json()
    r3 = client.delete(f"/v2/users/{x['id']}/friend-requests/{y['id']}")
    assert r3.status_code == 404


def test_get_friend_by_id_404_when_not_friends():
    a = client.post("/v2/users/", json=_u("gfid-a")).json()
    b = client.post("/v2/users/", json=_u("gfid-b")).json()

    r = client.get(f"/v2/users/{a['id']}/friends/{b['id']}")
    assert r.status_code == 404


def test_get_friend_by_name_404_when_not_friends():
    a = client.post("/v2/users/", json=_u("gfn-a")).json()
    b = client.post("/v2/users/", json=_u("gfn-b")).json()

    r = client.get(f"/v2/users/{a['id']}/friends/{b['name']}")
    assert r.status_code == 404


def test_delete_friend_by_id_404_when_not_friends():
    a = client.post("/v2/users/", json=_u("dfid-a")).json()
    b = client.post("/v2/users/", json=_u("dfid-b")).json()

    r = client.delete(f"/v2/users/{a['id']}/friends/{b['id']}")
    assert r.status_code == 404


def test_delete_friend_by_name_404_when_not_friends():
    a = client.post("/v2/users/", json=_u("dfn-a")).json()
    b = client.post("/v2/users/", json=_u("dfn-b")).json()

    r = client.delete(f"/v2/users/{a['id']}/friends/{b['name']}")
    assert r.status_code == 404


# =========================
# Friends – success branches
# =========================
def test_get_friend_by_id_success_and_friend_objects_for():
    a = client.post("/v2/users/", json=_u("ga")).json()
    b = client.post("/v2/users/", json=_u("gb")).json()
    client.post(f"/v2/users/{a['id']}/friend-requests/", json={"to": b["id"]})
    client.patch(
        f"/v2/users/{b['id']}/friend-requests/{a['id']}", json={"status": "accepted"}
    )
    # _friend_objects_for internal coverage
    friends_list = u._friend_objects_for(a["id"])
    assert any(f["id"] == b["id"] for f in friends_list)

    # API success path for get-by-id
    r = client.get(f"/v2/users/{a['id']}/friends/{b['id']}")
    assert r.status_code == 200 and r.json()["id"] == b["id"]
