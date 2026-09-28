"""The resume document the guided editor edits, and its mapping onto the engine.

The editor works with a simple, form-friendly JSON shape (`ResumeData`). It is
converted to the engine's input format only at render time, so the templates
can evolve without migrating stored documents.
"""

import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

from cvengine.schema.models.cv.cv import email_validator, phone_validator, website_validator

# ---------------------------------------------------------------- templates

# key -> (display name, engine theme, free tier?, short description)
TEMPLATES: dict[str, dict[str, Any]] = {
    "classic": {"name": "Classic", "theme": "classic", "free": True,
                "blurb": "Balanced and timeless, with a clean accent rule."},
    "harvard": {"name": "Harvard", "theme": "harvard", "free": True,
                "blurb": "Serif, centered, conservative. Loved by finance and law."},
    "compact": {"name": "Compact", "theme": "engineeringresumes", "free": True,
                "blurb": "Dense single column that fits more on one page."},
    "minimal": {"name": "Minimal", "theme": "sb2nov", "free": False,
                "blurb": "Quiet typography, lots of white space."},
    "modern": {"name": "Modern", "theme": "moderncv", "free": False,
               "blurb": "Dates in a left rail for a scannable timeline."},
    "technical": {"name": "Technical", "theme": "engineeringclassic", "free": False,
                  "blurb": "Crisp headings built for engineering roles."},
    "elegant": {"name": "Elegant", "theme": "ember", "free": False,
                "blurb": "Refined serif headings with a warm accent."},
    "ink": {"name": "Ink", "theme": "ink", "free": False,
            "blurb": "Bold section bands, still 100% ATS-parseable."},
    "opal": {"name": "Opal", "theme": "opal", "free": False,
             "blurb": "Soft, contemporary and friendly."},
}
DEFAULT_TEMPLATE = "classic"

HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
MONTH = re.compile(r"^\d{4}(-\d{2})?$")

MAX_TEXT = 2000
MAX_ITEMS = 40


def _clean(value: Any, limit: int = 300) -> str:
    if value is None:
        return ""
    return str(value).replace("\r", "").strip()[:limit]


# ---------------------------------------------------------------- schema


class _Model(BaseModel):
    model_config = {"extra": "ignore"}


class Basics(_Model):
    name: str = ""
    headline: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    website: str = ""
    linkedin: str = ""
    github: str = ""

    @field_validator("*", mode="before")
    @classmethod
    def _strip(cls, v: Any) -> str:
        return _clean(v, 200)


class ExperienceItem(_Model):
    position: str = ""
    company: str = ""
    location: str = ""
    start_date: str = ""
    end_date: str = ""
    current: bool = False
    bullets: list[str] = Field(default_factory=list)

    @field_validator("position", "company", "location", "start_date", "end_date", mode="before")
    @classmethod
    def _strip(cls, v: Any) -> str:
        return _clean(v, 200)

    @field_validator("bullets", mode="before")
    @classmethod
    def _bullets(cls, v: Any) -> list[str]:
        return [_clean(b, 600) for b in (v or [])][:MAX_ITEMS]


class EducationItem(_Model):
    institution: str = ""
    degree: str = ""
    area: str = ""
    location: str = ""
    start_date: str = ""
    end_date: str = ""
    details: list[str] = Field(default_factory=list)

    @field_validator("institution", "degree", "area", "location", "start_date", "end_date",
                     mode="before")
    @classmethod
    def _strip(cls, v: Any) -> str:
        return _clean(v, 200)

    @field_validator("details", mode="before")
    @classmethod
    def _details(cls, v: Any) -> list[str]:
        return [_clean(b, 600) for b in (v or [])][:MAX_ITEMS]


class ProjectItem(_Model):
    name: str = ""
    link: str = ""
    start_date: str = ""
    end_date: str = ""
    bullets: list[str] = Field(default_factory=list)

    @field_validator("name", "link", "start_date", "end_date", mode="before")
    @classmethod
    def _strip(cls, v: Any) -> str:
        return _clean(v, 200)

    @field_validator("bullets", mode="before")
    @classmethod
    def _bullets(cls, v: Any) -> list[str]:
        return [_clean(b, 600) for b in (v or [])][:MAX_ITEMS]


class SkillGroup(_Model):
    label: str = ""
    details: str = ""

    @field_validator("label", "details", mode="before")
    @classmethod
    def _strip(cls, v: Any) -> str:
        return _clean(v, 400)


class Certification(_Model):
    name: str = ""
    issuer: str = ""
    date: str = ""

    @field_validator("name", "issuer", "date", mode="before")
    @classmethod
    def _strip(cls, v: Any) -> str:
        return _clean(v, 200)


