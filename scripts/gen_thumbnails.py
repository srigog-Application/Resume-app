"""Regenerate the template preview images used on the landing page and editor.

    uv run python scripts/gen_thumbnails.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.renderer import render_png_pages
from app.resume_data import TEMPLATES, sample_resume

OUT = pathlib.Path(__file__).resolve().parent.parent / "app" / "static" / "img" / "templates"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for key in TEMPLATES:
        data = sample_resume()
        data.design.template = key
        page = render_png_pages(data, ppi=72).content[0]
        (OUT / f"{key}.png").write_bytes(page)
        print("wrote", key)


if __name__ == "__main__":
    main()
