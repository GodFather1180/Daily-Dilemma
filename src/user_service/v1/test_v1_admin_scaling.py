import re
import time
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import create_engine

from user_service.v1.api import app
from user_service.v1.models.user import Base, User, UserRepository, get_user_repository

# -------------------------------
# Tunables/expectations for v1
# -------------------------------
API_DEFAULT_PAGE_CAP = 200  # Expected upper bound for /users/ default page
UI_ROW_HEURISTIC_MAX = 250  # Max <tr>/<li> we allow on an admin page
ADMIN_TIME_BUDGET_S = 1.5  # Basic perf budget to catch "doesn't really work"


############################
# DB & app wiring (v1)
############################
@pytest.fixture(scope="function")
def engine():
    # In-memory SQLite DB for fast, isolated tests
    engine = create_engine("sqlite:///:memory:?check_same_thread=False")
    Base.metadata.create_all(bind=engine)
    yield engine


@pytest.fixture(scope="function")
def session(engine):
    conn = engine.connect()
    trans = conn.begin()
    db = Session(bind=conn)
    yield db
    trans.rollback()
    conn.close()


@pytest.fixture(scope="function")
def repo(session):
    yield UserRepository(session)


@pytest.fixture(scope="function")
def client(repo):
    # Use the real v1 app, but swap in our in-memory repo
    app.dependency_overrides[get_user_repository] = lambda: repo
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def admin_auth():
    # basic auth credentials for the admin UI
    return ("admin", "pw")


############################
# Seed helpers
############################
def seed(session, n=21_000):
    session.bulk_save_objects(
        [
            User(name=f"user{i}", email=f"user{i}@example.com", password_hash="x")
            for i in range(n)
        ]
    )
    session.commit()


def seed_users(session, n):
    session.bulk_save_objects(
        [
            User(name=f"user{i}", email=f"user{i}@example.com", password_hash="x")
            for i in range(n)
        ]
    )
    session.commit()


############################
# Response helpers
############################
def _rows(payload):
    data = payload.json()
    return (
        data
        if isinstance(data, list)
        else data.get(
            "items", data.get("users", data.get("data", data.get("results", [])))
        )
    )


def _rows_from_payload(payload_json):
    """
    Support multiple shapes:
    - legacy list: [...]
    - page-like: {"items": [...]}
    - alt key: {"users": [...]}
    - generic: {"data": [...]}
    """
    if isinstance(payload_json, list):
        return payload_json
    if isinstance(payload_json, dict):
        for key in ("items", "users", "data", "results"):
            if key in payload_json and isinstance(payload_json[key], list):
                return payload_json[key]
    return []


def _ids_from_rows(rows):
    # prefer "id", fall back to "user_id"
    ids = []
    for r in rows:
        if "id" in r:
            ids.append(r["id"])
        elif "user_id" in r:
            ids.append(r["user_id"])
    return ids


########################################
# TESTS (v1 behavior for admin scaling)
########################################


def test_admin_scaling_is_paginated(client, session):
    seed(session, 21_000)

    # default page: should be capped (e.g., <=200)
    r0 = client.get("/users/")
    assert r0.status_code == 200
    rows0 = _rows(r0)
    assert 1 <= len(rows0) <= API_DEFAULT_PAGE_CAP

    # page through two pages and ensure no overlap
    r1 = client.get("/users/?limit=100&offset=0")
    assert r1.status_code == 200
    r2 = client.get("/users/?limit=100&offset=100")
    assert r2.status_code == 200
    ids1 = {u["id"] for u in _rows(r1)}
    ids2 = {u["id"] for u in _rows(r2)}
    assert len(ids1) == len(ids2) == 100
    assert ids1.isdisjoint(ids2)


def test_v1_users_is_paginated_by_default(client, session):
    """Default list should NOT return all users when there are many."""
    seed_users(session, 21_000)
    res = client.get("/users/")
    assert res.status_code == 200
    data = res.json()

    rows = _rows_from_payload(data)
    # Regardless of shape, default response must be capped
    assert len(rows) <= API_DEFAULT_PAGE_CAP

    # If page-like metadata exists, sanity-check it without requiring exact keys
    if isinstance(data, dict):
        total = data.get("total") or data.get("count") or data.get("total_count")
        if total is not None:
            assert total == 21_000