class Design(_Model):
    template: str = DEFAULT_TEMPLATE
    accent_color: str = ""
    page_size: str = "us-letter"

    @field_validator("template", mode="before")
    @classmethod
    def _template(cls, v: Any) -> str:
        return v if v in TEMPLATES else DEFAULT_TEMPLATE

    @field_validator("accent_color", mode="before")
    @classmethod
    def _color(cls, v: Any) -> str:
        return v if isinstance(v, str) and HEX_COLOR.match(v) else ""

    @field_validator("page_size", mode="before")
    @classmethod
    def _page(cls, v: Any) -> str:
        return v if v in ("us-letter", "a4") else "us-letter"


class ResumeData(_Model):
    basics: Basics = Field(default_factory=Basics)
    summary: str = ""
    experience: list[ExperienceItem] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    skills: list[SkillGroup] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    design: Design = Field(default_factory=Design)

    @field_validator("summary", mode="before")
    @classmethod
    def _summary(cls, v: Any) -> str:
        return _clean(v, MAX_TEXT)

    @field_validator("experience", "education", "projects", "skills", "certifications",
                     mode="before")
    @classmethod
    def _cap(cls, v: Any) -> Any:
        return (v or [])[:MAX_ITEMS]


# ---------------------------------------------------------------- conversion


def _date(value: str) -> str | None:
    value = value.strip()
    if not value:
        return None
    if value.lower() in ("present", "current", "now"):
        return "present"
    return value if MONTH.match(value) else None


def _date_fields(start: str, end: str, current: bool = False) -> dict[str, str]:
    out: dict[str, str] = {}
    s, e = _date(start), ("present" if current else _date(end))
    if s and s != "present" and e:
        out["start_date"] = s
        out["end_date"] = e
    elif s and s != "present":
        out["date"] = s
    elif e:
        out["date"] = e
    return out


def _url(value: str) -> str | None:
    value = value.strip()
    if not value:
        return None
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value
    return value


def _handle(value: str, host: str) -> str | None:
    """Accept either a profile URL or a bare username; return the username."""
    value = value.strip().rstrip("/")
    if not value:
        return None
    m = re.search(rf"{host}/(?:in/)?([^/?#]+)", value, re.I)
    username = m.group(1) if m else value.lstrip("@")
    return username if re.fullmatch(r"[A-Za-z0-9_.\-]{1,100}", username) else None


def _nonempty(items: list[str]) -> list[str]:
    return [i for i in items if i.strip()]


def _valid(validator: Any, value: str) -> bool:
    try:
        validator.validate_python(value)
    except ValidationError:
        return False
    return True


def to_engine_input(data: ResumeData) -> tuple[dict[str, Any], list[str]]:
    """Build the engine's `{cv, design, locale}` input.

    Returns the input plus human-readable warnings for fields that were left out
    because they could not be parsed (the preview still renders).
    """
    warnings: list[str] = []
    b = data.basics
    cv: dict[str, Any] = {"name": b.name or "Your Name"}
    if b.headline:
        cv["headline"] = b.headline
    if b.location:
        cv["location"] = b.location
    if b.email:
        if _valid(email_validator, b.email):
            cv["email"] = b.email
        else:
            warnings.append("Email address looks invalid, so it was left off.")
    if b.phone:
        phone = b.phone if b.phone.startswith("+") else "+1 " + b.phone
        if _valid(phone_validator, phone):
            cv["phone"] = phone
        else:
            warnings.append("Phone number couldn't be parsed; include the country code, "
                            "e.g. +44 20 7946 0958.")
    if url := _url(b.website):
        if _valid(website_validator, url):
            cv["website"] = url
        else:
            warnings.append("Website URL looks invalid, so it was left off.")
    socials = []
    if handle := _handle(b.linkedin, "linkedin.com"):
        socials.append({"network": "LinkedIn", "username": handle})
    if handle := _handle(b.github, "github.com"):
        socials.append({"network": "GitHub", "username": handle})
    if socials:
        cv["social_networks"] = socials

    sections: dict[str, list[Any]] = {}
    if data.summary:
        sections["Summary"] = [data.summary]

    exp = []
    for e in data.experience:
        if not (e.company or e.position):
            continue
        item: dict[str, Any] = {"company": e.company or " ", "position": e.position or " "}
        if e.location:
            item["location"] = e.location
        item.update(_date_fields(e.start_date, e.end_date, e.current))
        if hl := _nonempty(e.bullets):
            item["highlights"] = hl
        exp.append(item)
    if exp:
        sections["Experience"] = exp

    edu = []
    for ed in data.education:
        if not ed.institution:
            continue
        item = {"institution": ed.institution, "area": ed.area or " "}
        if ed.degree:
            item["degree"] = ed.degree
        if ed.location:
            item["location"] = ed.location
        item.update(_date_fields(ed.start_date, ed.end_date))
        if hl := _nonempty(ed.details):
            item["highlights"] = hl
        edu.append(item)
    if edu:
        sections["Education"] = edu

    projects = []
    for p in data.projects:
        if not p.name:
            continue
        name = p.name
        if (url := _url(p.link)) and _valid(website_validator, url):
            # Markdown link; the engine escapes the URL safely.
            name = f"[{p.name}]({url})"
        item = {"name": name}
        item.update(_date_fields(p.start_date, p.end_date))
        if hl := _nonempty(p.bullets):
            item["highlights"] = hl
        projects.append(item)
    if projects:
        sections["Projects"] = projects

    skills = [
        {"label": s.label, "details": s.details}
        for s in data.skills
        if s.label and s.details
    ]
    if skills:
        sections["Skills"] = skills

    certs = []
    for c in data.certifications:
        if not c.name:
            continue
        line = f"**{c.name}**" + (f", {c.issuer}" if c.issuer else "")
        if c.date:
            line += f" ({c.date})"
        certs.append(line)
    if certs:
        sections["Certifications"] = certs

    if sections:
        cv["sections"] = sections

    tpl = TEMPLATES[data.design.template]
    design: dict[str, Any] = {
        "theme": tpl["theme"],
        "page": {"size": data.design.page_size, "show_footer": False, "show_top_note": False},
    }
    if data.design.accent_color:
        c = data.design.accent_color
        design["colors"] = {"name": c, "section_titles": c, "links": c, "connections": c,
                            "headline": c}
    return {"cv": cv, "design": design, "locale": {"language": "english"}}, warnings


