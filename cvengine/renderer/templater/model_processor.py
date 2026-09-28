import pathlib
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Literal

from cvengine.exception import CVEngineUserError
from cvengine.schema.models.cv.section import Entry
from cvengine.schema.models.cvengine_model import CVEngineModel

from .connections import compute_connections
from .date import build_date_placeholders, date_object_to_string
from .entry_templates_from_input import render_entry_templates
from .footer_and_top_note import render_footer_template, render_top_note_template
from .markdown_parser import markdown_to_typst
from .string_processor import (
    apply_string_processors,
    make_keywords_bold,
    substitute_placeholders,
)


def download_photo_from_url(cvengine_model: CVEngineModel) -> None:
    """Download photo from URL to output directory and update model to local path.

    Why:
        Templates and Typst compiler require cv.photo to be a local pathlib.Path.
        When user provides a URL, this downloads the image before template
        rendering, preserving the local-path invariant for all downstream code.

    Args:
        cvengine_model: CV model whose photo URL will be downloaded in-place.
    """
    if cvengine_model.cv.photo is None or isinstance(
        cvengine_model.cv.photo, pathlib.Path
    ):
        return

    url_str = str(cvengine_model.cv.photo)

    parsed = urllib.parse.urlparse(url_str)
    filename = pathlib.PurePosixPath(parsed.path).name
    if not filename or "." not in filename:
        filename = "photo.jpg"

    output_dir = cvengine_model.settings.render_command.output_folder
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / filename

    if not destination.exists():
        try:
            with urllib.request.urlopen(url_str, timeout=30) as response:
                destination.write_bytes(response.read())
        except (urllib.error.URLError, OSError) as e:
            raise CVEngineUserError(
                message=f"Failed to download photo from {url_str}: {e}"
            ) from e

    cvengine_model.cv.photo = destination


def process_model(
    cvengine_model: CVEngineModel, file_type: Literal["typst", "markdown"]
) -> CVEngineModel:
    """Pre-process CV model for template rendering with format-specific transformations.

    Why:
        Templates need processed data, not raw model. This applies markdown
        parsing, keyword bolding, connection formatting, date rendering, and
        entry template expansion before templates execute.

    Args:
        cvengine_model: Validated CV model.
        file_type: Target format for format-specific processors.

    Returns:
        Processed model ready for templates.
    """
    cvengine_model = cvengine_model.model_copy(deep=True)

    string_processors: list[Callable[[str], str]] = [
        lambda string: make_keywords_bold(string, cvengine_model.settings.bold_keywords)
    ]
    if file_type == "typst":
        string_processors.extend([markdown_to_typst])

    cvengine_model.cv._plain_name = cvengine_model.cv.name
    cvengine_model.cv.name = apply_string_processors(
        cvengine_model.cv.name, string_processors
    )
    cvengine_model.cv.headline = apply_string_processors(
        cvengine_model.cv.headline, string_processors
    )
    cvengine_model.cv._connections = compute_connections(cvengine_model, file_type)
    cvengine_model.cv._top_note = render_top_note_template(
        cvengine_model.design.templates.top_note,
        locale=cvengine_model.locale,
        current_date=cvengine_model.settings._resolved_current_date,
        name=cvengine_model.cv.name,
        single_date_template=cvengine_model.design.templates.single_date,
        string_processors=string_processors,
    )

    cvengine_model.cv._footer = render_footer_template(
        cvengine_model.design.templates.footer,
        locale=cvengine_model.locale,
        current_date=cvengine_model.settings._resolved_current_date,
        name=cvengine_model.cv.name,
        single_date_template=cvengine_model.design.templates.single_date,
        string_processors=string_processors,
    )

    pdf_title_placeholders: dict[str, str] = {
        "CURRENT_DATE": date_object_to_string(
            cvengine_model.settings._resolved_current_date,
            locale=cvengine_model.locale,
            single_date_template=cvengine_model.design.templates.single_date,
        ),
        "NAME": cvengine_model.cv._plain_name or "",
        **build_date_placeholders(
            cvengine_model.settings._resolved_current_date, locale=cvengine_model.locale
        ),
    }
    cvengine_model.settings.pdf_title = substitute_placeholders(
        cvengine_model.settings.pdf_title, pdf_title_placeholders
    )

    if cvengine_model.cv.sections is None:
        return cvengine_model

    for section in cvengine_model.cv.cvengine_sections:
        section.title = apply_string_processors(section.title, string_processors)
        show_time_span = (
            section.snake_case_title
            in cvengine_model.design.sections.show_time_spans_in
        )
        for i, entry in enumerate(section.entries):
            processed_entry = render_entry_templates(
                entry,
                templates=cvengine_model.design.templates,
                locale=cvengine_model.locale,
                show_time_span=show_time_span,
                current_date=cvengine_model.settings._resolved_current_date,
            )
            section.entries[i] = process_fields(processed_entry, string_processors)

    return cvengine_model


def process_fields(
    entry: Entry, string_processors: list[Callable[[str], str]]
) -> Entry:
    """Apply string processors to all entry fields except skipped technical fields.

    Why:
        Entry fields need markdown parsing and formatting, but dates, DOIs, and
        URLs must remain unprocessed for correct linking and formatting. Field-
        level processing enables selective transformation.

    Args:
        entry: Entry to process (model or string).
        string_processors: Transformation functions to apply.

    Returns:
        Entry with processed fields.
    """
    skipped = {"start_date", "end_date", "doi", "url"}

    if isinstance(entry, str):
        return apply_string_processors(entry, string_processors)

    data = entry.model_dump(exclude_none=True)
    for field, value in data.items():
        if field in skipped or field.startswith("_"):
            continue

        if isinstance(value, str):
            setattr(entry, field, apply_string_processors(value, string_processors))
        elif isinstance(value, list):
            setattr(
                entry,
                field,
                [apply_string_processors(v, string_processors) for v in value],
            )
        else:
            setattr(
                entry, field, apply_string_processors(str(value), string_processors)
            )

    return entry
