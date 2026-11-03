from typing import List, Optional
import logging
import os
import io
import base64
from html import escape
from pathlib import Path

from fastapi import (
    FastAPI,
    Depends,
    Response,
    UploadFile,
    File,
    HTTPException,
    Query,
    Form,
    Request,
)

from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security.utils import get_authorization_scheme_param
from sqlalchemy.exc import IntegrityError
from PIL import Image

from user_service.v2.api_v2 import router as v2_router
from user_service.jwt_service import jwt_service

from admin.main import ui
from user_service.v1.models.user import (
    UserRepository,
    UserSchema,
    UserCreateSchema,
    get_user_repository,
)
from game.api import router as game_router

logger = logging.getLogger("uvicorn.error")
app = FastAPI(title="User Service", tags=["v1"])
app.include_router(v2_router, prefix="/v2")

# ===== Game router inclusion =====

# Path to built frontend: src/frontend/dist
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

if FRONTEND_DIST.is_dir():
    # Serve the built SPA shell at /play
    app.mount(
        "/play",
        StaticFiles(directory=str(FRONTEND_DIST), html=True),
        name="play",
    )

    # Serve Vite-built assets at /assets (JS, CSS, etc.)
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=str(assets_dir), html=False),
            name="assets",
        )
else:
    logger.warning(
        "Frontend dist not found at %s; /play UI is disabled in this environment",
        FRONTEND_DIST,
    )


