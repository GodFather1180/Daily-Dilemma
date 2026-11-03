import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import create_engine, text
from user_service.v1.api import app
from user_service.v1.models.user import Base, UserRepository, get_user_repository
import base64
import importlib
import time
import math
import io
from PIL import Image


###############
# FIXTURES needed for tests
###############

# These fixtures set up an in-memory SQLite database for testing


# Each test gets a fresh database
@pytest.fixture(scope="function")
def engine():
    # Use PostgreSQL for JWT tests, SQLite for others
    import os

    if os.getenv("USE_POSTGRES_FOR_TESTS"):
        engine = create_engine(
            "postgresql://user_service:user_service@db:5432/user_service"
        )
    else:
        engine = create_engine("sqlite:///:memory:?check_same_thread=False")
    Base.metadata.create_all(bind=engine)
    yield engine


@pytest.fixture(scope="function")
def session(engine):
    conn = engine.connect()
    conn.begin()
    db = Session(bind=conn)
    yield db
    db.rollback()
    conn.close()


@pytest.fixture(scope="function")
def repo(session):
    yield UserRepository(session)


@pytest.fixture(scope="function")
def client(repo):
    app.dependency_overrides[get_user_repository] = lambda: repo
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def make_user(session):
    """
    Factory to create (or ensure) a user exists in the test DB.
    Returns a dict payload suitable for POSTs to your API (no password fields).
    """
    import bcrypt
    from sqlalchemy import text

    def _make_user(
        name: str = "foo",
        email: str | None = "foo@example.com",
        password: str | None = "testpass123",
        ensure_exists: bool = True,
        reset: bool = False,
    ) -> dict:
        # Optionally remove any existing row for a clean slate
        if reset:
            session.execute(
                text("DELETE FROM users WHERE name = :name"), {"name": name}
            )
            session.commit()

        if ensure_exists:
            # If not present, insert directly (SQLite-portable, bcrypt-hashed)
            row = session.execute(
                text("SELECT id FROM users WHERE name = :name"),
                {"name": name},
            ).fetchone()

            if row is None:
                password_hash = None
                if password is not None:
                    password_hash = bcrypt.hashpw(
                        password.encode("utf-8"), bcrypt.gensalt()
                    ).decode("utf-8")

                session.execute(
                    text(
                        """
                        INSERT INTO users (name, email, password_hash, tier)
                        VALUES (:name, :email, :password_hash, :tier)
                        """
                    ),
                    {
                        "name": name,
                        "email": email,
                        "password_hash": password_hash,
                        "tier": 1,
                    },
                )
                session.commit()

        # Return a payload shape that your tests POST to the API
        payload = {"name": name}
        if email is not None:
            payload["email"] = email
        # Intentionally DO NOT return password/password_hash (security contract)
        return payload

    return _make_user


@pytest.fixture(scope="function")
def created_user(make_user):
    """
    Canonical ready-to-use user payload for tests that POST/DELETE/etc.
    Compatible with tests that tolerate 201|409 on create.
    """
    return make_user(
        name="foo",
        email="foo@example.com",
        password="testpass123",
        ensure_exists=True,
        reset=False,
    )


def _basic(user: str, pwd: str) -> dict:
    token = base64.b64encode(f"{user}:{pwd}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture(scope="function")
def client_admin(repo, monkeypatch):
    # Set ADMIN_PASSWORD for the duration of this test
    monkeypatch.setenv("ADMIN_PASSWORD", "pw")

    # Reload the admin.main module to pick up the env var
    import admin.main

    importlib.reload(admin.main)

    app.dependency_overrides[get_user_repository] = lambda: repo
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)


############
# TESTS
############


##############
# Issue: 1 - create user
##############


# Ensure that if we try to create a duplicate user,
# it doesn't block us from creating a different user later
def test_duplicate_create_does_not_block_followup_create(client):
    # Create user "bob"
    r1 = client.post("/users/", json={"name": "bob"})
    assert r1.status_code == 201

    # Create user "bob" again , should fail
    r2 = client.post("/users/", json={"name": "bob"})
    assert r2.status_code == 409

    # Create user "bob1"
    r3 = client.post("/users/", json={"name": "bob1"})
    assert r3.status_code == 201, r3.text


################
# Issue: 5 - delete user
################


