"""JSON API used by the editor."""

import base64
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import ai, ai_features, plans
from ..ai import AIError, AIInputError
from ..ats import run_checks
from ..db import get_db
from ..extract import MAX_BYTES as MAX_UPLOAD
from ..extract import ExtractError, extract_text
from ..keywords import keyword_report
from ..models import ChatMessage, Resume, ResumeVersion, User
from ..plans import plan_for
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
    bullets: list[Annotated[str, Field(max_length=1000)]] = Field(max_length=30)
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


def _remaining(db: Session, user: User, feature: str) -> int | None:
    return plans.remaining(db, user, feature)


async def _metered(user: User, db: Session, feature: str, fn, *args):
    """Run an AI call, charging one use of `feature` and refunding it on failure."""
    if not plans.consume(db, user, feature):
        db.commit()
        raise HTTPException(status_code=402, detail=plans.upgrade_hint(user, feature))
    db.commit()
    try:
        result = await run_in_threadpool(fn, *args)
    except BaseException as e:
        # Never keep a credit for a call that didn't deliver, whatever failed.
        plans.refund(db, user, feature)
        db.commit()
        if isinstance(e, AIInputError):
            raise HTTPException(status_code=422, detail=str(e)) from e
        if isinstance(e, AIError):
            raise HTTPException(status_code=502, detail=str(e)) from e
        raise
    return result


@router.post("/ai/bullets")
async def ai_bullets(body: BulletsIn, user: User = Depends(require_user_api),
                     db: Session = Depends(get_db)):
    bullets = await _metered(user, db, "chat", ai.rewrite_bullets, body.bullets,
                             body.position, body.company, body.job_description)
    return {"bullets": bullets, "credits_left": _remaining(db, user, "chat")}


@router.post("/ai/summary")
async def ai_summary(body: ResumeJobIn, user: User = Depends(require_user_api),
                     db: Session = Depends(get_db)):
    data = ResumeData.model_validate(body.data)
    summary = await _metered(user, db, "chat", ai.write_summary, data, body.job_description)
    return {"summary": summary, "credits_left": _remaining(db, user, "chat")}


@router.post("/ai/tailor")
async def ai_tailor(body: ResumeJobIn, user: User = Depends(require_user_api),
                    db: Session = Depends(get_db)):
    data = ResumeData.model_validate(body.data)
    result = await _metered(user, db, "tailor", ai.tailor, data, body.job_description)
    return {**result.model_dump(), "tailor_left": _remaining(db, user, "tailor")}


@router.post("/keywords")
def keywords(body: ResumeJobIn, user: User = Depends(require_user_api)):
    data = ResumeData.model_validate(body.data)
    return keyword_report(resume_plain_text(data), body.job_description)


# ------------------------------------------------------------------ import


@router.post("/resumes/import")
async def import_resume(file: UploadFile = File(...), user: User = Depends(require_user_api),
                        db: Session = Depends(get_db)):
    plan = plans.plan_for(user)
    if plan.max_resumes is not None and len(user.resumes) >= plan.max_resumes:
        raise HTTPException(status_code=402, detail=(
            f"The Free plan includes {plan.max_resumes} resumes. Delete one or upgrade to "
            "Pro for unlimited uploads."))
    content = await file.read(MAX_UPLOAD + 1)
    try:
        text = await run_in_threadpool(extract_text, file.filename or "", content)
    except ExtractError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    # Importing calls the AI with the whole document, so it is metered.
    data = await _metered(user, db, "import", ai_features.import_resume, text)
    title = (file.filename or "Imported resume").rsplit(".", 1)[0][:200] or "Imported resume"
    resume = Resume(user_id=user.id, title=title, data=data.model_dump())
    db.add(resume)
    db.commit()
    return {**_resume_out(resume), "url": f"/app/resumes/{resume.id}#analysis"}


# ------------------------------------------------------------------ analysis


@router.post("/ats-check")
def ats_check(body: PreviewIn, user: User = Depends(require_user_api)):
    return run_checks(ResumeData.model_validate(body.data))


@router.post("/ai/analysis")
async def ai_analysis(body: ResumeJobIn, user: User = Depends(require_user_api),
                      db: Session = Depends(get_db)):
    data = ResumeData.model_validate(body.data)
    result = await _metered(user, db, "analysis", ai_features.analyze, data,
                            body.job_description)
    return {**result.model_dump(), "checks": run_checks(data),
            "analysis_left": _remaining(db, user, "analysis")}


# ------------------------------------------------------------------ coach chat


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    job_description: str = Field(default="", max_length=20000)


class ApplyEditIn(BaseModel):
    edit: ai_features.ResumeEdit
    target: str | None = Field(default=None, max_length=500)


def _chat_out(m: ChatMessage) -> dict[str, Any]:
    return {"id": m.id, "role": m.role, "content": m.content, "edits": m.edits or []}


@router.get("/resumes/{resume_id}/chat")
def chat_history(resume_id: int, user: User = Depends(require_user_api),
                 db: Session = Depends(get_db)):
    resume = owned_resume(db, user, resume_id)
    rows = db.scalars(select(ChatMessage).where(ChatMessage.resume_id == resume.id)
                      .order_by(ChatMessage.id)).all()
    return {"messages": [_chat_out(m) for m in rows],
            "credits_left": _remaining(db, user, "chat")}


@router.post("/resumes/{resume_id}/chat")
async def chat_send(resume_id: int, body: ChatIn, user: User = Depends(require_user_api),
                    db: Session = Depends(get_db)):
    resume = owned_resume(db, user, resume_id)
    data = ResumeData.model_validate(resume.data)
    history = [{"role": m.role, "content": m.content} for m in db.scalars(
        select(ChatMessage).where(ChatMessage.resume_id == resume.id)
        .order_by(ChatMessage.id.desc()).limit(20)).all()][::-1]
    reply = await _metered(user, db, "chat", ai_features.chat, data, history, body.message,
                           body.job_description)
    user_msg = ChatMessage(resume_id=resume.id, role="user", content=body.message)
    # Each edit remembers which entry it was written for (see relocate_edit).
    bot_msg = ChatMessage(resume_id=resume.id, role="assistant", content=reply.reply,
                          edits=[{**e.model_dump(), "target": ai_features.edit_target(data, e)}
                                 for e in reply.edits])
    db.add_all([user_msg, bot_msg])
    db.commit()
    return {"user": _chat_out(user_msg), "assistant": _chat_out(bot_msg),
            "credits_left": _remaining(db, user, "chat")}


@router.delete("/resumes/{resume_id}/chat")
def chat_clear(resume_id: int, user: User = Depends(require_user_api),
               db: Session = Depends(get_db)):
    resume = owned_resume(db, user, resume_id)
    for m in db.scalars(select(ChatMessage).where(ChatMessage.resume_id == resume.id)):
        db.delete(m)
    db.commit()
    return {"ok": True}


@router.post("/resumes/{resume_id}/apply-edit")
def apply_edit(resume_id: int, body: ApplyEditIn, user: User = Depends(require_user_api),
               db: Session = Depends(get_db)):
    resume = owned_resume(db, user, resume_id)
    data = ResumeData.model_validate(resume.data)
    edit = ai_features.relocate_edit(data, body.edit, body.target)
    if edit is None:
        raise HTTPException(status_code=409, detail=(
            "The entry this suggestion was written for has changed or been removed."))
    resume.data = ai_features.apply_edit(data, edit).model_dump()
    db.commit()
    return {"data": resume.data}
