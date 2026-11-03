import os
import itertools

import pytest
from fastapi.testclient import TestClient

from user_service.v1.api import app
from user_service.v2 import analytics as analytics_module
from user_service.v2 import events as ev

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_events_and_ttl():
    """Reset in-memory events and TTL before each test."""
    ev._EVENTS.clear()
    ev._NEXT_EID = itertools.count(1)

    old = os.environ.get("AUTH_TTL_SECONDS")
    os.environ["AUTH_TTL_SECONDS"] = "60"
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("AUTH_TTL_SECONDS", None)
        else:
            os.environ["AUTH_TTL_SECONDS"] = old


def test_ttl_seconds_falls_back_to_default_on_invalid_env(monkeypatch):
    # Bad value should trigger the except path and use the default of 900.
    monkeypatch.setenv("AUTH_TTL_SECONDS", "not-an-int")
    assert analytics_module._ttl_seconds() == 900


def test_analytics_since_in_future_returns_400():
    # "since" later than today should raise HTTP 400 via the guard in get_analytics.
    res = client.get("/v2/analytics", params={"since": "9999-01-01"})
    assert res.status_code == 400


def test_analytics_counts_users_active_at_end_of_day():
    # With TTL=60 and an event at 23:59:30, the user should be active at day end.
    day = "2025-10-15"
    client.post(
        "/v2/events/",
        json={
            "when": f"{day} 23:59:30",
            "source": "http://x",
            "type": "view",
            "payload": {},
            "user": "u-end",
        },
    )

    res = client.get("/v2/analytics", params={"on": day})
    assert res.status_code == 200
    data = res.json()
    assert data["active_users"]["current"] == 1


def test_analytics_max_active_ignores_anonymous_events():
    # Anonymous events (user=None) should not contribute to max concurrent users.
    day = "2025-10-20"

    client.post(
        "/v2/events/",
        json={
            "when": f"{day} 10:00:00",
            "source": "http://x",
            "type": "view",
            "payload": {},
            "user": "A",
        },
    )
    client.post(
        "/v2/events/",
        json={
            "when": f"{day} 10:00:10",
            "source": "http://x",
            "type": "view",
            "payload": {},
            "user": None,
        },
    )
    client.post(
        "/v2/events/",
        json={
            "when": f"{day} 10:00:20",
            "source": "http://x",
            "type": "view",
            "payload": {},
            "user": "B",
        },
    )

    res = client.get("/v2/analytics", params={"on": day})
    assert res.status_code == 200
    stats = res.json()["active_users"]

    # Only the two non-anonymous users should be counted.
    assert stats["max"] == 2


def test_ttl_seconds_handles_bad_env_value(monkeypatch):
    # Force AUTH_TTL_SECONDS to something non-integer so we hit the except branch
    monkeypatch.setenv("AUTH_TTL_SECONDS", "not-an-int")

    from user_service.v2 import analytics as analytics_module

    ttl = analytics_module._ttl_seconds()
    # We don't depend on the exact fallback value, just that it's a sane int
    assert isinstance(ttl, int)
    assert ttl > 0
