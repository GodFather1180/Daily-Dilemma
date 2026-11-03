from __future__ import annotations
from typing import Optional, List, Tuple, Dict, Any
from datetime import datetime, timedelta, date, timezone
import os

from fastapi import APIRouter, HTTPException, Query
from .events import _EVENTS  # reuse in-memory events

router = APIRouter(prefix="/analytics", tags=["v2"])


def _ttl_seconds() -> int:
    # Read at call-time so tests / env changes don’t require re-import
    try:
        return int(os.getenv("AUTH_TTL_SECONDS", "900"))
    except Exception:
        return 900


def _day_bounds(d: date) -> tuple[datetime, datetime]:
    start = datetime(d.year, d.month, d.day, 0, 0, 0)
    end = start + timedelta(days=1) - timedelta(seconds=1)
    return start, end


def _sessions_for_day(d: date) -> List[Tuple[datetime, datetime]]:
    start, end = _day_bounds(d)
    ttl = _ttl_seconds()

    rows = [
        (ev["user"], ev["when"])
        for ev in _EVENTS
        if ev["user"] is not None and start <= ev["when"] <= end
    ]
    rows.sort(key=lambda x: (x[0], x[1]))

    sessions: List[Tuple[datetime, datetime]] = []
    cur_user: Optional[str] = None
    cur_start: Optional[datetime] = None
    last_when: Optional[datetime] = None

    for u, w in rows:
        if u != cur_user:
            if cur_user is not None and cur_start and last_when:
                sA = max(cur_start, start)
                sB = min(last_when + timedelta(seconds=ttl), end)
                if sB > sA:
                    sessions.append((sA, sB))
            cur_user, cur_start, last_when = u, w, w
            continue

        # same user
        assert last_when is not None
        if (w - last_when).total_seconds() <= ttl:
            last_when = w
        else:
            sA = max(cur_start, start)
            sB = min(last_when + timedelta(seconds=ttl), end)
            if sB > sA:
                sessions.append((sA, sB))
            cur_start, last_when = w, w

    if cur_user is not None and cur_start and last_when:
        sA = max(cur_start, start)
        sB = min(last_when + timedelta(seconds=ttl), end)
        if sB > sA:
            sessions.append((sA, sB))

    return sessions


def _length_stats(durs: List[float]) -> Dict[str, float]:
    if not durs:
        return {"min": 0.0, "max": 0.0, "mean": 0.0, "median": 0.0, "p95": 0.0}
    xs = sorted(durs)
    n = len(xs)

    def pct(p: float) -> float:
        i = max(0, min(n - 1, int(round(p * (n - 1)))))
        return xs[i]

    return {
        "min": xs[0],
        "max": xs[-1],
        "mean": sum(xs) / n,
        "median": pct(0.5),
        "p95": pct(0.95),
    }


def _active_at_end_of_day(d: date) -> int:
    start, end = _day_bounds(d)
    ttl = _ttl_seconds()
    latest: dict[str, datetime] = {}
    for ev in _EVENTS:
        u = ev["user"]
        if u is None or ev["when"] > end:
            continue
        if u not in latest or ev["when"] > latest[u]:
            latest[u] = ev["when"]
    count = 0
    for _, w in latest.items():
        if start <= w <= end and (end - w).total_seconds() <= ttl:
            count += 1
    return count


def _daily_max_active(d: date) -> int:
    start, end = _day_bounds(d)
    ttl = _ttl_seconds()
    points: list[tuple[datetime, int]] = []
    for ev in _EVENTS:
        if ev["user"] is None:
            continue
        if not (start <= ev["when"] <= end):
            continue
        a = ev["when"]
        b = min(ev["when"] + timedelta(seconds=ttl), end)
        points.append((a, +1))
        points.append((b, -1))
    points.sort(key=lambda p: (p[0], -p[1]))
    cur = m = 0
    for _, dlt in points:
        cur += dlt
        m = max(m, cur)
    return m


def _stats_for_day(d: date) -> Dict[str, Any]:
    sessions = _sessions_for_day(d)
    durs = [(b - a).total_seconds() for (a, b) in sessions]
    return {
        "session_length": _length_stats(durs),
        "active_users": {
            "current": _active_at_end_of_day(d),
            "max": _daily_max_active(d),
        },
    }


@router.get("/")
def analytics(
    on: Optional[date] = Query(default=None),
    since: Optional[date] = Query(default=None),
):
    today = datetime.now(timezone.utc).date()
    if since:
        if since > today:
            raise HTTPException(
                status_code=400, detail="'since' cannot be in the future"
            )
        days = [since + timedelta(days=i) for i in range((today - since).days + 1)]
        per = [_stats_for_day(d) for d in days]

        def avg(xs):
            return sum(xs) / len(xs) if xs else 0.0

        return {
            "session_length": {
                k: avg([s["session_length"][k] for s in per])
                for k in ("min", "max", "mean", "median", "p95")
            },
            "active_users": {
                "current": avg([s["active_users"]["current"] for s in per]),
                "max": avg([s["active_users"]["max"] for s in per]),
            },
        }
    if on:
        return _stats_for_day(on)
    return _stats_for_day(today)
