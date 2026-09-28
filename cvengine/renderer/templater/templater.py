import contextlib
import functools
import pathlib
from typing import Literal

import jinja2

from cvengine.schema.models.cvengine_model import CVEngineModel

from .markdown_parser import escape_typst_string_literal, markdown_to_html
from .model_processor import download_photo_from_url, process_model
from .string_processor import clean_url

templates_directory = pathlib.Path(__file__).parent / "templates"


@functools.lru_cache(maxsize=1)
def get_jinja2_environment(
    input_file_path: pathlib.Path | None = None,
) -> jinja2.Environment:
    """Create cached Jinja2 environment with custom filters and template loaders.

    Why:
        Template rendering is called multiple times per render. Caching environment
        prevents repeated filesystem scans. Loader hierarchy enables user template
        overrides by checking input file directory before built-in templates.

    Args:
        input_file_path: Path to input file for user template override resolution.

    Returns:
        Configured Jinja2 environment with filters and loaders.
    """
    env = jinja2.Environment(
        # Web-app hardening: only ever load the bundled templates (upstream also
        # searched the working directory for user overrides).
        loader=jinja2.FileSystemLoader([templates_directory]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["clean_url"] = clean_url
    env.filters["strip"] = lambda string: string.strip()
    env.filters["typst_string"] = escape_typst_string_literal
    return env


def render_full_template(
    cvengine_model: CVEngineModel, file_type: Literal["typst", "markdown"]
) -> str:
    """Render complete CV document by assembling preamble, header, and sections.

    Why:
        CV generation requires consistent structure across formats. This orchestrates
        model processing, template rendering for each component, and assembly into
        final document following proper order.

    Example:
        ```py
        typst_document = render_full_template(cvengine_model, "typst")
        # Returns complete .typ file with preamble, header, and all sections

        markdown_document = render_full_template(cvengine_model, "markdown")
        # Returns complete .md file with header and all sections
        ```

    Args:
        cvengine_model: CV model to render.
        file_type: Output format for template selection and processing.

    Returns:
        Complete rendered document as string.
    """
    extension = {
        "typst": "typ",
        "markdown": "md",
    }[file_type]

    download_photo_from_url(cvengine_model)
    cvengine_model = process_model(cvengine_model, file_type)

    header = render_single_template(
        file_type,
        f"Header.j2.{extension}",
        cvengine_model,
    )
    if file_type == "typst":
        preamble = render_single_template(
            file_type,
            f"Preamble.j2.{extension}",
            cvengine_model,
        )
        code = f"{preamble}\n\n{header}\n"
    else:
        code = f"{header}\n"

    for cvengine_section in cvengine_model.cv.cvengine_sections:
        section_beginning = render_single_template(
            file_type,
            f"SectionBeginning.j2.{extension}",
            cvengine_model,
            section_title=cvengine_section.title,
            snake_case_section_title=cvengine_section.snake_case_title,
            entry_type=cvengine_section.entry_type,
        )
        section_ending = render_single_template(
            file_type,
            f"SectionEnding.j2.{extension}",
            cvengine_model,
            entry_type=cvengine_section.entry_type,
        )
        entry_codes = []
        for entry in cvengine_section.entries:
            entry_code = render_single_template(
                file_type,
                f"entries/{cvengine_section.entry_type}.j2.{extension}",
                cvengine_model,
                entry=entry,
            )
            entry_codes.append(entry_code)
        entries_code = "\n\n".join(entry_codes)
        section_code = f"{section_beginning}\n{entries_code}\n{section_ending}"
        code += f"\n{section_code}"

    return code


def render_html(cvengine_model: CVEngineModel, markdown: str) -> str:
    """Convert Markdown to HTML and wrap with full HTML template.

    Why:
        HTML output requires both content conversion (Markdown to HTML body) and
        document structure (head, CSS, metadata). Separate function handles HTML-
        specific workflow distinct from Typst/Markdown direct generation.

    Example:
        ```py
        markdown_content = render_full_template(cvengine_model, "markdown")
        html_document = render_html(cvengine_model, markdown_content)
        # Returns complete HTML with <head>, CSS, and converted Markdown body
        ```

    Args:
        cvengine_model: CV model for template context.
        markdown: Markdown content to convert.

    Returns:
        Complete HTML document.
    """
    html_body = markdown_to_html(markdown)
    return render_single_template(
        "html", "Full.html", cvengine_model, html_body=html_body
    )


def render_single_template(
    file_type: Literal["markdown", "typst", "html"],
    relative_template_path: str,
    cvengine_model: CVEngineModel,
    **kwargs,
) -> str:
    """Render single Jinja2 template with user override support. Arbitrary keyword
    arguments may be passed to the template as additional template variables.

    Why:
        Users can override built-in templates by placing custom templates in
        theme folder alongside input file. Typst templates check theme-specific
        location first, falling back to built-in templates if not found.

    Example:
        ```py
        header = render_single_template("typst", "Header.j2.typ", cvengine_model)
        # First checks for classic/Header.j2.typ in input file directory
        # Falls back to built-in typst/Header.j2.typ if not found

        section = render_single_template(
            "typst",
            "SectionBeginning.j2.typ",
            cvengine_model,
            section_title="Experience",
        )
        ```

    Args:
        file_type: Format for template directory selection.
        relative_template_path: Template file path relative to format directory.
        cvengine_model: CV model providing template context.

    Returns:
        Rendered template as string.
    """
    jinja2_environment = get_jinja2_environment(cvengine_model._input_file_path)
    template = None
    if file_type == "typst":
        # Try user's own Typst templates first:
        with contextlib.suppress(jinja2.TemplateNotFound):
            template = jinja2_environment.get_template(
                f"{cvengine_model.design.theme}/{relative_template_path}"
            )

    if template is None:
        template = jinja2_environment.get_template(
            f"{file_type}/{relative_template_path}"
        )

    return template.render(
        cv=cvengine_model.cv,
        design=cvengine_model.design,
        locale=cvengine_model.locale,
        settings=cvengine_model.settings,
        **kwargs,
    )
