from __future__ import annotations
from typing import Optional, List, Dict, Any
from datetime import datetime
import itertools

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, AnyUrl

router = APIRouter(prefix="/events", tags=["v2"])

# In-memory store (keeps TDD super simple for now)
_EVENTS: list[dict] = []
_NEXT_EID = itertools.count(1)


class EventIn(BaseModel):
    when: datetime
    source: AnyUrl | str
    type: str = Field(min_length=1)
    payload: Dict[str, Any]
    user: Optional[str] = None  # optional by spec


class EventOut(EventIn):
    id: int
    created_at: datetime


@router.post("/", response_model=EventOut, status_code=201)
def create_event(e: EventIn):
    eid = next(_NEXT_EID)
    rec = {
        "id": eid,
        "when": e.when,
        "source": str(e.source),
        "type": e.type,
        "payload": e.payload,
        "user": e.user,  # can be None
        "created_at": datetime.now(),  # naive is fine for now
    }
    _EVENTS.append(rec)
    return rec


@router.get("/", response_model=List[EventOut])
def query_events(
    type: Optional[str] = None,
    source: Optional[str] = None,
    user: Optional[str] = None,
    before: Optional[str] = Query(default=None),
    after: Optional[str] = Query(default=None),
):
    # simple parser for "YYYY-MM-DD HH:MM:SS" or ISO
    def _parse(ts: Optional[str]) -> Optional[datetime]:
        if not ts:
            return None
        try:
            if "T" not in ts and " " in ts:
                ts = ts.replace(" ", "T")
            return datetime.fromisoformat(ts)
        except Exception:
            raise HTTPException(status_code=400, detail=f"Invalid datetime: {ts}")

    aft = _parse(after)
    bef = _parse(before)

    out: list[dict] = []
    for ev in _EVENTS:
        if type and ev["type"] != type:
            continue
        if source and ev["source"] != source:
            continue
        if user is not None and ev["user"] != user:
            continue
        if aft and ev["when"] < aft:
            continue
        if bef and ev["when"] > bef:
            continue
        out.append(ev)

    out.sort(key=lambda r: (r["when"], r["id"]))
    return out