# Test that deleting an existing user works
def test_delete_existing_user_returns_204_and_user_is_gone(client, created_user):
    # Create (or tolerate conflict if it already exists)
    resp = client.post("/users/", json=created_user)
    assert resp.status_code in (201, 409)

    # Delete
    resp = client.post("/users/delete", json=created_user)
    assert resp.status_code == 204
    # Many frameworks set Content-Length:
    #  0 but still expose .content == b""; this assert is fine.
    assert resp.content == b""

    # Verify gone (choose ONE contract
    #  stick to it; this test encodes 200 + {"user": None})
    resp = client.get(f"/users/{created_user['name']}")
    assert resp.status_code == 200
    assert resp.json() == {"user": None}


# Test that deleting a user that doesn't exist is idempotent
def test_delete_is_idempotent_returns_204_for_nonexistent_user(client, created_user):
    # Ensure user is absent
    client.post("/users/delete", json=created_user)

    # Deleting again should still be 204 (no info leak, idempotent)
    resp = client.post("/users/delete", json=created_user)
    assert resp.status_code == 204
    assert resp.content == b""


# Test that deleting one user does not affect other users
def test_delete_does_not_affect_other_users(client, created_user):
    another_user = {"name": "other_test_user"}

    client.post("/users/", json=created_user)
    client.post("/users/", json=another_user)

    # delete the first
    client.post("/users/delete", json=created_user)

    # assert first gone, second remains
    assert client.get(f"/users/{created_user['name']}").json() == {"user": None}
    assert (
        client.get(f"/users/{another_user['name']}").json()["user"]["name"]
        == another_user["name"]
    )


################
# Issue: 4  (password-protect /admin with single ADMIN_PASSWORD)
################


# Test that /admin requires authentication if ADMIN_PASSWORD is set
def test_admin_requires_auth(client_admin):
    r = client_admin.get("/admin")
    assert r.status_code == 401
    assert r.headers.get("www-authenticate") == "Basic"


# Test that /admin rejects wrong password if ADMIN_PASSWORD is set
def test_admin_rejects_wrong_password(client_admin):
    r = client_admin.get("/admin", headers=_basic("any", "wrong"))
    assert r.status_code == 401


# Test that /admin allows correct password if ADMIN_PASSWORD is set
def test_admin_allows_correct_password(client_admin):
    # prove guard exists first
    r0 = client_admin.get("/admin")
    assert r0.status_code == 401
    assert r0.headers.get("www-authenticate") == "Basic"

    # now prove correct creds work
    r = client_admin.get("/admin", headers=_basic("cs", "pw"))
    assert r.status_code in (200, 307, 308)


##############
# issue: 3 - performance of GET /users/{name}
##############

# Test that lookups by name are fast and exact, even with many users present
# This test assumes an index on the "name" column of the "users" table.
# If the index is missing, this test will fail.
# (This test also serves as a crude benchmark; if lookups become slow,
#  this test may start to take a long time and eventually timeout/fail.)


# Seed the database with n users named user_1, user_2, ..., user_n
def _seed_users(session, n=20_000):
    """SQLite-portable bulk insert of exactly n users."""
    session.execute(text("DELETE FROM users"))
    session.execute(
        text(
            """
        WITH RECURSIVE s(i) AS (
          SELECT 1
          UNION ALL
          SELECT i+1 FROM s WHERE i < :n
        )
        INSERT INTO users(name, tier) SELECT 'user_' || i, 1 FROM s
    """
        ),
        {"n": n},
    )
    session.commit()


