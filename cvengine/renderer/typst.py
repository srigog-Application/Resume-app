import pathlib

from cvengine.schema.models.cvengine_model import CVEngineModel

from .path_resolver import resolve_cvengine_file_path
from .templater.templater import render_full_template


def generate_typst(cvengine_model: CVEngineModel) -> pathlib.Path | None:
    """Generate Typst source file from CV model via Jinja2 templates.

    Why:
        Typst is the intermediate format before PDF/PNG compilation. Templates
        convert validated model data to Typst markup with proper formatting,
        fonts, and styling from design options.

    Args:
        cvengine_model: Validated CV model with content and design.

    Returns:
        Path to generated Typst file, or None if generation disabled.
    """
    if cvengine_model.settings.render_command.dont_generate_typst:
        return None
    typst_path = resolve_cvengine_file_path(
        cvengine_model, cvengine_model.settings.render_command.typst_path
    )
    typst_contents = render_full_template(cvengine_model, "typst")
    typst_path.write_text(typst_contents, encoding="utf-8")
    return typst_path
