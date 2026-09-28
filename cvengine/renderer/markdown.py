import pathlib

from cvengine.schema.models.cvengine_model import CVEngineModel

from .path_resolver import resolve_cvengine_file_path
from .templater.templater import render_full_template


def generate_markdown(cvengine_model: CVEngineModel) -> pathlib.Path | None:
    """Generate Markdown file from CV model via Jinja2 templates.

    Why:
        Markdown provides human-readable CV format for version control and
        web platforms. Acts as intermediate format for HTML generation.

    Args:
        cvengine_model: Validated CV model with content.

    Returns:
        Path to generated Markdown file, or None if generation disabled.
    """
    if cvengine_model.settings.render_command.dont_generate_markdown:
        return None
    markdown_path = resolve_cvengine_file_path(
        cvengine_model, cvengine_model.settings.render_command.markdown_path
    )
    markdown_contents = render_full_template(cvengine_model, "markdown")
    markdown_path.write_text(markdown_contents, encoding="utf-8")
    return markdown_path
