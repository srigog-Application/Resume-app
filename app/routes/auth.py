import re

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Resume, User
from ..resume_data import blank_resume
from ..security import (
    DUMMY_HASH,
    get_optional_user,
    hash_password,
    login_user,
    logout_user,
    verify_password,
)
from ..web import flash, render, safe_next

router = APIRouter()

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD = 8


@router.get("/signup")
def signup_page(request: Request, next: str = "", user: User | None = Depends(get_optional_user)):
    if user:
        return RedirectResponse("/app", status_code=303)
    return render(request, "auth.html", mode="signup", next=safe_next(next), email="")


@router.post("/signup")
def signup(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form(""),
    db: Session = Depends(get_db),
):
    email = email.strip().lower()
    error = None
    if not EMAIL_RE.match(email) or len(email) > 320:
        error = "Please enter a valid email address."
    elif len(password) < MIN_PASSWORD:
        error = f"Password must be at least {MIN_PASSWORD} characters."
    elif len(password) > 512:
        error = "Password is too long."
    elif db.scalar(select(User).where(func.lower(User.email) == email)):
        error = "An account with that email already exists. Try logging in."
    if error:
        return render(request, "auth.html", status_code=400, mode="signup", error=error,
                      email=email, next=safe_next(next))

    user = User(email=email, password_hash=hash_password(password))
    db.add(user)
    db.flush()
    db.add(Resume(user_id=user.id, title="My Resume",
                  data=blank_resume(email).model_dump()))
    db.commit()
    login_user(request, user)
    flash(request, "Welcome! Let's build your resume.", "success")
    return RedirectResponse(safe_next(next), status_code=303)


@router.get("/login")
def login_page(request: Request, next: str = "", user: User | None = Depends(get_optional_user)):
    if user:
        return RedirectResponse("/app", status_code=303)
    return render(request, "auth.html", mode="login", next=safe_next(next), email="")


@router.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form(""),
    db: Session = Depends(get_db),
):
    email = email.strip().lower()
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    ok = verify_password(password, user.password_hash if user else DUMMY_HASH)
    if not (user and ok):
        return render(request, "auth.html", status_code=400, mode="login",
                      error="Incorrect email or password.", email=email, next=safe_next(next))
    login_user(request, user)
    return RedirectResponse(safe_next(next), status_code=303)


@router.post("/logout")
def logout(request: Request):
    logout_user(request)
    return RedirectResponse("/", status_code=303)