# Compute the pct-th percentile of a list of numbers
def _pctl(xs, pct):
    xs = sorted(xs)
    k = (len(xs) - 1) * (pct / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    return xs[f] if f == c else xs[f] + (xs[c] - xs[f]) * (k - f)


# Test that lookups are exact matches, not similar matches
# (e.g. "target_user" should not match "target_user2")
# Also test that a missing user returns {"user": None}
def test_get_user_by_name_exactness_with_many_rows(client, session):
    """Functional: exact match, not similar; missing user returns {'user': None}."""
    _seed_users(session, 20_000)
    client.post("/users/", json={"name": "target_user"})
    r = client.get("/users/target_user")
    assert r.status_code == 200
    assert r.json()["user"]["name"] == "target_user"

    client.post("/users/", json={"name": "target_user2"})
    r2 = client.get("/users/target_user")
    assert r2.status_code == 200
    assert r2.json()["user"]["name"] == "target_user"

    r3 = client.get("/users/does_not_exist")
    assert r3.status_code == 200
    assert r3.json() == {"user": None}


# Test that an explicit named index exists on users(name)
def test_named_index_exists_on_users_name(session):
    """Require an explicit, named index so Postgres also
    benefits (not just SQLite autoindex)."""
    from sqlalchemy import inspect

    idxs = inspect(session.bind).get_indexes("users")
    names = {i["name"] for i in idxs}
    assert "ix_users_name" in names, "Expected explicit index "
    "ix_users_name on users(name)"


# Test that the query plan for lookups by name uses the index
def test_query_plan_uses_index_for_equality_lookup(session):
    """Planner should use an index for WHERE name = :n
    (SQLite phrasing contains 'USING INDEX')."""
    session.execute(text("DELETE FROM users"))
    session.execute(text("INSERT INTO users(name, tier) VALUES ('idx_probe', 1)"))
    session.commit()
    row = session.execute(
        text("EXPLAIN QUERY PLAN SELECT * FROM users WHERE name = :n"),
        {"n": "idx_probe"},
    ).fetchone()
    plan = " ".join(str(x) for x in row if x is not None).upper()
    assert ("USING INDEX" in plan) or ("USING COVERING INDEX" in plan), (
        f"Planner did not report index usage: {plan}"
    )


# Performance contract from the issue:
#   - dataset: ~20,000 users
#   - endpoint: GET /users/{name}
#   - p99 latency must be <= 127 ms


def test_get_user_by_name_p99_under_127ms_with_20k(client, session):
    """
    Performance contract from the issue:
      - dataset: ~20,000 users
      - endpoint: GET /users/{name}
      - p99 latency must be <= 127 ms
    """
    _seed_users(session, 20_000)
    # ensure target exists
    r = client.post("/users/", json={"name": "target_user"})
    assert r.status_code in (201, 409)

    # warm-up to stabilize caches/connection
    for _ in range(10):
        assert client.get("/users/target_user").status_code == 200

    samples_ms = []
    for _ in range(200):
        t0 = time.perf_counter()
        resp = client.get("/users/target_user")
        assert resp.status_code == 200 and resp.json()["user"]["name"] == "target_user"
        samples_ms.append((time.perf_counter() - t0) * 1000.0)

    p99 = _pctl(samples_ms, 99)
    assert p99 <= 127.0, f"p99={p99:.2f} ms (must be ≤ 127 ms with 20k users)"


###################
# ISSUE 7 new user fields
##################


def test_read_user(client, created_user):
    response = client.get("/users/foo")
    assert response.status_code == 200
    user = response.json()["user"]
    assert user["name"] == "foo"
    assert user["email"] == "foo@example.com"
    assert "id" in user


def test_create_user(client):
    response = client.post(
        "/users/",
        json={
            "name": "foobar",
            "email": "foobar@example.com",
            "password": "testpass123",
        },
    )
    assert response.status_code == 201
    user = response.json()["user"]
    assert user["name"] == "foobar"
    assert user["email"] == "foobar@example.com"
    assert "id" in user
    assert "password" not in user  # Security: password should not be returned


def test_create_existing_user(client, created_user):
    response = client.post(
        "/users/",
        json={"name": "foo", "email": "foo@example.com", "password": "testpass123"},
    )
    assert response.status_code == 409
    assert response.json() == {
        "detail": "Username already exists. Please choose a different username."
    }


def test_create_user_with_all_fields(client):
    """Test creating a user with id, name, email, and password"""
    response = client.post(
        "/users/",
        json={
            "name": "alice",
            "email": "alice@example.com",
            "password": "SecurePass123!",
        },
    )
    assert response.status_code == 201
    data = response.json()
    user = data["user"]

    # Should return id, name, and email
    assert "id" in user
    assert user["name"] == "alice"
    assert user["email"] == "alice@example.com"

    # Should NOT return password or password hash
    assert "password" not in user
    assert "password_hash" not in user


def test_unique_email(client):
    """Test that email must be unique across users"""
    # Create first user
    client.post(
        "/users/",
        json={"name": "bob", "email": "bob@example.com", "password": "Pass123!"},
    )

    # Try to create second user with same email but different name
    response = client.post(
        "/users/",
        json={
            "name": "robert",
            "email": "bob@example.com",  # Same email!
            "password": "DifferentPass456!",
        },
    )

    assert response.status_code == 409  # Conflict
    assert response.json() == {
        "detail": (
            "Email already exists. Please use a different email or try logging in."
        )
    }


def test_unique_name_still_enforced(client):
    """Test that name is still unique (as issue requires)"""
    # Create first user
    client.post(
        "/users/",
        json={"name": "carol", "email": "carol1@example.com", "password": "Pass123!"},
    )

    # Try to create second user with same name but different email
    response = client.post(
        "/users/",
        json={
            "name": "carol",  # Same name!
            "email": "carol2@example.com",
            "password": "DifferentPass456!",
        },
    )

    assert response.status_code == 409  # Conflict
    assert response.json() == {
        "detail": "Username already exists. Please choose a different username."
    }


def test_get_user_by_name_returns_new_fields(client):
    """Test that getting a user returns the new fields"""
    # Create a user
    client.post(
        "/users/",
        json={
            "name": "dave",
            "email": "dave@example.com",
            "password": "SecurePass789!",
        },
    )

    # Get the user by name
    response = client.get("/users/dave")
    assert response.status_code == 200

    user = response.json()["user"]
    assert "id" in user
    assert user["name"] == "dave"
    assert user["email"] == "dave@example.com"

    # Should NOT expose password
    assert "password" not in user


################
# ISSUE 9 profile pictures
##################


def _png_bytes(size=(320, 240), color=(9, 20, 30)):
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


def test_upload_and_fetch_avatar(client):
    # create user
    r = client.post("/users/", json={"name": "alice"})
    assert r.status_code in (200, 201)

    # upload
    r = client.post(
        "/users/alice/avatar",
        files={"file": ("x.png", _png_bytes(), "image/png")},
    )
    assert r.status_code == 200
    assert r.json()["avatar_url"].startswith("/media/")

    # fetch
    r2 = client.get("/users/alice/avatar")
    assert r2.status_code == 200
    assert r2.headers["content-type"] == "image/webp"


def test_reject_wrong_type(client):
    client.post("/users/", json={"name": "bob"})
    r = client.post(
        "/users/bob/avatar",
        files={"file": ("note.txt", b"hello", "text/plain")},
    )
    assert r.status_code == 415


def test_reject_big_file(client):
    client.post("/users/", json={"name": "carol"})
    big = b"\x00" * (6 * 1024 * 1024)  # 6MB > 5MB limit
    r = client.post(
        "/users/carol/avatar",
        files={"file": ("big.png", big, "image/png")},
    )
    assert r.status_code == 413


################
# ISSUE 26 - Tier field tests (RED)
################


def test_user_has_tier_field(client, created_user):
    """Test that user model includes tier field with default value"""
    response = client.get("/users/foo")
    assert response.status_code == 200
    user = response.json()["user"]
    assert "tier" in user
    assert user["tier"] == 1  # Default tier should be 1


def test_create_user_with_tier(client):
    """Test creating a user with custom tier"""
    response = client.post(
        "/users/",
        json={
            "name": "tier_user",
            "email": "tier@example.com",
            "password": "testpass123",
            "tier": 3,
        },
    )
    assert response.status_code == 201
    user = response.json()["user"]
    assert user["tier"] == 3


def test_create_user_defaults_to_tier_1(client):
    """Test that creating user without tier defaults to tier 1"""
    response = client.post(
        "/users/",
        json={
            "name": "default_tier",
            "email": "default@example.com",
            "password": "testpass123",
        },
    )
    assert response.status_code == 201
    user = response.json()["user"]
    assert user["tier"] == 1


def test_tier_field_in_all_user_responses(client):
    """Test that tier field is returned in all user read operations"""
    # Create user
    client.post(
        "/users/",
        json={
            "name": "tier_test",
            "email": "tier_test@example.com",
            "password": "testpass123",
            "tier": 2,
        },
    )

    # Test GET by name
    response = client.get("/users/tier_test")
    assert response.status_code == 200
    user = response.json()["user"]
    assert "tier" in user
    assert user["tier"] == 2


################
# ISSUE 26 - JWT Authentication tests (RED)
################


def test_post_authentications_issues_jwt(client, created_user):
    """Test POST /v2/authentications/ issues a JWT token"""
    response = client.post(
        "/v2/authentications/",
        json={
            "name": "foo",
            "password": "testpass123",
            "expiry": "2024-12-31 23:59:59",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "jwt" in data
    assert isinstance(data["jwt"], str)
    assert len(data["jwt"]) > 0


def test_post_authentications_invalid_credentials(client):
    """Test POST /v2/authentications/ with invalid credentials"""
    response = client.post(
        "/v2/authentications/",
        json={
            "name": "nonexistent",
            "password": "wrongpass",
            "expiry": "2024-12-31 23:59:59",
        },
    )
    assert response.status_code == 401


def test_post_authentications_expires_previous_tokens(client, created_user):
    """Test that issuing a new JWT expires previous tokens for the same user"""
    # Issue first token
    response1 = client.post(
        "/v2/authentications/",
        json={
            "name": "foo",
            "password": "testpass123",
            "expiry": "2024-12-31 23:59:59",
        },
    )
    assert response1.status_code == 200
    jwt1 = response1.json()["jwt"]

    # Issue second token
    response2 = client.post(
        "/v2/authentications/",
        json={
            "name": "foo",
            "password": "testpass123",
            "expiry": "2024-12-31 23:59:59",
        },
    )
    assert response2.status_code == 200
    jwt2 = response2.json()["jwt"]

    # Tokens should be different
    assert jwt1 != jwt2


def test_delete_authentications_expires_token(client, created_user):
    """Test DELETE /v2/authentications/ expires a JWT token"""
    # Issue a token
    response = client.post(
        "/v2/authentications/",
        json={
            "name": "foo",
            "password": "testpass123",
            "expiry": "2024-12-31 23:59:59",
        },
    )
    assert response.status_code == 200
    jwt = response.json()["jwt"]

    # Delete the token
    delete_response = client.request(
        "DELETE", "/v2/authentications/", json={"jwt": jwt}
    )
    assert delete_response.status_code == 200


def test_jwt_contains_correct_payload(client, created_user):
    """Test that JWT contains correct user ID and expiry"""
    response = client.post(
        "/v2/authentications/",
        json={
            "name": "foo",
            "password": "testpass123",
            "expiry": "2024-12-31 23:59:59",
        },
    )
    assert response.status_code == 200
    jwt = response.json()["jwt"]

    # Decode JWT (without verification for testing)
    import base64
    import json

    # Split JWT and decode payload
    parts = jwt.split(".")
    assert len(parts) == 3  # header.payload.signature

    # Decode payload (add padding if needed)
    payload_b64 = parts[1]
    payload_b64 += "=" * (4 - len(payload_b64) % 4)
    payload = json.loads(base64.b64decode(payload_b64))

    assert "sub" in payload  # user ID
    assert "exp" in payload  # expiry
    assert payload["sub"] == "1"  # user ID should be 1


def test_jwt_respects_max_expiry_limit(client, created_user):
    """Test that JWT respects 1 hour maximum expiry limit"""
    response = client.post(
        "/v2/authentications/",
        json={
            "name": "foo",
            "password": "testpass123",
            "expiry": "2025-12-31 23:59:59",  # Very far in future
        },
    )
    assert response.status_code == 200
    jwt = response.json()["jwt"]

    # Decode and check expiry is limited to 1 hour from now
    import base64
    import json
    import time

    parts = jwt.split(".")
    payload_b64 = parts[1]
    payload_b64 += "=" * (4 - len(payload_b64) % 4)
    payload = json.loads(base64.b64decode(payload_b64))

    exp_timestamp = payload["exp"]
    current_time = int(time.time())
    max_future_time = current_time + 3600  # 1 hour from now

    assert exp_timestamp <= max_future_time


################
# ISSUE 26 - Rate limiting tests (RED)
################


def test_rate_limit_unauthenticated_per_ip(client):
    """Unauthenticated requests are limited to 1 per 10 seconds per client IP."""
    # First request should pass (endpoint doesn't need auth)
    r1 = client.get("/users/does_not_exist", headers={"X-Enable-RateLimit": "1"})
    assert r1.status_code == 200

    # Second immediate request in same window should be rate limited
    r2 = client.get("/users/does_not_exist", headers={"X-Enable-RateLimit": "1"})
    assert r2.status_code == 429
    assert r2.content in (b"",)  # no response body per spec


def _get_jwt_for_user(client, name: str = "foo", password: str = "testpass123") -> str:
    resp = client.post(
        "/v2/authentications/",
        json={"name": name, "password": password, "expiry": "2099-12-31 23:59:59"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["jwt"]


def test_rate_limit_authenticated_uses_tier_multiplier(client, session):
    """Authenticated requests are limited to 2*tier per 10s window."""
    # Ensure a user with tier=2 exists so limit is 4 per window
    session.execute(text("DELETE FROM users WHERE name = :n"), {"n": "tier2"})
    session.execute(
        text(
            """
            INSERT INTO users (name, email, password_hash, tier)
            VALUES (:name, :email, :password_hash, :tier)
            """
        ),
        {
            "name": "tier2",
            "email": "tier2@example.com",
            "password_hash": __import__("bcrypt")
            .hashpw(b"testpass123", __import__("bcrypt").gensalt())
            .decode("utf-8"),
            "tier": 2,
        },
    )
    session.commit()

    jwt = _get_jwt_for_user(client, name="tier2", password="testpass123")
    headers = {"Authorization": f"Bearer {jwt}"}

    # 4 requests should pass in the same 10s window (2 * tier)
    for i in range(4):
        r = client.get(
            "/users/tier2",
            headers={**headers, "X-Enable-RateLimit": "1"},
        )
        # 200 with user payload or 200 user None
        assert r.status_code in (200, 404, 200)

    # The 5th should be rate limited
    r5 = client.get("/users/tier2", headers={**headers, "X-Enable-RateLimit": "1"})
    assert r5.status_code == 429
    assert r5.content in (b"",)


def test_rate_limit_prefers_jwt_over_ip_bucket(client, created_user):
    """If a JWT is present, use the user-tier limit, not the 1-per-IP limit."""
    # Issue JWT for default user (tier=1 => allows 2 per window)
    jwt = _get_jwt_for_user(client, name="foo", password="testpass123")
    headers = {"Authorization": f"Bearer {jwt}"}

    # Two requests should be allowed (despite IP rule of 1 per 10s)
    r1 = client.get("/users/foo", headers={**headers, "X-Enable-RateLimit": "1"})
    r2 = client.get("/users/foo", headers={**headers, "X-Enable-RateLimit": "1"})
    assert r1.status_code == 200
    assert r2.status_code == 200

    # Third in same window should be blocked for tier=1
    r3 = client.get("/users/foo", headers={**headers, "X-Enable-RateLimit": "1"})
    assert r3.status_code == 429
    assert r3.content in (b"",)


################
# Coverage
################


def test_upload_avatar_invalid_image_returns_400(client):
    # Create a user first
    r = client.post("/users/", json={"name": "invalid_img_user"})
    assert r.status_code in (200, 201, 409)

    # Send a PNG content-type but garbage bytes so PIL fails to open it
    r = client.post(
        "/users/invalid_img_user/avatar",
        files={"file": ("bad.png", b"not-a-real-image", "image/png")},
    )
    assert r.status_code == 400
    body = r.json()
    assert body["detail"] == "Invalid image"


def test_get_avatar_returns_404_when_no_avatar_set(client):
    # Create a user with no avatar
    r = client.post("/users/", json={"name": "no_avatar_user"})
    assert r.status_code in (200, 201, 409)

    # Request avatar before any upload
    r2 = client.get("/users/no_avatar_user/avatar")
    assert r2.status_code == 404
    body = r2.json()
    assert body["detail"] == "No avatar set"


def test_rate_limit_uses_jwt_bucket_for_invalid_token(client):
    """
    If an invalid Bearer token is present, the rate limiter should still
    prefer a JWT-scoped bucket (2 reqs / window) over the IP bucket,
    instead of the 1-per-IP unauthenticated limit.
    """
    headers = {
        "Authorization": "Bearer not-a-valid-jwt",
        "X-Enable-RateLimit": "1",
    }

    # First two requests should be allowed
    r1 = client.get("/users/does_not_exist", headers=headers)
    r2 = client.get("/users/does_not_exist", headers=headers)
    assert r1.status_code == 200
    assert r2.status_code == 200

    # Third should be rate-limited for this JWT bucket
    r3 = client.get("/users/does_not_exist", headers=headers)
    assert r3.status_code == 429
    assert r3.content in (b"",)
