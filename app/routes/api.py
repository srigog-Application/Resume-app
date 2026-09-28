"""JSON API used by the editor."""

import base64
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import ai
from ..db import get_db
from ..keywords import keyword_report
from ..models import Resume, ResumeVersion, User
from ..plans import PRO, ai_credits_left, consume_ai_credit, plan_for, refund_ai_credit
from ..renderer import RenderError, render_png_pages
from ..resume_data import TEMPLATES, ResumeData, resume_plain_text
from ..security import require_user_api
from .pages import can_use_template, owned_resume

router = APIRouter(prefix="/api")


class SaveIn(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    data: dict[str, Any]


class DuplicateIn(BaseModel):
    title: str = Field(max_length=200)
    data: dict[str, Any] | None = None


class PreviewIn(BaseModel):
    data: dict[str, Any]


class VersionIn(BaseModel):
    label: str = Field(min_length=1, max_length=200)


class BulletsIn(BaseModel):
    bullets: list[str] = Field(max_length=30)
    position: str = Field(default="", max_length=200)
    company: str = Field(default="", max_length=200)
    job_description: str = Field(default="", max_length=20000)


class ResumeJobIn(BaseModel):
    data: dict[str, Any]
    job_description: str = Field(default="", max_length=20000)


def _resume_out(resume: Resume) -> dict[str, Any]:
    return {"id": resume.id, "title": resume.title,
            "updated_at": resume.updated_at.isoformat() + "Z"}


def _version_out(v: ResumeVersion) -> dict[str, Any]:
    return {"id": v.id, "label": v.label, "created_at": v.created_at.isoformat() + "Z",
            "template": TEMPLATES[ResumeData.model_validate(v.data).design.template]["name"]}


# ------------------------------------------------------------------ resumes


@router.put("/resumes/{resume_id}")
def save_resume(resume_id: int, body: SaveIn, user: User = Depends(require_user_api),
                db: Session = Depends(get_db)):
    resume = owned_resume(db, user, resume_id)
    resume.data = ResumeData.model_validate(body.data).model_dump()
    if body.title is not None and body.title.strip():
        resume.title = body.title.strip()
    db.commit()
    return _resume_out(resume)


@router.post("/resumes/{resume_id}/duplicate")
def duplicate_resume(resume_id: int, body: DuplicateIn, user: User = Depends(require_user_api),
                     db: Session = Depends(get_db)):
    source = owned_resume(db, user, resume_id)
    plan = plan_for(user)
    if plan.max_resumes is not None and len(user.resumes) >= plan.max_resumes:
        raise HTTPException(status_code=402, detail=(
            f"The Free plan includes {plan.max_resumes} resumes. Upgrade to Pro for unlimited "
            "tailored copies, or save this as a version instead."))
    data = ResumeData.model_validate(body.data if body.data is not None else source.data)
    copy = Resume(user_id=user.id, title=body.title.strip() or f"{source.title} (copy)",
                  data=data.model_dump())
    db.add(copy)
    db.commit()
    return {**_resume_out(copy), "url": f"/app/resumes/{copy.id}"}


@router.post("/preview")
def preview(body: PreviewIn, user: User = Depends(require_user_api)):
    data = ResumeData.model_validate(body.data)
    try:
        result = render_png_pages(data)
    except RenderError as e:
        return {"pages": [], "warnings": [], "error": str(e)}
    pages = ["data:image/png;base64," + base64.b64encode(p).decode() for p in result.content]
    locked = not can_use_template(user, data.design.template)
    return {"pages": pages, "warnings": result.warnings, "error": None, "locked": locked}


# ------------------------------------------------------------------ versions


@router.get("/resumes/{resume_id}/versions")
def list_versions(resume_id: int, user: User = Depends(require_user_api),
                  db: Session = Depends(get_db)):
    resume = owned_resume(db, user, resume_id)
    return {"versions": [_version_out(v) for v in resume.versions]}


@router.post("/resumes/{resume_id}/versions")
def create_version(resume_id: int, body: VersionIn, user: User = Depends(require_user_api),
                   db: Session = Depends(get_db)):
    resume = owned_resume(db, user, resume_id)
    limit = plan_for(user).max_versions_per_resume
    count = db.scalar(select(func.count()).where(ResumeVersion.resume_id == resume.id)) or 0
    if limit is not None and count >= limit:
        raise HTTPException(status_code=402, detail=(
            f"The Free plan keeps {limit} saved versions per resume. Delete one or upgrade "
            "to Pro for unlimited versions."))
    version = ResumeVersion(resume_id=resume.id, label=body.label.strip(), data=resume.data)
    db.add(version)
    db.commit()
    return _version_out(version)


def _owned_version(db: Session, resume: Resume, version_id: int) -> ResumeVersion:
    version = db.scalar(select(ResumeVersion).where(
        ResumeVersion.id == version_id, ResumeVersion.resume_id == resume.id))
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found.")
    return version


@router.post("/resumes/{resume_id}/versions/{version_id}/restore")
def restore_version(resume_id: int, version_id: int, user: User = Depends(require_user_api),
                    db: Session = Depends(get_db)):
    resume = owned_resume(db, user, resume_id)
    version = _owned_version(db, resume, version_id)
    resume.data = version.data
    db.commit()
    return {"data": ResumeData.model_validate(resume.data).model_dump()}


@router.delete("/resumes/{resume_id}/versions/{version_id}")
def delete_version(resume_id: int, version_id: int, user: User = Depends(require_user_api),
                   db: Session = Depends(get_db)):
    resume = owned_resume(db, user, resume_id)
    db.delete(_owned_version(db, resume, version_id))
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ AI


async def _metered(user: User, db: Session, fn, *args):
    """Run an AI call, charging one credit and refunding it on failure."""
    if not consume_ai_credit(user):
        db.commit()
        detail = "You've used all AI credits for this month."
        if not user.is_pro:
            detail += f" Upgrade to Pro for {PRO.ai_credits_per_month} credits/month."
        raise HTTPException(status_code=402, detail=detail)
    db.commit()
    try:
        result = await run_in_threadpool(fn, *args)
    except ai.AIError as e:
        refund_ai_credit(user)
        db.commit()
        raise HTTPException(status_code=502, detail=str(e)) from e
    return result


@router.post("/ai/bullets")
async def ai_bullets(body: BulletsIn, user: User = Depends(require_user_api),
                     db: Session = Depends(get_db)):
    bullets = await _metered(user, db, ai.rewrite_bullets, body.bullets, body.position,
                             body.company, body.job_description)
    return {"bullets": bullets, "credits_left": ai_credits_left(user)}


@router.post("/ai/summary")
async def ai_summary(body: ResumeJobIn, user: User = Depends(require_user_api),
                     db: Session = Depends(get_db)):
    data = ResumeData.model_validate(body.data)
    summary = await _metered(user, db, ai.write_summary, data, body.job_description)
    return {"summary": summary, "credits_left": ai_credits_left(user)}


@router.post("/ai/tailor")
async def ai_tailor(body: ResumeJobIn, user: User = Depends(require_user_api),
                    db: Session = Depends(get_db)):
    data = ResumeData.model_validate(body.data)
    result = await _metered(user, db, ai.tailor, data, body.job_description)
    return {**result.model_dump(), "credits_left": ai_credits_left(user)}


@router.post("/keywords")
def keywords(body: ResumeJobIn, user: User = Depends(require_user_api)):
    data = ResumeData.model_validate(body.data)
    return keyword_report(resume_plain_text(data), body.job_description)
