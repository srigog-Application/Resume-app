"""The rendering engine must treat all user text as text, never as Typst code."""

import threading

import pytest

from app.renderer import render_pdf
from app.resume_data import TEMPLATES, ResumeData, sample_resume, to_engine_input

EVIL = [
    '#panic("pwned")',
    '$$#panic("pwned")$$',
    '`a`#panic("pwned")`b`',
    '[link](https://a.com"+panic("pwned")+")',
    '<b>#panic("pwned")</b>',
    'x", footer: panic("pwned"), y: "',
    '#read("/etc/passwd")',
    "C# & C++ 100% <tag> @me ~ _x_ \\ *star* ] [ } {",
]


@pytest.mark.parametrize("evil", EVIL)
def test_user_text_cannot_execute_typst(evil):
    data = sample_resume()
    data.basics.name = evil
    data.basics.headline = evil
    data.summary = evil
    data.experience[0].company = evil
    data.experience[0].bullets = [evil]
    data.skills[0].details = evil
    data.projects[0].name = evil
    # A successful compile proves no panic() ran; an injected call would abort it.
    assert render_pdf(data).content.startswith(b"%PDF")


@pytest.mark.parametrize("template", list(TEMPLATES))
def test_every_template_renders(template):
    data = sample_resume()
    data.design.template = template
    data.design.accent_color = "#0f766e"
    assert render_pdf(data).content.startswith(b"%PDF")


def test_empty_resume_renders():
    assert render_pdf(ResumeData()).content.startswith(b"%PDF")


def test_concurrent_renders_do_not_mix_content():
    results, errors = {}, []

    def work(i):
        try:
            data = sample_resume()
            data.basics.name = f"Person Number {i}"
            data.summary = f"Unique summary {i} " * 5
            engine_input, _ = to_engine_input(data)
            from cvengine.renderer.templater.templater import render_full_template
            from cvengine.schema.cvengine_model_builder import (
                build_cvengine_model_from_commented_map,
            )
            src = render_full_template(build_cvengine_model_from_commented_map(engine_input),
                                       "typst")
            results[i] = src
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    for i, src in results.items():
        assert f"Unique summary {i} " in src
        assert all(f"Unique summary {j} " not in src for j in results if j != i)


def test_linkedin_and_website_normalisation():
    data = sample_resume()
    data.basics.linkedin = "https://www.linkedin.com/in/jane-doe/"
    data.basics.github = "@janedoe"
    data.basics.website = "janedoe.dev"
    engine_input, warnings = to_engine_input(data)
    cv = engine_input["cv"]
    assert {"network": "LinkedIn", "username": "jane-doe"} in cv["social_networks"]
    assert {"network": "GitHub", "username": "janedoe"} in cv["social_networks"]
    assert cv["website"] == "https://janedoe.dev"
    assert warnings == []
