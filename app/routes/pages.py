from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Resume, ResumeVersion, User
from ..plans import FREE, PRO, ai_credits_left, plan_for
from ..renderer import RenderError, pdf_filename, render_pdf
from ..resume_data import TEMPLATES, ResumeData, blank_resume
from ..security import get_optional_user, require_user_page
from ..web import flash, render

router = APIRouter()


def owned_resume(db: Session, user: User, resume_id: int) -> Resume:
    resume = db.get(Resume, resume_id)
    if resume is None or resume.user_id != user.id:
        raise HTTPException(status_code=404, detail="Resume not found.")
    return resume


def can_use_template(user: User, template_key: str) -> bool:
    return plan_for(user).templates == "all" or TEMPLATES[template_key]["free"]


@router.get("/")
def landing(request: Request, user: User | None = Depends(get_optional_user)):
    return render(request, "landing.html", user=user, free=FREE, pro=PRO)


@router.get("/app")
def dashboard(request: Request, user: User = Depends(require_user_page)):
    plan = plan_for(user)
    return render(request, "dashboard.html", user=user, plan=plan,
                  credits_left=ai_credits_left(user))


@router.post("/app/resumes")
def create_resume(
    request: Request, user: User = Depends(require_user_page), db: Session = Depends(get_db)
):
    plan = plan_for(user)
    if plan.max_resumes is not None and len(user.resumes) >= plan.max_resumes:
        flash(request, f"The Free plan includes {plan.max_resumes} resumes. Upgrade to Pro "
                       "for unlimited resumes.", "warning")
        return RedirectResponse("/app/account", status_code=303)
    resume = Resume(user_id=user.id, title=f"Resume {len(user.resumes) + 1}",
                    data=blank_resume(user.email).model_dump())
    db.add(resume)
    db.commit()
    return RedirectResponse(f"/app/resumes/{resume.id}", status_code=303)


@router.get("/app/resumes/{resume_id}")
def editor(
    request: Request,
    resume_id: int,
    user: User = Depends(require_user_page),
    db: Session = Depends(get_db),
):
    resume = owned_resume(db, user, resume_id)
    data = ResumeData.model_validate(resume.data)
    return render(request, "editor.html", user=user, resume=resume,
                  resume_json=data.model_dump(), plan=plan_for(user),
                  credits_left=ai_credits_left(user))


def _pdf_response(request: Request, user: User, data: ResumeData, suffix: str = ""):
    if not can_use_template(user, data.design.template):
        name = TEMPLATES[data.design.template]["name"]
        flash(request, f"The {name} template is a Pro template. Upgrade to download it, or "
                       "switch to a free template.", "warning")
        return RedirectResponse("/app/account", status_code=303)
    try:
        result = render_pdf(data)
    except RenderError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    filename = pdf_filename(data, suffix)
    return Response(result.content, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/app/resumes/{resume_id}/pdf")
def download_pdf(
    request: Request,
    resume_id: int,
    user: User = Depends(require_user_page),
    db: Session = Depends(get_db),
):
    resume = owned_resume(db, user, resume_id)
    return _pdf_response(request, user, ResumeData.model_validate(resume.data))


@router.get("/app/resumes/{resume_id}/versions/{version_id}/pdf")
def download_version_pdf(
    request: Request,
    resume_id: int,
    version_id: int,
    user: User = Depends(require_user_page),
    db: Session = Depends(get_db),
):
    resume = owned_resume(db, user, resume_id)
    version = db.scalar(select(ResumeVersion).where(
        ResumeVersion.id == version_id, ResumeVersion.resume_id == resume.id))
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found.")
    return _pdf_response(request, user, ResumeData.model_validate(version.data), version.label)


@router.post("/app/resumes/{resume_id}/delete")
def delete_resume(
    request: Request,
    resume_id: int,
    user: User = Depends(require_user_page),
    db: Session = Depends(get_db),
):
    resume = owned_resume(db, user, resume_id)
    db.delete(resume)
    db.commit()
    flash(request, f"Deleted “{resume.title}”.", "info")
    return RedirectResponse("/app", status_code=303)


@router.get("/app/account")
def account(request: Request, user: User = Depends(require_user_page)):
    return render(request, "account.html", user=user, plan=plan_for(user), free=FREE, pro=PRO,
                  credits_left=ai_credits_left(user))