def resume_plain_text(data: ResumeData) -> str:
    """Flatten a resume to plain text (for AI prompts and keyword matching)."""
    b = data.basics
    lines = [b.name, b.headline, b.location]
    if data.summary:
        lines += ["", "SUMMARY", data.summary]
    if data.experience:
        lines += ["", "EXPERIENCE"]
        for i, e in enumerate(data.experience):
            end = "Present" if e.current else e.end_date
            lines.append(f"[{i}] {e.position} at {e.company} ({e.start_date} – {end})")
            lines += [f"  - {x}" for x in _nonempty(e.bullets)]
    if data.projects:
        lines += ["", "PROJECTS"]
        for p in data.projects:
            lines.append(p.name)
            lines += [f"  - {x}" for x in _nonempty(p.bullets)]
    if data.education:
        lines += ["", "EDUCATION"]
        for ed in data.education:
            lines.append(f"{ed.degree} {ed.area}, {ed.institution}".strip())
            lines += [f"  - {x}" for x in _nonempty(ed.details)]
    if data.skills:
        lines += ["", "SKILLS"] + [f"{s.label}: {s.details}" for s in data.skills]
    if data.certifications:
        lines += ["", "CERTIFICATIONS"] + [f"{c.name} {c.issuer}" for c in data.certifications]
    return "\n".join(x for x in lines if x is not None).strip()


def blank_resume(email: str = "") -> ResumeData:
    return ResumeData(
        basics=Basics(email=email),
        experience=[ExperienceItem(bullets=[""])],
        education=[EducationItem()],
        skills=[SkillGroup(label="Languages"), SkillGroup(label="Tools")],
    )


def sample_resume() -> ResumeData:
    """Used for template thumbnails and the landing page."""
    return ResumeData.model_validate({
        "basics": {
            "name": "Alex Morgan", "headline": "Senior Product Engineer",
            "email": "alex.morgan@example.com", "phone": "+1 415 555 0142",
            "location": "San Francisco, CA", "website": "alexmorgan.dev",
            "linkedin": "alexmorgan", "github": "alexmorgan",
        },
        "summary": "Product-minded engineer with 7 years shipping customer-facing web "
                   "platforms. Known for turning ambiguous problems into measurable wins "
                   "across performance, growth and reliability.",
        "experience": [
            {"position": "Senior Software Engineer", "company": "Northwind Labs",
             "location": "San Francisco, CA", "start_date": "2022-03", "current": True,
             "bullets": [
                 "Led redesign of checkout flow, lifting conversion **14%** and adding "
                 "$3.2M in annual revenue",
                 "Cut p95 API latency from 820 ms to 210 ms by introducing a read-through "
                 "cache and query batching",
                 "Mentored 4 engineers; 2 promoted within a year",
             ]},
            {"position": "Software Engineer", "company": "Brightline",
             "location": "Remote", "start_date": "2019-06", "end_date": "2022-02",
             "bullets": [
                 "Built event pipeline processing 40M events/day with 99.99% uptime",
                 "Automated release process, reducing deploy time from 2 hours to 12 minutes",
             ]},
        ],
        "education": [
            {"institution": "University of Michigan", "degree": "BS",
             "area": "Computer Science", "start_date": "2015-09", "end_date": "2019-05",
             "details": ["GPA 3.8/4.0, Dean's List"]},
        ],
        "projects": [
            {"name": "OpenMetrics Dashboard", "start_date": "2023-01",
             "bullets": ["Open-source observability UI with 2.1k GitHub stars"]},
        ],
        "skills": [
            {"label": "Languages", "details": "TypeScript, Python, Go, SQL"},
            {"label": "Platforms", "details": "React, Node.js, PostgreSQL, AWS, Kubernetes"},
        ],
        "certifications": [
            {"name": "AWS Certified Solutions Architect", "issuer": "Amazon", "date": "2023"},
        ],
    })