def test_v1_users_limit_is_capped(client, session):
    seed_users(session, 1_000)
    res = client.get("/users/?limit=500")  # ask for too much
    assert res.status_code == 200
    rows = _rows_from_payload(res.json())
    assert len(rows) <= API_DEFAULT_PAGE_CAP  # cap enforced


def test_v1_users_offset_paginates_without_overlap(client, session):
    seed_users(session, 300)
    # request 3 pages of 100
    p1 = client.get("/users/?limit=100&offset=0")
    p2 = client.get("/users/?limit=100&offset=100")
    p3 = client.get("/users/?limit=100&offset=200")
    for r in (p1, p2, p3):
        assert r.status_code == 200

    r1 = _rows_from_payload(p1.json())
    r2 = _rows_from_payload(p2.json())
    r3 = _rows_from_payload(p3.json())

    ids = _ids_from_rows(r1) + _ids_from_rows(r2) + _ids_from_rows(r3)
    assert len(ids) == 300
    assert len(set(ids)) == 300  # no overlap


def test_v1_users_search_by_name_or_email(client, session):
    seed_users(session, 500)
    # Add a distinctive user
    session.add(User(name="Ada Lovelace", email="ada@lovelace.org", password_hash="x"))
    session.commit()

    # Try common query param names in order: q, search, query
    for qp in ("q", "search", "query"):
        res = client.get(f"/users/?{qp}=lovelace&limit=50")
        if res.status_code != 200:
            continue
        rows = _rows_from_payload(res.json())
        emails = [u.get("email") for u in rows]
        if any(e and "lovelace" in e.lower() for e in emails):
            break
    else:
        pytest.fail("Search did not return expected results for any of q/search/query")


def test_v1_users_never_exposes_password_fields(client, session):
    seed_users(session, 5)
    res = client.get("/users/?limit=5")
    assert res.status_code == 200
    rows = _rows_from_payload(res.json())
    for u in rows:
        assert "password" not in u
        assert "password_hash" not in u


#######################################
# Helper Test Coverage
#######################################


def test_rows_from_payload_accepts_list_and_returns_it_unchanged():
    rows = [{"id": 1}, {"id": 2}]
    # When given a plain list, _rows_from_payload should return it directly
    out = _rows_from_payload(rows)
    assert out is rows
    assert [r["id"] for r in out] == [1, 2]


def test_rows_from_payload_falls_back_to_empty_for_unknown_shape():
    # Non-list, non-dict inputs should safely fall back to []
    out = _rows_from_payload("not-a-dict-or-list")
    assert out == []


def test_ids_from_rows_uses_user_id_fallback_when_id_missing():
    rows = [
        {"id": 1, "name": "primary"},
        {"user_id": 2, "name": "fallback"},
        {"name": "no-id"},
    ]
    ids = _ids_from_rows(rows)
    # prefers "id" but falls back to "user_id"
    assert ids == [1, 2]


def test_rows_from_payload_unrecognized_dict_returns_empty_list():
    payload = {"foo": "bar", "count": 3}
    rows = _rows_from_payload(payload)
    assert rows == []


def test_ids_from_rows_prefers_id_and_falls_back_to_user_id():
    rows = [
        {"id": 1},
        {"user_id": 2},
        {"id": 3, "user_id": 99},
    ]
    ids = _ids_from_rows(rows)
    assert ids == [1, 2, 3]


########################################
# Admin UI hardening tests (strict)
########################################


