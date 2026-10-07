"""Render a ResumeData document to PDF / PNG via the vendored engine."""

import pathlib
import re
import tempfile
from dataclasses import dataclass, field

import rendercv_fonts
import typst

from cvengine.exception import CVEngineUserValidationError
from cvengine.renderer.pdf_png import get_package_path
from cvengine.renderer.templater.templater import render_full_template
from cvengine.schema.cvengine_model_builder import build_cvengine_model_from_commented_map

from .resume_data import ResumeData, to_engine_input


class RenderError(Exception):
    pass


@dataclass
class RenderResult:
    content: bytes | list[bytes]
    warnings: list[str] = field(default_factory=list)


def _typst_source(data: ResumeData) -> tuple[str, list[str]]:
    engine_input, warnings = to_engine_input(data)
    try:
        model = build_cvengine_model_from_commented_map(engine_input)
    except CVEngineUserValidationError as e:
        errors = [
            err for err in e.validation_errors if "problems with the entries" not in err.message
        ] or e.validation_errors
        messages = "; ".join(_describe(err) for err in errors)
        raise RenderError(f"Please fix: {messages}") from e
    return render_full_template(model, "typst"), warnings


def _describe(err) -> str:
    loc = [p for p in (err.schema_location or ()) if p not in ("cv", "sections")]
    # e.g. ("Experience", "0", "start_date") -> "Experience #1 start date"
    words = []
    for part in loc:
        words.append(f"#{int(part) + 1}" if part.isdigit() else part.replace("_", " "))
    where = " ".join(words) or "resume"
    return f"{where}: {err.message}"


def _compile(source: str, fmt: str, ppi: float | None = None) -> bytes | list[bytes]:
    # Each render gets its own sandbox directory: Typst can only read files
    # under `root`, and that directory contains nothing but this resume.
    with tempfile.TemporaryDirectory(prefix="resume-") as tmp:
        root = pathlib.Path(tmp)
        (root / "resume.typ").write_text(source, encoding="utf-8")
        compiler = typst.Compiler(
            root=root,
            font_paths=rendercv_fonts.paths_to_font_folders,
            package_path=get_package_path(),
        )
        kwargs = {"ppi": ppi} if ppi else {}
        try:
            return compiler.compile(input=root / "resume.typ", format=fmt, **kwargs)
        except Exception as e:  # typst raises its own error types
            raise RenderError("The resume could not be typeset.") from e


def render_pdf(data: ResumeData) -> RenderResult:
    source, warnings = _typst_source(data)
    pdf = _compile(source, "pdf")
    assert isinstance(pdf, bytes)
    return RenderResult(pdf, warnings)


def render_png_pages(data: ResumeData, ppi: float = 110) -> RenderResult:
    source, warnings = _typst_source(data)
    pages = _compile(source, "png", ppi=ppi)
    if isinstance(pages, bytes):
        pages = [pages]
    return RenderResult([p for p in pages if p], warnings)


def pdf_filename(data: ResumeData, suffix: str = "") -> str:
    base = re.sub(r"[^A-Za-z0-9]+", "_", data.basics.name or "Resume").strip("_") or "Resume"
    suffix = re.sub(r"[^A-Za-z0-9]+", "_", suffix).strip("_")
    return f"{base}_Resume{'_' + suffix if suffix else ''}.pdf"


# ---------------------------------------------------------------- cover letters

LETTER_TEMPLATE = """\
#let d = json("letter.json")
#set document(title: d.title)
#set page(paper: d.paper, margin: (x: 1in, y: 0.9in))
#set text(font: "Source Sans 3", size: 11pt, fill: rgb("#1f2328"))
#set par(justify: false, leading: 0.7em, spacing: 1.1em)
#text(size: 20pt, weight: "bold", fill: rgb(d.accent))[#d.name]
#if d.contact != "" [ #v(-0.5em) #text(size: 9.5pt, fill: rgb("#57606a"))[#d.contact] ]
#line(length: 100%, stroke: 0.6pt + rgb(d.accent))
#v(0.6em)
#text(size: 10pt, fill: rgb("#57606a"))[#d.date]
#v(0.4em)
#for p in d.paragraphs [ #par[#p] ]
"""


def render_letter_pdf(body: str, data: ResumeData, title: str, date: str) -> bytes:
    """Typeset a cover letter. Text is passed as JSON data, never as Typst markup."""
    import json

    b = data.basics
    contact = " · ".join(x for x in (b.email, b.phone, b.location) if x)
    paragraphs = [p.strip() for p in body.replace("\r", "").split("\n\n") if p.strip()]
    payload = {
        "title": title[:200] or "Cover letter",
        "name": b.name or "",
        "contact": contact,
        "date": date,
        "paragraphs": paragraphs or [""],
        "accent": data.design.accent_color or "#004f90",
        "paper": data.design.page_size,
    }
    with tempfile.TemporaryDirectory(prefix="letter-") as tmp:
        root = pathlib.Path(tmp)
        (root / "letter.typ").write_text(LETTER_TEMPLATE, encoding="utf-8")
        (root / "letter.json").write_text(json.dumps(payload), encoding="utf-8")
        compiler = typst.Compiler(root=root, font_paths=rendercv_fonts.paths_to_font_folders)
        try:
            pdf = compiler.compile(input=root / "letter.typ", format="pdf")
        except Exception as e:
            raise RenderError("The cover letter could not be typeset.") from e
    assert isinstance(pdf, bytes)
    return pdf
