"""Job application tracker and cover letters (pages + JSON API)."""

import datetime as dt
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import ai_features, plans
from ..ai import AIError
from ..db import get_db
from ..models import JOB_STATUSES, CoverLetter, Job, Resume, User, utcnow
from ..renderer import RenderError, pdf_filename, render_letter_pdf
from ..resume_data import ResumeData
from ..security import require_user_api, require_user_page
from ..web import flash, render
from .pages import owned_resume

router = APIRouter()


# ------------------------------------------------------------------ helpers


def owned_job(db: Session, user: User, job_id: int) -> Job:
    job = db.get(Job, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


def owned_letter(db: Session, user: User, letter_id: int) -> CoverLetter:
    letter = db.get(CoverLetter, letter_id)
    if letter is None or letter.user_id != user.id:
        raise HTTPException(status_code=404, detail="Cover letter not found.")
    return letter


def _iso(d: dt.datetime | None) -> str | None:
    return d.isoformat() + "Z" if d else None


def job_out(job: Job) -> dict[str, Any]:
    return {
        "id": job.id, "company": job.company, "title": job.title, "url": job.url,
        "location": job.location, "salary": job.salary, "status": job.status,
        "description": job.description, "notes": job.notes, "resume_id": job.resume_id,
        "applied_at": _iso(job.applied_at), "created_at": _iso(job.created_at),
        "updated_at": _iso(job.updated_at),
    }


def letter_out(letter: CoverLetter) -> dict[str, Any]:
    return {"id": letter.id, "title": letter.title, "body": letter.body,
            "job_id": letter.job_id, "resume_id": letter.resume_id,
            "updated_at": _iso(letter.updated_at), "url": f"/app/letters/{letter.id}"}


def user_jobs(db: Session, user: User) -> list[Job]:
    return list(db.scalars(select(Job).where(Job.user_id == user.id)
                           .order_by(Job.updated_at.desc())))


def user_letters(db: Session, user: User) -> list[CoverLetter]:
    return list(db.scalars(select(CoverLetter).where(CoverLetter.user_id == user.id)
                           .order_by(CoverLetter.updated_at.desc())))


# ------------------------------------------------------------------ jobs: pages


@router.get("/app/jobs")
def jobs_page(request: Request, user: User = Depends(require_user_page),
              db: Session = Depends(get_db)):
    jobs = user_jobs(db, user)
    letters = user_letters(db, user)
    return render(request, "jobs.html", user=user, statuses=JOB_STATUSES,
                  boot={"jobs": [job_out(j) for j in jobs],
                        # A list keeps column order (tojson sorts dict keys).
                        "statuses": list(JOB_STATUSES.items()),
                        "resumes": [{"id": r.id, "title": r.title} for r in user.resumes],
                        "letters": [{"id": c.id, "title": c.title, "job_id": c.job_id}
                                    for c in letters]})


# ------------------------------------------------------------------ jobs: API


class JobIn(BaseModel):
    company: str = Field(default="", max_length=200)
    title: str = Field(default="", max_length=200)
    url: str = Field(default="", max_length=1000)
    location: str = Field(default="", max_length=200)
    salary: str = Field(default="", max_length=100)
    status: str = "saved"
    description: str = Field(default="", max_length=30000)
    notes: str = Field(default="", max_length=10000)
    resume_id: int | None = None

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        if v not in JOB_STATUSES:
            raise ValueError("Unknown status.")
        return v

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = v.strip()
        if v and not v.lower().startswith(("http://", "https://")):
            v = "https://" + v
        return v


def _apply_job(db: Session, user: User, job: Job, body: JobIn) -> None:
    if body.resume_id is not None:
        owned_resume(db, user, body.resume_id)
    if body.status != "saved" and job.status == "saved" and job.applied_at is None:
        job.applied_at = utcnow()
    for k, v in body.model_dump().items():
        setattr(job, k, v.strip() if isinstance(v, str) and k not in ("description", "notes")
                else v)


@router.post("/api/jobs")
def create_job(body: JobIn, user: User = Depends(require_user_api),
               db: Session = Depends(get_db)):
    if not (body.company.strip() or body.title.strip()):
        raise HTTPException(status_code=422, detail="Add a company or a job title.")
    job = Job(user_id=user.id, status="saved")
    _apply_job(db, user, job, body)
    db.add(job)
    db.commit()
    return job_out(job)


@router.put("/api/jobs/{job_id}")
def update_job(job_id: int, body: JobIn, user: User = Depends(require_user_api),
               db: Session = Depends(get_db)):
    job = owned_job(db, user, job_id)
    _apply_job(db, user, job, body)
    db.commit()
    return job_out(job)


class StatusIn(BaseModel):
    status: str


@router.patch("/api/jobs/{job_id}/status")
def move_job(job_id: int, body: StatusIn, user: User = Depends(require_user_api),
             db: Session = Depends(get_db)):
    job = owned_job(db, user, job_id)
    if body.status not in JOB_STATUSES:
        raise HTTPException(status_code=422, detail="Unknown status.")
    if body.status != "saved" and job.applied_at is None:
        job.applied_at = utcnow()
    job.status = body.status
    db.commit()
    return job_out(job)


@router.delete("/api/jobs/{job_id}")
def delete_job(job_id: int, user: User = Depends(require_user_api),
               db: Session = Depends(get_db)):
    db.delete(owned_job(db, user, job_id))
    db.commit()
    return {"ok": True}


@router.get("/api/jobs")
def list_jobs(user: User = Depends(require_user_api), db: Session = Depends(get_db)):
    return {"jobs": [job_out(j) for j in user_jobs(db, user)]}


# ------------------------------------------------------------------ letters: pages


@router.get("/app/letters")
def letters_page(request: Request, user: User = Depends(require_user_page),
                 db: Session = Depends(get_db)):
    jobs = user_jobs(db, user)
    return render(request, "letters.html", user=user, letters=user_letters(db, user),
                  jobs={j.id: j for j in jobs},
                  boot={"resumes": [{"id": r.id, "title": r.title} for r in user.resumes],
                        "jobs": [job_out(j) for j in jobs],
                        "left": plans.remaining(db, user, "cover_letter")})


@router.get("/app/letters/{letter_id}")
def letter_page(request: Request, letter_id: int, user: User = Depends(require_user_page),
                db: Session = Depends(get_db)):
    letter = owned_letter(db, user, letter_id)
    job = db.get(Job, letter.job_id) if letter.job_id else None
    return render(request, "letter.html", user=user, letter=letter, job=job,
                  boot=letter_out(letter))


@router.get("/app/letters/{letter_id}/pdf")
def letter_pdf(letter_id: int, user: User = Depends(require_user_page),
               db: Session = Depends(get_db)):
    letter = owned_letter(db, user, letter_id)
    resume = db.get(Resume, letter.resume_id) if letter.resume_id else None
    if resume is None and user.resumes:
        resume = user.resumes[0]
    data = ResumeData.model_validate(resume.data) if resume else ResumeData()
    date = utcnow().strftime("%B %d, %Y").replace(" 0", " ")
    try:
        pdf = render_letter_pdf(letter.body, data, letter.title, date)
    except RenderError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    name = pdf_filename(data, "Cover_Letter").replace("_Resume_", "_")
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/app/letters/{letter_id}/delete")
def delete_letter(request: Request, letter_id: int, user: User = Depends(require_user_page),
                  db: Session = Depends(get_db)):
    db.delete(owned_letter(db, user, letter_id))
    db.commit()
    flash(request, "Cover letter deleted.", "info")
    return RedirectResponse("/app/letters", status_code=303)


# ------------------------------------------------------------------ letters: API


class LetterGenIn(BaseModel):
    resume_id: int
    job_id: int | None = None
    company: str = Field(default="", max_length=200)
    title: str = Field(default="", max_length=200)
    job_description: str = Field(default="", max_length=30000)
    tone: str = Field(default="professional", max_length=20)
    notes: str = Field(default="", max_length=2000)


@router.post("/api/letters/generate")
async def generate_letter(body: LetterGenIn, user: User = Depends(require_user_api),
                          db: Session = Depends(get_db)):
    resume = owned_resume(db, user, body.resume_id)
    company, title, jd = body.company, body.title, body.job_description
    if body.job_id is not None:
        job = owned_job(db, user, body.job_id)
        company, title = company or job.company, title or job.title
        jd = jd or job.description
    if not plans.consume(db, user, "cover_letter"):
        db.commit()
        raise HTTPException(status_code=402, detail=plans.upgrade_hint(user, "cover_letter"))
    db.commit()
    data = ResumeData.model_validate(resume.data)
    try:
        text = await run_in_threadpool(ai_features.cover_letter, data, company, title, jd,
                                       body.tone, body.notes)
    except BaseException as e:
        plans.refund(db, user, "cover_letter")
        db.commit()
        if isinstance(e, AIError):
            raise HTTPException(status_code=502, detail=str(e)) from e
        raise
    label = " · ".join(x for x in (company, title) if x) or "Cover letter"
    letter = CoverLetter(user_id=user.id, job_id=body.job_id, resume_id=resume.id,
                         title=label[:200], body=text)
    db.add(letter)
    db.commit()
    return {**letter_out(letter), "left": plans.remaining(db, user, "cover_letter")}


class LetterIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(max_length=20000)


@router.put("/api/letters/{letter_id}")
def save_letter(letter_id: int, body: LetterIn, user: User = Depends(require_user_api),
                db: Session = Depends(get_db)):
    letter = owned_letter(db, user, letter_id)
    letter.title, letter.body = body.title.strip(), body.body
    db.commit()
    return letter_out(letter)
