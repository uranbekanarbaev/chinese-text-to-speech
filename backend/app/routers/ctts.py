"""
Chinese TTS (uranbekanarbaev.dev), Google OAuth + history endpoints.

Ported out of hsk-tutor's backend/app/routers/ctts.py, logic unchanged -
this service now owns the `ctts` schema outright instead of sharing
hsk-tutor's `yihan_user` DB role.

Auth flow:
  1. Frontend gets Google ID token via Sign-In button
  2. POST /api/ctts/auth/google  { token: <google_id_token> }
  3. Backend verifies with Google, upserts ctts.users, returns our JWT
  4. Frontend includes JWT as  Authorization: Bearer <jwt>  on TTS requests
"""

from datetime import datetime, timedelta
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import text

from ..config import settings
from ..database import AsyncSessionLocal

router = APIRouter(prefix="/api/ctts", tags=["ctts"])

# Anonymous is IP-scoped, authenticated is user-scoped - both share the
# same ctts.rate_limits table (the `ip` column stores either "ip:<addr>"
# or "user:<id>", see check_and_increment_rate_limit).
DAILY_CHAR_LIMIT_ANON = 1000
DAILY_CHAR_LIMIT_AUTH = 3000
DAILY_REQUEST_LIMIT = 30

# Absolute per-request sanity ceiling, independent of the daily budgets
# above - rejects a pathological single payload (e.g. a scraped page of
# megabytes) outright rather than trying to chunk-synthesize it. Well above
# DAILY_CHAR_LIMIT_AUTH since a single request is still gated by the daily
# budget check that runs after this one.
MAX_REQUEST_CHARS = 500_000

# Backward-compat alias - some older code/tests may still reference this name.
DAILY_CHAR_LIMIT = DAILY_CHAR_LIMIT_ANON

# JWT helpers