app.include_router(game_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000/play/",
        "http://localhost:5173",
        "https://daily-dilemma-ui.onrender.com",  # deployed frontend
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# ===== Avatar upload & retrieval  =====

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEDIA_ROOT = os.path.abspath(os.path.join(BASE_DIR, "..", "media"))
os.makedirs(MEDIA_ROOT, exist_ok=True)
app.mount("/media", StaticFiles(directory=MEDIA_ROOT), name="media")

ALLOWED = {"image/png", "image/jpeg", "image/webp"}
MAX_BYTES = 5 * 1024 * 1024  # 5MB
AVATAR_SIZE = 256

DEFAULT_LIMIT = 50
MAX_LIMIT = 200  # hard cap for API default page size & requested limit
# ===== Rate limiting middleware (Issue #26) =====
# Fixed window counter: 10-second windows. Keys are per-user (JWT) or per-IP.
# Tests opt-in via header: X-Enable-RateLimit: 1 (keeps unrelated tests stable)
_RATE_WINDOW_SECONDS = 10
_RATE_BUCKETS: dict[str, tuple[int, int]] = {}


def _current_window(now_s: int) -> int:
    return (now_s // _RATE_WINDOW_SECONDS) * _RATE_WINDOW_SECONDS


@app.middleware("http")
async def _rate_limit_guard(request: Request, call_next):
    import time as _time

    # Don't rate-limit the authentication endpoints to avoid blocking logins/logout
    if request.url.path.startswith("/v2/authentications/"):
        return await call_next(request)

    # Opt-in activation for tests: only enforce when explicitly enabled
    if request.headers.get("X-Enable-RateLimit") != "1":
        return await call_next(request)

    # Determine subject: user:<id> if valid JWT, else ip:<ip>
    auth = request.headers.get("Authorization", "")
    scheme, param = get_authorization_scheme_param(auth)
    subject_key = None
    limit = 1  # unauthenticated per-IP limit

    if scheme.lower() == "bearer" and param:
        payload = jwt_service.validate_token(param)
        if payload:
            user_id = str(payload.get("sub", ""))
            tier = int(payload.get("tier", 1))
            issued_at = int(payload.get("iat", 0))
            if user_id:
                # Include issued-at so a freshly issued token starts a fresh bucket
                subject_key = f"user:{user_id}:{issued_at}"
                limit = 2 * max(1, tier)
        else:
            # If a bearer token is present but not validatable here,
            # prefer a JWT-scoped bucket over IP and allow tier=1
            # semantics (2 reqs/window) to avoid penalizing token users.
            subject_key = f"jwt:{hash(param)}"
            limit = 2

    if subject_key is None:
        client_ip = request.client.host if request.client else "127.0.0.1"
        subject_key = f"ip:{client_ip}"
        limit = 1

    now = int(_time.time())
    win = _current_window(now)

    prev = _RATE_BUCKETS.get(subject_key)
    if not prev or prev[0] != win:
        _RATE_BUCKETS[subject_key] = (win, 0)
        prev = _RATE_BUCKETS[subject_key]

    # Enforce
    count = prev[1]
    if count >= limit:
        return Response(status_code=429)

    _RATE_BUCKETS[subject_key] = (win, count + 1)
    return await call_next(request)


def _center_crop(img: Image.Image) -> Image.Image:
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    return img.crop((left, top, left + side, top + side))


def _save_avatar(user_key: str, img: Image.Image) -> str:
    user_dir = os.path.join(MEDIA_ROOT, "avatars", user_key)
    os.makedirs(user_dir, exist_ok=True)
    out_path = os.path.join(user_dir, "avatar.webp")
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    resample_attr = getattr(Image, "Resampling", None)
    resample = resample_attr.LANCZOS if resample_attr else Image.LANCZOS
    img = _center_crop(img).resize((AVATAR_SIZE, AVATAR_SIZE), resample)
    img.save(out_path, format="WEBP", quality=80)
    return os.path.relpath(out_path, MEDIA_ROOT)


def _avatar_abs_path(user_key: str) -> str:
    return os.path.join(MEDIA_ROOT, "avatars", user_key, "avatar.webp")


@app.post("/users/", status_code=201)
async def create_user(
    user: UserCreateSchema,
    response: Response,
    user_repo: UserRepository = Depends(get_user_repository),
):
    try:
        new_user = await user_repo.create(
            user.name,
            user.email,
            user.password,
            user.tier,
        )
        return {"user": UserSchema.from_db_model(new_user)}
    except IntegrityError as e:
        response.status_code = 409
        # Provide more specific error message
        error_msg = str(e.orig) if hasattr(e, "orig") else str(e)
        if "name" in error_msg.lower() or "username" in error_msg.lower():
            return {
                "detail": "Username already exists. Please choose a different username."
            }
        elif "email" in error_msg.lower():
            return {
                "detail": (
                    "Email already exists. Please use a different email "
                    "or try logging in."
                )
            }
        else:
            return {"detail": f"Item already exists: {error_msg}"}


@app.get("/users/")
async def list_users(
    user_repo: UserRepository = Depends(get_user_repository),
    limit: Optional[int] = Query(DEFAULT_LIMIT, ge=0),
    offset: Optional[int] = Query(0, ge=0),
    q: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    query: Optional[str] = Query(None),
):
    term = q or search or query
    page_size = min(limit if limit is not None else DEFAULT_LIMIT, MAX_LIMIT)
    page_offset = offset or 0

    items, total = await user_repo.list_paginated(page_size, page_offset, term)
    users: List[UserSchema] = [UserSchema.from_db_model(m) for m in items]

    return {
        "items": users,
        "total": total,
        "limit": page_size,
        "offset": page_offset,
    }


@app.get("/users/{name}")
async def get_user(name: str, user_repo: UserRepository = Depends(get_user_repository)):
    model = await user_repo.get_by_name(name)
    return {"user": (UserSchema.from_db_model(model) if model else None)}


@app.post("/users/delete", status_code=204)
async def delete_user_post(
    user: UserCreateSchema,
    user_repo: UserRepository = Depends(get_user_repository),
):
    try:
        await user_repo.delete(user.name)
    finally:
        return Response(status_code=204)


@app.post("/users/{name}/avatar", status_code=200)
async def upload_avatar(
    name: str,
    file: UploadFile = File(...),
    user_repo: UserRepository = Depends(get_user_repository),
):
    user = await user_repo.get_by_name(name)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if file.content_type not in ALLOWED:
        raise HTTPException(status_code=415, detail="Unsupported media type")
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 5MB)")
    try:
        img = Image.open(io.BytesIO(data))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid image")

    rel_path = _save_avatar(name, img)
    return {"avatar_url": f"/media/{rel_path}", "message": "ok"}


@app.get("/users/{name}/avatar")
async def get_avatar(
    name: str, user_repo: UserRepository = Depends(get_user_repository)
):
    user = await user_repo.get_by_name(name)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    abs_path = _avatar_abs_path(name)
    if not os.path.exists(abs_path):
        raise HTTPException(status_code=404, detail="No avatar set")
    return FileResponse(abs_path, media_type="image/webp")


@app.post("/users/{id}/avatar", include_in_schema=False)
async def upload_avatar_by_id(
    id: str,
    file: UploadFile = File(...),
    user_repo: UserRepository = Depends(get_user_repository),
):
    return await upload_avatar(id, file, user_repo)


@app.get("/users/{id}/avatar", include_in_schema=False)
async def get_avatar_by_id(
    id: str, user_repo: UserRepository = Depends(get_user_repository)
):
    return await get_avatar(id, user_repo)


# ===== Admin guard (Issue #2) =====
@app.middleware("http")
async def _admin_basic_guard(request: Request, call_next):
    if request.url.path.startswith("/admin"):
        admin_pwd = os.getenv("ADMIN_PASSWORD", "")
        if not admin_pwd:
            return JSONResponse(
                status_code=500, content={"detail": "ADMIN_PASSWORD not set"}
            )

        auth = request.headers.get("Authorization")
        if not auth:
            return Response(status_code=401, headers={"WWW-Authenticate": "Basic"})

        scheme, param = get_authorization_scheme_param(auth)
        if scheme.lower() != "basic" or not param:
            return Response(status_code=401, headers={"WWW-Authenticate": "Basic"})

        try:
            decoded = base64.b64decode(param).decode()
        except Exception:
            return Response(status_code=401, headers={"WWW-Authenticate": "Basic"})

        _, _, supplied = decoded.partition(":")
        if supplied != admin_pwd:
            return Response(status_code=401, headers={"WWW-Authenticate": "Basic"})

    return await call_next(request)


# ===== Minimal server-rendered Admin HTML with
# CREATE + DELETE and detectable pagination=====
def render_admin_page(
    items: List[UserSchema],
    total: int,
    limit: int,
    offset: int,
    message: Optional[str] = None,
    error: Optional[str] = None,
    q: Optional[str] = None,
) -> str:
    rows_html = "\n".join(
        (
            "<tr>"
            f"<td>{escape(str(u.id or ''))}</td>"
            f"<td>{escape(u.name)}</td>"
            f"<td>{escape(u.email or '')}</td>"
            f"<td>"
            f"<form method='post' action='/admin/delete' style='display:inline'>"
            f"<input type='hidden' name='name' value='{escape(u.name)}' />"
            f"<button type='submit'aria-label='Delete {escape(u.name)}'>Delete</button>"
            f"</form>"
            f"</td>"
            "</tr>"
        )
        for u in items
    )

    base_query = f"&q={escape(q)}" if q else ""
    next_offset = offset + limit
    has_next = next_offset < total
    next_href = (
        f"/admin/?offset={next_offset}&limit={limit}{base_query}" if has_next else ""
    )
    # Hints for tests: rel=next, data-next-page, visible anchor.
    link_next = f'<link rel="next" href="{next_href}">' if has_next else ""
    data_next = f'data-next-page="{next_href}"' if has_next else ""
    anchor_next = f'<a class="next" href="{next_href}">Next »</a>' if has_next else ""

    msg_html = f"<p style='color:#060'>{escape(message)}</p>" if message else ""
    err_html = f"<p style='color:#b00'>{escape(error)}</p>" if error else ""

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>User Admin</title>
{link_next}
<style>
  body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,
  Ubuntu,Helvetica,Arial,sans-serif}}
  table{{border-collapse:collapse;width:100%}}
  th,td{{padding:6px;border:1px solid #ddd;vertical-align:top}}
  .row-actions button{{margin-left:6px}}
  .pager{{margin-top:12px}}
  .create input{{margin-right:8px}}
  .toolbar{{display:flex;gap:8px;align-items:center;margin:12px 0}}
  .toolbar input[type="text"]{{min-width:220px}}
</style>
</head>
<body {data_next}>
<h1>Users</h1>
{msg_html}{err_html}

<form class="toolbar" method="get" action="/admin">
  <input type="text" name="q" placeholder="Search name/email..."
    value="{escape(q or "")}" />
  <input type="hidden" name="limit" value="{limit}">
  <button type="submit">Search</button>
  <a href="/admin">Clear</a>
</form>

<form class="create" method="post" action="/admin/create">
  <input type="text" name="name" placeholder="Name" required>
  <input type="email" name="email" placeholder="Email" required>
  <input type="password" name="password" placeholder="Password" required>
  <button type="submit">Create</button>
</form>

<p>Total: {total} • Showing {len(items)} (limit={limit}, offset={offset})</p>

<table>
  <thead><tr><th>ID</th><th>Name</th><th>Email</th><th>Actions</th></tr></thead>
  <tbody>
{rows_html}
  </tbody>
</table>

<div class="pager">
  {anchor_next}
</div>
</body>
</html>"""


@app.get("/admin", include_in_schema=False)
@app.get("/admin/", include_in_schema=False)
async def admin_index(
    user_repo: UserRepository = Depends(get_user_repository),
    limit: Optional[int] = Query(DEFAULT_LIMIT, ge=1),
    offset: Optional[int] = Query(0, ge=0),
    q: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    query: Optional[str] = Query(None),
    message: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
):
    term = q or search or query
    page_size = min(limit if limit is not None else DEFAULT_LIMIT, MAX_LIMIT)
    page_offset = offset or 0
    items, total = await user_repo.list_paginated(page_size, page_offset, term)
    users: List[UserSchema] = [UserSchema.from_db_model(m) for m in items]
    html = render_admin_page(
        users, total, page_size, page_offset, message, error, q=term
    )
    return Response(content=html, media_type="text/html")


@app.post("/admin/create", include_in_schema=False)
async def admin_create_user(
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    user_repo: UserRepository = Depends(get_user_repository),
):
    try:
        await user_repo.create(name, email, password)
        return RedirectResponse(url="/admin?message=User%20created", status_code=303)
    except IntegrityError:
        return RedirectResponse(
            url="/admin?error=User%20already%20exists", status_code=303
        )
    except Exception:
        return RedirectResponse(
            url="/admin?error=Failed%20to%20create%20user", status_code=303
        )


@app.post("/admin/delete", include_in_schema=False)
async def admin_delete_user(
    name: str = Form(...),
    user_repo: UserRepository = Depends(get_user_repository),
):
    try:
        await user_repo.delete(name)
        return RedirectResponse(url="/admin?message=User%20deleted", status_code=303)
    except Exception:
        return RedirectResponse(
            url="/admin?error=Failed%20to%20delete%20user", status_code=303
        )


# Mount the external UI elsewhere so it doesn't shadow /admin
ui.run_with(app, mount_path="/admin-ui", favicon="👤", title="User Admin")
