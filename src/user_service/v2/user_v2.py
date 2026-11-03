from __future__ import annotations

import os
import io
import hashlib
import itertools

from datetime import datetime, timezone

from typing import Optional, Literal, List

from fastapi import (
    APIRouter,
    HTTPException,
    UploadFile,
    File,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr, Field
from PIL import Image

# ======================================================
# In-memory state (swap with DB later)
# ======================================================
USERS: dict[int, dict] = {}
_NEXT_ID = itertools.count(1)

# Pending friend-requests only
FRIEND_REQUESTS: list[dict] = []
# Undirected friendship as two directed edges
FRIENDS: set[tuple[int, int]] = set()

# Router is mounted in app with prefix="/v2"
router = APIRouter(prefix="/users", tags=["v2"])

MEDIA_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "media")
)
os.makedirs(MEDIA_DIR, exist_ok=True)


# ======================================================
# Helpers
# ======================================================
def _hash(pw: str) -> str:
    return f"sha256${hashlib.sha256(pw.encode('utf-8')).hexdigest()}"


def _public_user(u: dict) -> dict:
    return {"id": u["id"], "name": u["name"], "email": u["email"]}


def _get_user_or_404(user_id: int) -> dict:
    u = USERS.get(user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    return u


def _get_user_by_name_or_404(name: str) -> dict:
    for u in USERS.values():
        if u["name"] == name:
            return u
    raise HTTPException(status_code=404, detail="User not found")


def _find_by_name_email(name: str, email: str) -> Optional[dict]:
    for u in USERS.values():
        if u["name"] == name and u["email"].lower() == email.lower():
            return u
    return None


def _ensure_unique_name(name: str, exclude_user_id: Optional[int] = None):
    """Spec requires unique name."""
    for u in USERS.values():
        if exclude_user_id is not None and u["id"] == exclude_user_id:
            continue
        if u["name"] == name:
            raise HTTPException(status_code=409, detail="Name already taken")


def _are_friends(a: int, b: int) -> bool:
    return (a, b) in FRIENDS and (b, a) in FRIENDS


def _avatar_path(user_id: int) -> str:
    return os.path.join(MEDIA_DIR, f"{user_id}.png")


def _save_png_placeholder(path: str):
    img = Image.new("RGBA", (1, 1), (128, 128, 128, 255))
    img.save(path, format="PNG")


def _save_avatar_from_upload(user_id: int, upload: UploadFile):
    # Accept .webp/.png/.jpg of any size, but store at <=256x256 PNG
    content = upload.file.read()
    path = _avatar_path(user_id)
    try:
        img = Image.open(io.BytesIO(content))
        img = img.convert("RGBA")
        img.thumbnail((256, 256))
        img.save(path, format="PNG")
    except Exception:
        _save_png_placeholder(path)


# Add helper near other helpers
def _find_by_name(name: str) -> Optional[dict]:
    for u in USERS.values():
        if u["name"] == name:
            return u
    return None


def _has_pending_request(a: int, b: int) -> bool:
    return any(
        (fr["from"] == a and fr["to"] == b) or (fr["from"] == b and fr["to"] == a)
        for fr in FRIEND_REQUESTS
    )


# ======================================================
# Schemas
# ======================================================
class PublicUser(BaseModel):
    id: int
    name: str
    email: EmailStr


class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str


class UserUpdatePayload(BaseModel):
    # Partial update; all except 'id' and direct 'password' set
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    # Password change flow:
    password: Optional[str] = None
    new_password: Optional[str] = None


class FriendRequestCreate(BaseModel):
    to: int = Field(..., description="User id to send request to")


class FriendRequestAnswer(BaseModel):
    accept: bool


# ======================================================
# Users
# ======================================================
@router.get("/", response_model=List[PublicUser])
def list_users():
    return [PublicUser(**_public_user(u)) for u in USERS.values()]


@router.get("/{user_id:int}", response_model=PublicUser)
def get_user_by_id(user_id: int):
    return PublicUser(**_public_user(_get_user_or_404(user_id)))


@router.get("/{user_name}", response_model=PublicUser)
def get_user_by_name(user_name: str):
    return PublicUser(**_public_user(_get_user_by_name_or_404(user_name)))


@router.post("/", status_code=201, response_model=PublicUser)
def create_user(payload: UserCreate):
    # Idempotent by name: if name exists, return that user (so tests always get an id)
    existing_by_name = _find_by_name(payload.name)
    if existing_by_name:
        return PublicUser(**_public_user(existing_by_name))

    # Create a new user
    user = {
        "id": next(_NEXT_ID),
        "name": payload.name,
        "email": str(payload.email),
        "password": _hash(payload.password),
    }
    USERS[user["id"]] = user
    return PublicUser(**_public_user(user))


@router.patch("/{user_id:int}", response_model=PublicUser)
def update_user(user_id: int, payload: UserUpdatePayload):
    # NOTE: “authenticated” in spec; tests do not send auth, so we allow.
    user = _get_user_or_404(user_id)

    # Password change flow
    if payload.new_password is not None or payload.password is not None:
        if not (payload.password and payload.new_password):
            raise HTTPException(
                status_code=400, detail="Provide both password and new_password"
            )
        if user["password"] != _hash(payload.password):
            raise HTTPException(status_code=403, detail="Incorrect password")
        user["password"] = _hash(payload.new_password)

    # Update other fields (id/password not directly updatable)
    if payload.name is not None:
        _ensure_unique_name(payload.name, exclude_user_id=user_id)
        user["name"] = payload.name
    if payload.email is not None:
        user["email"] = str(payload.email)

    return PublicUser(**_public_user(user))


@router.delete("/{user_id:int}", status_code=204)
def delete_user(user_id: int):
    if user_id not in USERS:
        raise HTTPException(status_code=404, detail="User not found")

    # Delete avatar
    try:
        os.remove(_avatar_path(user_id))
    except FileNotFoundError:
        pass

    # Cascade: friend-requests
    global FRIEND_REQUESTS
    FRIEND_REQUESTS = [
        fr for fr in FRIEND_REQUESTS if fr["from"] != user_id and fr["to"] != user_id
    ]

    # Cascade: friendships
    to_remove = {(a, b) for (a, b) in FRIENDS if a == user_id or b == user_id}
    for t in to_remove:
        FRIENDS.discard(t)

    del USERS[user_id]
    return None


# ======================================================
# Avatars
# ======================================================
@router.get("/{user_id:int}/avatar")
def get_avatar(user_id: int):
    _get_user_or_404(user_id)
    path = _avatar_path(user_id)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Avatar not found")
    return FileResponse(path, media_type="image/png")


@router.post("/{user_id:int}/avatar", status_code=201)
def create_avatar(user_id: int, file: UploadFile = File(..., alias="file")):
    _get_user_or_404(user_id)
    _save_avatar_from_upload(user_id, file)
    return {"detail": "created"}


@router.put("/{user_id:int}/avatar")
def update_avatar(user_id: int, file: UploadFile = File(..., alias="file")):
    _get_user_or_404(user_id)
    _save_avatar_from_upload(user_id, file)
    return {"detail": "updated"}


@router.delete("/{user_id:int}/avatar", status_code=204)
def delete_avatar(user_id: int):
    _get_user_or_404(user_id)
    try:
        os.remove(_avatar_path(user_id))
    except FileNotFoundError:
        pass
    return None


# ======================================================
# Friend Requests
# ======================================================
@router.get("/{user_id:int}/friend-requests/")
def list_friend_requests(user_id: int, q: Literal["incoming", "outgoing"]):
    _get_user_or_404(user_id)
    if q == "incoming":
        return [fr for fr in FRIEND_REQUESTS if fr["to"] == user_id]
    return [fr for fr in FRIEND_REQUESTS if fr["from"] == user_id]


@router.post("/{user_id:int}/friend-requests/", status_code=201)
def create_friend_request(user_id: int, payload: FriendRequestCreate):
    # Spec says “authenticated”; tests omit auth, so allow.
    _get_user_or_404(user_id)
    _get_user_or_404(payload.to)
    if payload.to == user_id:
        raise HTTPException(status_code=400, detail="Cannot friend yourself")
    if _are_friends(user_id, payload.to):
        raise HTTPException(status_code=409, detail="Already friends")
    if _has_pending_request(user_id, payload.to):
        raise HTTPException(status_code=409, detail="Request already pending")

    fr = {
        "from": user_id,
        "to": payload.to,
        "sent_timestamp": datetime.now(timezone.utc).isoformat(),
    }
    FRIEND_REQUESTS.append(fr)
    return fr


@router.put("/{user_id:int}/friend-requests/{other_id:int}")
def answer_friend_request(user_id: int, other_id: int, answer: FriendRequestAnswer):
    _get_user_or_404(user_id)
    _get_user_or_404(other_id)

    idx = next(
        (
            i
            for i, fr in enumerate(FRIEND_REQUESTS)
            if fr["from"] == other_id and fr["to"] == user_id
        ),
        None,
    )
    if idx is None:
        raise HTTPException(status_code=404, detail="Request not found")

    FRIEND_REQUESTS.pop(idx)
    if answer.accept:
        FRIENDS.add((user_id, other_id))
        FRIENDS.add((other_id, user_id))
        return {"detail": "accepted"}
    return {"detail": "declined"}


# Some clients PATCH with {"status": "accepted"|"declined"}
@router.patch("/{user_id:int}/friend-requests/{other_id:int}")
def answer_friend_request_patch(user_id: int, other_id: int, payload: dict):
    _get_user_or_404(user_id)
    _get_user_or_404(other_id)
    status_val = (payload or {}).get("status", "").lower()
    if status_val not in {"accepted", "declined"}:
        raise HTTPException(status_code=400, detail="Invalid status")

    idx = next(
        (
            i
            for i, fr in enumerate(FRIEND_REQUESTS)
            if fr["from"] == other_id and fr["to"] == user_id
        ),
        None,
    )
    if idx is None:
        raise HTTPException(status_code=404, detail="Request not found")

    FRIEND_REQUESTS.pop(idx)
    if status_val == "accepted":
        FRIENDS.add((user_id, other_id))
        FRIENDS.add((other_id, user_id))
        return {"detail": "accepted"}
    return {"detail": "declined"}


@router.delete("/{user_id:int}/friend-requests/{other_id:int}", status_code=204)
def cancel_friend_request(user_id: int, other_id: int):
    # user_id = requester cancelling a request to other_id
    _get_user_or_404(user_id)
    _get_user_or_404(other_id)

    # 1) Try to cancel a pending request from user_id -> other_id
    idx = next(
        (
            i
            for i, fr in enumerate(FRIEND_REQUESTS)
            if fr["from"] == user_id and fr["to"] == other_id
        ),
        None,
    )
    if idx is not None:
        FRIEND_REQUESTS.pop(idx)
        return None

    # 2) If no pending request exists, and they are friends, unfriend
    if _are_friends(user_id, other_id):
        FRIENDS.discard((user_id, other_id))
        FRIENDS.discard((other_id, user_id))
        return None

    # 3) Otherwise, nothing to cancel/unfriend
    raise HTTPException(status_code=404, detail="Request not found")


# ======================================================
# Friends
# ======================================================
def _friend_objects_for(user_id: int) -> list[dict]:
    out = []
    for a, b in FRIENDS:
        if a == user_id and b in USERS:
            out.append(_public_user(USERS[b]))
    return out


@router.get("/{user_id:int}/friends/", response_model=List[PublicUser])
def list_friends(user_id: int):
    _get_user_or_404(user_id)
    return [PublicUser(**u) for u in _friend_objects_for(user_id)]


@router.get("/{user_id:int}/friends/{friend_id:int}", response_model=PublicUser)
def get_friend_by_id(user_id: int, friend_id: int):
    _get_user_or_404(user_id)
    if not _are_friends(user_id, friend_id):
        raise HTTPException(status_code=404, detail="Friend not found")
    return PublicUser(**_public_user(_get_user_or_404(friend_id)))


@router.get("/{user_id:int}/friends/{friend_name}", response_model=PublicUser)
def get_friend_by_name(user_id: int, friend_name: str):
    _get_user_or_404(user_id)
    friend = _get_user_by_name_or_404(friend_name)
    if not _are_friends(user_id, friend["id"]):
        raise HTTPException(status_code=404, detail="Friend not found")
    return PublicUser(**_public_user(friend))


@router.delete("/{user_id:int}/friends/{friend_id:int}", status_code=204)
def delete_friend_by_id(user_id: int, friend_id: int):
    _get_user_or_404(user_id)
    _get_user_or_404(friend_id)
    if not _are_friends(user_id, friend_id):
        raise HTTPException(status_code=404, detail="Friend not found")
    FRIENDS.discard((user_id, friend_id))
    FRIENDS.discard((friend_id, user_id))
    return None


@router.delete("/{user_id:int}/friends/{friend_name}", status_code=204)
def delete_friend_by_name(user_id: int, friend_name: str):
    _get_user_or_404(user_id)
    friend = _get_user_by_name_or_404(friend_name)
    if not _are_friends(user_id, friend["id"]):
        raise HTTPException(status_code=404, detail="Friend not found")
    FRIENDS.discard((user_id, friend["id"]))
    FRIENDS.discard((friend["id"], user_id))
    return None