def create_ctts_token(ctts_user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(days=30)
    return jwt.encode(
        {"sub": str(ctts_user_id), "type": "ctts", "exp": expire},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )


def decode_ctts_token(token: str) -> int | None:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("type") != "ctts":
            return None
        return int(payload["sub"])
    except (JWTError, ValueError):
        return None


def get_ctts_user_id(authorization: str | None = Header(default=None)) -> int | None:
    """FastAPI dependency, returns ctts user id if Bearer token is valid, else None."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return decode_ctts_token(authorization.removeprefix("Bearer "))


# Google auth

_CALLBACK_URI = f"{settings.API_URL}/api/ctts/auth/google/callback"
_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


@router.get("/auth/google/redirect")
async def google_auth_redirect():
    """Redirect browser to Google OAuth consent screen (server-side flow)."""
    params = urlencode({
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": _CALLBACK_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "select_account",
    })
    return RedirectResponse(f"{_GOOGLE_AUTH_URL}?{params}")


@router.get("/auth/google/callback")
async def google_auth_callback(code: str = Query(...)):
    """Handle Google OAuth callback → create JWT → redirect to frontend."""
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(_GOOGLE_TOKEN_URL, data={
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": _CALLBACK_URI,
            "grant_type": "authorization_code",
        })
    token_data = token_resp.json()
    id_token_str = token_data.get("id_token")
    if not id_token_str:
        raise HTTPException(status_code=400, detail=f"Google token exchange failed: {token_data}")

    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token as google_id_token
        idinfo = google_id_token.verify_oauth2_token(
            id_token_str, google_requests.Request(), settings.GOOGLE_CLIENT_ID,
        )
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Invalid Google token: {exc}")

    google_id = idinfo["sub"]
    email = idinfo.get("email", "")
    name = idinfo.get("name", "")
    picture = idinfo.get("picture", "")

    async with AsyncSessionLocal() as db:
        row = await db.execute(
            text("SELECT id FROM ctts.users WHERE google_id = :gid"), {"gid": google_id}
        )
        row = row.fetchone()
        if row:
            user_id = row.id
            await db.execute(
                text("UPDATE ctts.users SET name=:n, picture=:p WHERE id=:id"),
                {"n": name, "p": picture, "id": user_id},
            )
        else:
            result = await db.execute(
                text(
                    "INSERT INTO ctts.users (google_id, email, name, picture) "
                    "VALUES (:gid, :e, :n, :p) RETURNING id"
                ),
                {"gid": google_id, "e": email, "n": name, "p": picture},
            )
            user_id = result.fetchone().id
        await db.commit()

    our_jwt = create_ctts_token(user_id)
    user_json = f'{{"name":"{name}","email":"{email}","picture":"{picture}"}}'
    import urllib.parse
    redirect_url = (
        f"{settings.CTTS_FRONTEND_URL}"
        f"?ctts_token={urllib.parse.quote(our_jwt)}"
        f"&ctts_user={urllib.parse.quote(user_json)}"
    )
    return RedirectResponse(redirect_url)


class GoogleAuthRequest(BaseModel):
    token: str  # Google ID token from frontend (legacy popup flow)


@router.post("/auth/google")
async def google_auth(body: GoogleAuthRequest):
    """Verify Google ID token → upsert user → return our JWT."""
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token as google_id_token
        idinfo = google_id_token.verify_oauth2_token(
            body.token,
            google_requests.Request(),
            settings.GOOGLE_CLIENT_ID,
        )
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Invalid Google token: {exc}")

    google_id = idinfo["sub"]
    email = idinfo.get("email", "")
    name = idinfo.get("name", "")
    picture = idinfo.get("picture", "")

    async with AsyncSessionLocal() as db:
        row = await db.execute(
            text("SELECT id FROM ctts.users WHERE google_id = :gid"),
            {"gid": google_id},
        )
        row = row.fetchone()
        if row:
            user_id = row.id
            await db.execute(
                text("UPDATE ctts.users SET name=:n, picture=:p WHERE id=:id"),
                {"n": name, "p": picture, "id": user_id},
            )
        else:
            result = await db.execute(
                text(
                    "INSERT INTO ctts.users (google_id, email, name, picture) "
                    "VALUES (:gid, :e, :n, :p) RETURNING id"
                ),
                {"gid": google_id, "e": email, "n": name, "p": picture},
            )
            user_id = result.fetchone().id
        await db.commit()

    return {
        "token": create_ctts_token(user_id),
        "user": {"name": name, "email": email, "picture": picture},
    }


# History

@router.get("/history")
async def get_history(ctts_user_id: int | None = Depends(get_ctts_user_id)):
    if not ctts_user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            text(
                "SELECT id, text_content, char_count, voice, rate, audio_url, created_at "
                "FROM ctts.tts_history WHERE user_id = :uid "
                "ORDER BY created_at DESC LIMIT 50"
            ),
            {"uid": ctts_user_id},
        )
        rows = rows.fetchall()

    return [
        {
            "id": r.id,
            "text": r.text_content,
            "char_count": r.char_count,
            "voice": r.voice,
            "rate": r.rate,
            "audio_url": r.audio_url,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


# Rate limit helpers (used by voice router)

def _rate_limit_subject(ip: str | None, user_id: int | None) -> tuple[str, int, str]:
    """
    Picks the tracking key + daily budget + human label for a request.
    Authenticated requests are tracked per-user (stable identity); anonymous
    ones per-IP (the only signal available). Both share ctts.rate_limits -
    the `ip` column just stores whichever key applies.
    """
    if user_id is not None:
        return f"user:{user_id}", DAILY_CHAR_LIMIT_AUTH, "signed-in"
    return f"ip:{ip}", DAILY_CHAR_LIMIT_ANON, "anonymous"


async def check_and_increment_rate_limit(
    ip: str | None, char_count: int, user_id: int | None = None
) -> tuple[bool, str]:
    """Returns (allowed, error_message). Increments counters if allowed."""
    from datetime import date
    today = date.today()
    subject, daily_limit, label = _rate_limit_subject(ip, user_id)

    async with AsyncSessionLocal() as db:
        row = await db.execute(
            text(
                "SELECT char_count, request_count FROM ctts.rate_limits "
                "WHERE ip = :ip AND limit_date = :d"
            ),
            {"ip": subject, "d": today},
        )
        row = row.fetchone()
        cur_chars = row.char_count if row else 0
        cur_reqs = row.request_count if row else 0

        if cur_reqs >= DAILY_REQUEST_LIMIT:
            return False, f"Daily limit reached: {DAILY_REQUEST_LIMIT} free requests per day."
        if cur_chars + char_count > daily_limit:
            remaining = max(0, daily_limit - cur_chars)
            hint = "" if user_id is not None else " Sign in with Google for a higher daily limit."
            return False, (
                f"Daily character limit reached ({daily_limit} chars/day for {label} users, "
                f"{remaining} remaining today).{hint}"
            )

        await db.execute(
            text(
                "INSERT INTO ctts.rate_limits (ip, limit_date, char_count, request_count) "
                "VALUES (:ip, :d, :cc, 1) "
                "ON CONFLICT (ip, limit_date) DO UPDATE SET "
                "  char_count = ctts.rate_limits.char_count + :cc, "
                "  request_count = ctts.rate_limits.request_count + 1"
            ),
            {"ip": subject, "d": today, "cc": char_count},
        )
        await db.commit()

    return True, ""


async def save_history(user_id: int, text_content: str, voice: str, rate: float, audio_url: str | None):
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "INSERT INTO ctts.tts_history "
                "(user_id, text_content, char_count, voice, rate, audio_url, created_at) "
                "VALUES (:uid, :tc, :cc, :v, :r, :url, NOW())"
            ),
            {
                "uid": user_id,
                "tc": text_content[:2000],
                "cc": len(text_content),
                "v": voice,
                "r": rate,
                "url": audio_url,
            },
        )
        await db.commit()


_OSS_HOST = "taobao-image-search-bucket.oss-ap-southeast-1.aliyuncs.com"


@router.get("/audio/download")
async def download_audio(
    url: str = Query(...),
    ctts_user_id: int | None = Depends(get_ctts_user_id),
):
    """Proxy OSS audio download to avoid browser CORS restrictions."""
    if not ctts_user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    if _OSS_HOST not in url:
        raise HTTPException(status_code=400, detail="Invalid audio URL")
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url)
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail="Audio unavailable")
    from fastapi.responses import Response as _Resp
    return _Resp(
        content=r.content,
        media_type="audio/mpeg",
        headers={"Content-Disposition": 'attachment; filename="chinese-tts.mp3"'},
    )
