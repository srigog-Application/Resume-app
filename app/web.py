"""Shared helpers for HTML responses."""

from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates

from .config import BASE_DIR, settings
from .resume_data import TEMPLATES

templates = Jinja2Templates(directory=BASE_DIR / "app" / "templates")
templates.env.globals.update(settings=settings, TEMPLATES=TEMPLATES)


def flash(request: Request, message: str, kind: str = "info") -> None:
    request.session.setdefault("flash", []).append({"message": message, "kind": kind})


def render(request: Request, name: str, status_code: int = 200, **context: Any):
    messages = request.session.pop("flash", [])
    return templates.TemplateResponse(
        request, name, {"flash_messages": messages, **context}, status_code=status_code
    )


def safe_next(url: str | None, default: str = "/app") -> str:
    """Only allow local redirects (prevents open-redirect via ?next=)."""
    if url and url.startswith("/") and not url.startswith("//") and "\\" not in url:
        return url
    return default