@pytest.mark.parametrize("path", ["/admin", "/admin/"])
def test_admin_page_exists_is_fast_and_paginated(client, session, path, admin_auth):
    """
    Enforce that /admin:
    - Exists and returns 200 with correct auth
    - Renders a bounded number of rows on the first page
    - Exposes a detectable 'next page' control when there are more rows
    - Responds within a small performance budget under heavy data volume
    """
    seed_users(session, 21_000)

    t0 = time.perf_counter()
    res = client.get(path, auth=admin_auth)
    dt = time.perf_counter() - t0

    # Must exist and be accessible with correct creds
    assert res.status_code == 200, f"{path} must exist be accessible {res.status_code}"

    # Must be reasonably fast (basic 'doesn't really work' proxy)
    assert dt < ADMIN_TIME_BUDGET_S, f"{path} too slow under load: {dt:.2f}s"

    html = res.text

    # Must not dump thousands of rows on page 1
    bounded = (html.count("<tr") <= UI_ROW_HEURISTIC_MAX) or (
        html.count("<li") <= UI_ROW_HEURISTIC_MAX
    )
    assert bounded, f"{path} appears to render too many rows on first page"

    # Must expose a next-page control (rel=next preferred; allow tolerant fallbacks)
    next_href = None
    m = re.search(r'rel=["\']next["\'][^>]*href=["\']([^"\']+)["\']', html)
    if m:
        next_href = m.group(1)
    else:
        m = re.search(r'data-next-page=["\']([^"\']+)["\']', html)
        if m:
            next_href = m.group(1)
        else:
            # Look for a typical "Next" anchor
            m = re.search(
                r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>\s*(Next|»)\s*</a>', html, re.I
            )
            if m:
                next_href = m.group(1)

    assert next_href, f"{path} provide detectable page control when many users exist"


def test_admin_page_bounded_changescontent(client, session, admin_auth, path="/admin"):
    """
    Follow the detected next page and ensure:
    - Page 2 also bounded
    - Content changes across pages (not re-rendering the same large block)
    """
    seed_users(session, 2_100)

    r1 = client.get(path, auth=admin_auth)
    assert r1.status_code == 200
    html1 = r1.text

    # Extract next link (must exist)
    next_href = None
    m = re.search(r'rel=["\']next["\'][^>]*href=["\']([^"\']+)["\']', html1)
    if m:
        next_href = m.group(1)
    else:
        m = re.search(r'data-next-page=["\']([^"\']+)["\']', html1)
        if m:
            next_href = m.group(1)
        else:
            m = re.search(
                r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>\s*(Next|»)\s*</a>', html1, re.I
            )
            if m:
                next_href = m.group(1)

    assert next_href, "Admin must provide a detectable next-page link"

    r2 = client.get(next_href, auth=admin_auth)
    assert r2.status_code == 200
    html2 = r2.text

    # Page 1 & 2 both bounded
    assert (html1.count("<tr") <= UI_ROW_HEURISTIC_MAX) or (
        html1.count("<li") <= UI_ROW_HEURISTIC_MAX
    )
    assert (html2.count("<tr") <= UI_ROW_HEURISTIC_MAX) or (
        html2.count("<li") <= UI_ROW_HEURISTIC_MAX
    )

    # Content should change across pages
    assert html2 != html1


def test_admin_requires_auth(client, session, path="/admin"):
    seed_users(session, 1_000)

    # No auth should not succeed
    res = client.get(path)
    assert res.status_code in (401, 403)

    # Wrong auth should not succeed
    res = client.get(path, auth=("admin", "wrongpw"))
    assert res.status_code in (401, 403)

    # Right auth should succeed (matches fixture)
    res = client.get(path, auth=("admin", "pw"))
    assert res.status_code == 200


def test_v1_users_pagination_is_stable_for_same_params(client, session):
    """
    Same query params should return the same ordering
    (helps front-ends avoid row 'jumping').
    We don't require any particular global order, just stability for identical requests.
    """
    seed_users(session, 250)
    a = client.get("/users/?limit=100&offset=50")
    b = client.get("/users/?limit=100&offset=50")
    assert a.status_code == b.status_code == 200

    ra = _rows_from_payload(a.json())
    rb = _rows_from_payload(b.json())

    assert _ids_from_rows(ra) == _ids_from_rows(rb)


def test_v1_users_offset_beyond_total_is_empty(client, session):
    """Asking for pages beyond the end should return an empty page,
    not a huge dump or error."""
    seed_users(session, 150)
    res = client.get("/users/?limit=50&offset=1000")
    assert res.status_code == 200
    rows = _rows_from_payload(res.json())
    assert rows == []


def test_admin_index_search_query_works(client, session, admin_auth):
    seed_users(session, 10)
    res = client.get("/admin?q=user5", auth=admin_auth)
    assert res.status_code == 200
    html = res.text
    assert "user5" in html
    assert "limit=" in html and "offset=" in html


def test_delete_authentications_invalid_token_returns_400(client):
    """DELETE /v2/authentications/ with an unknown token should return 400."""
    resp = client.request(
        "DELETE",
        "/v2/authentications/",
        json={"jwt": "not-a-real-token"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid token"
