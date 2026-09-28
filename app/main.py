import logging
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.middleware.sessions import SessionMiddleware

from .config import BASE_DIR, settings
from .db import init_db
from .routes import api, auth, billing, pages
from .security import LoginRequired, OriginCheckMiddleware
from .web import render

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, lifespan=lifespan, docs_url=None, redoc_url=None)

    # Order matters: the last-added middleware runs first.
    app.add_middleware(OriginCheckMiddleware)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="session",
        max_age=60 * 60 * 24 * 30,
        same_site="lax",
        https_only=settings.is_production,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if settings.is_production:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response

    app.mount("/static", StaticFiles(directory=BASE_DIR / "app" / "static"), name="static")
    app.include_router(pages.router)
    app.include_router(auth.router)
    app.include_router(api.router)
    app.include_router(billing.router)

    @app.exception_handler(LoginRequired)
    async def _login_required(request: Request, exc: LoginRequired):
        return RedirectResponse(f"/login?next={quote(request.url.path)}", status_code=303)

    @app.exception_handler(HTTPException)
    async def _http_error(request: Request, exc: HTTPException):
        if request.url.path.startswith(("/api/", "/billing/webhook")):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        return render(request, "error.html", status_code=exc.status_code,
                      status=exc.status_code, detail=exc.detail)

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"ok": True}

    return app


app = create_app()
