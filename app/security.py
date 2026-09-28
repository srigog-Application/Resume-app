import base64
import hashlib
import hmac
import secrets
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, PlainTextResponse

from .db import get_db
from .models import User

# scrypt parameters (~16 MiB memory, tens of ms per hash).
_N, _R, _P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    b64 = base64.b64encode
    return f"scrypt${_N}${_R}${_P}${b64(salt).decode()}${b64(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(digest_b64)
        digest = hashlib.scrypt(
            password.encode(), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
    except ValueError:
        return False
    return hmac.compare_digest(digest, expected)


# A valid hash to compare against when the email is unknown, so login timing
# doesn't reveal which emails have accounts.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def login_user(request: Request, user: User) -> None:
    request.session.clear()
    request.session["uid"] = user.id


def logout_user(request: Request) -> None:
    request.session.clear()


def get_optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    uid = request.session.get("uid")
    if not isinstance(uid, int):
        return None
    return db.get(User, uid)


class LoginRequired(Exception):
    """Raised on HTML pages; handled by redirecting to /login."""


def require_user_page(user: User | None = Depends(get_optional_user)) -> User:
    if user is None:
        raise LoginRequired()
    return user


def require_user_api(user: User | None = Depends(get_optional_user)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="Please log in.")
    return user


class OriginCheckMiddleware(BaseHTTPMiddleware):
    """CSRF defence: state-changing requests must come from our own origin.

    Browsers send `Origin` on cross-site POST/PUT/DELETE; combined with
    SameSite=Lax session cookies this blocks cross-site form and fetch attacks.
    """

    SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
    EXEMPT_PATHS = {"/billing/webhook"}  # Authenticated by Stripe signature instead.

    async def dispatch(self, request: Request, call_next):
        if request.method not in self.SAFE_METHODS and request.url.path not in self.EXEMPT_PATHS:
            origin = request.headers.get("origin") or request.headers.get("referer")
            if origin:
                parts = urlsplit(origin)
                if parts.netloc != request.headers.get("host", ""):
                    return _forbidden(request)
            elif request.headers.get("sec-fetch-site") == "cross-site":
                return _forbidden(request)
        return await call_next(request)


def _forbidden(request: Request):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Cross-origin request blocked."}, status_code=403)
    return PlainTextResponse("Cross-origin request blocked.", status_code=403)
