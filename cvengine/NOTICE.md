# cvengine

Resume layout engine used by this app. It is a vendored, renamed fork of the
MIT-licensed [rendercv](https://github.com/rendercv/rendercv) project
(schema + Typst renderer only; the CLI was dropped). The upstream copyright
notice is preserved in `LICENSE`, as the MIT license requires.

Pipeline: `dict → pydantic (CVEngineModel) → Jinja2 → Typst source → PDF/PNG`.

Local changes vs. upstream:

- Renamed package and Typst package (`rendercv` → `cvengine`) and removed
  upstream branding, examples and sample template.
- Bundled the `fontawesome` Typst package (upstream uses a git submodule).
- **Multi-tenant hardening**: raw Typst commands/math in user text are escaped
  (`ALLOW_RAW_TYPST = False`), raw HTML in markdown is ignored, code spans and
  link URLs are emitted as escaped string literals, name/title are escaped in the
  preamble, templates load only from the bundled directory, and the markdown
  parser is per-thread instead of a shared global.
