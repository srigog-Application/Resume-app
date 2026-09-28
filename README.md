# Resumora: AI resume builder

A lean, production-ready AI resume builder you can run locally and charge for.

- **Guided builder**: step-by-step form (contact → experience → education → skills → projects → certifications → summary) with a **live preview** that updates as you type.
- **ATS-friendly templates**: 9 single-column, real-text templates. 3 are free, 6 are Pro. Output is typeset with [Typst](https://typst.app), so PDFs are crisp and parse cleanly.
- **AI writing (Claude)**:
  - rewrite one bullet or all bullets of a role for impact
  - write a professional summary
  - **tailor to a pasted job description**: rewritten summary and bullets, skills to add, missing keywords, tips
  - the AI never invents numbers. It inserts highlighted `[X%]` placeholders for you to fill in.
- **Free job-match score**: an instant, offline keyword comparison between the resume and the job post (no AI credits used).
- **Versions**: named snapshots per resume (restore or download any of them), plus "save as tailored copy".
- **PDF export**, with a sensible filename (`Jane_Doe_Resume.pdf`).
- **Accounts and billing**: email/password auth, and a Free/Pro plan through Stripe Checkout, the Customer Portal and webhooks.
- A responsive landing page (features, templates, pricing, FAQ) and a mobile-friendly editor.

The app name is a placeholder. Set `APP_NAME` to rebrand.

---

## Architecture

```
app/                      FastAPI web app
  main.py                 app factory, middleware (sessions, CSRF origin check, security headers)
  config.py               settings from environment / .env
  models.py, db.py        SQLAlchemy models: User, Resume, ResumeVersion, ProcessedStripeEvent
  resume_data.py          the editor's JSON schema, template list, mapping to the engine
  renderer.py             ResumeData → Typst → PDF / PNG preview (sandboxed temp dir per render)
  ai.py                   Claude calls with structured outputs; demo-mode fallback without a key
  keywords.py             offline ATS keyword matching / match score
  plans.py                Free vs Pro limits and AI-credit metering
  routes/                 pages.py (HTML), auth.py, api.py (JSON for the editor), billing.py (Stripe)
  templates/, static/     Jinja pages, CSS, vanilla-JS editor
cvengine/                 resume layout engine, a vendored fork of rendercv (see below)
tests/                    pytest suite (auth, resumes, versions, limits, AI, billing, engine security)
scripts/gen_thumbnails.py regenerates template preview images
Dockerfile, render.yaml   deployment
```

**Stack:** Python 3.12, FastAPI, SQLAlchemy (SQLite locally, Postgres in production), Typst via `typst-py`, Anthropic Python SDK, Stripe. There is no JS build step: the frontend is server-rendered HTML plus one vanilla JS file.

### About `cvengine` (built on rendercv)

The PDF engine is a vendored, renamed fork of the MIT-licensed [rendercv](https://github.com/rendercv/rendercv): its Pydantic schema, Jinja→Typst templates and themes. The CLI was dropped and the branding removed. The upstream MIT copyright notice is kept in `cvengine/LICENSE`, as the license requires. rendercv was designed as a single-user CLI, so the fork was **hardened for multi-tenant use**:

- raw Typst commands and math in user text are escaped instead of executed
- raw HTML in markdown is ignored
- link URLs and code spans are emitted as escaped string literals
- templates load only from the bundled directory
- the markdown parser is per-thread, so concurrent renders don't mix content

Each render compiles in its own empty temp directory, so Typst can't read other files. `tests/test_engine.py` covers the injection cases. Details are in `cvengine/NOTICE.md`.

---

## Run locally

Requirements: Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                                  # install dependencies
cp .env.example .env                     # optional: add keys (everything works without them)
uv run uvicorn app.main:app --reload     # http://localhost:8000
```

Without any keys:

- **AI runs in demo mode**, using simple labelled heuristics so you can try every flow.
- **Billing is disabled**. The Upgrade button explains what to configure.
- **SQLite** is used at `./data/app.db`.

To give yourself Pro locally without Stripe:

```bash
sqlite3 data/app.db "update users set plan='pro' where email='you@example.com'"
```

Run the tests and the linter:

```bash
uv run pytest
uv run ruff check .
```

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | **prod** | Signs session cookies. Generate with `python -c "import secrets; print(secrets.token_urlsafe(48))"`. In development a random key is used, so sessions reset on restart. |
| `ENVIRONMENT` | prod | Set to `production` for Secure cookies and HSTS, and to require `SECRET_KEY`. |
| `DATABASE_URL` | prod | Postgres URL (`postgres://`, `postgresql://` and `postgresql+psycopg://` all work). Defaults to SQLite. |
| `BASE_URL` | prod | Public URL, used for Stripe redirect URLs. On Render, `RENDER_EXTERNAL_URL` is used automatically. |
| `APP_NAME` | no | Brand name shown in the UI (default `Resumora`). |
| `ANTHROPIC_API_KEY` | for AI | From [console.anthropic.com](https://console.anthropic.com/settings/keys). Without it, AI runs in demo mode. |
| `ANTHROPIC_MODEL` | no | Default `claude-opus-5`. |
| `STRIPE_SECRET_KEY` | for billing | `sk_test_…` in test mode. |
| `STRIPE_PRICE_ID` | for billing | The recurring Price for Pro (`price_…`). |
| `STRIPE_WEBHOOK_SECRET` | for billing | `whsec_…` from the webhook endpoint or the `stripe listen` output. |
| `PRO_PRICE_LABEL` | no | Price shown on the pricing page (default `$12`). Keep it in sync with your Stripe price. |
| `WEB_CONCURRENCY` | no | Uvicorn workers in Docker (default 2). |

Plan limits (resumes, versions, AI credits, which templates are free) live in `app/plans.py` and `app/resume_data.py`.

---

## Stripe setup (test mode)

1. In the Stripe Dashboard, switch to **Test mode**.
2. **Product catalog → Add product**: "Pro", recurring, for example $12/month. Copy the **Price ID** (`price_…`) into `STRIPE_PRICE_ID`.
3. **Developers → API keys**: copy the secret key (`sk_test_…`) into `STRIPE_SECRET_KEY`.
4. **Settings → Billing → Customer portal**: activate it (needed for "Manage subscription").
5. Webhooks:
   - **Locally**, with the [Stripe CLI](https://stripe.com/docs/stripe-cli):
     ```bash
     stripe listen --forward-to localhost:8000/billing/webhook
     ```
     Put the printed `whsec_…` into `STRIPE_WEBHOOK_SECRET`.
   - **In production**, go to Developers → Webhooks → Add endpoint `https://YOUR_DOMAIN/billing/webhook` with the events `checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated` and `customer.subscription.deleted`, then copy the signing secret.
6. Pay with the test card `4242 4242 4242 4242`, any future expiry, any CVC.

The success page syncs the plan immediately. The webhook is the source of truth for renewals, failed payments and cancellations. Events are de-duplicated by ID.

When you go live, repeat these steps in live mode and swap in the live keys.

---

## Deploy

### Option A: Render (Blueprint, recommended)

`render.yaml` defines a Docker web service plus a managed Postgres database.

1. Push this repo to GitHub.
2. In Render: **New → Blueprint**, then pick the repo. Render creates `resume-app` and `resume-db`, generates `SECRET_KEY`, and wires `DATABASE_URL`.
3. When prompted, fill in `ANTHROPIC_API_KEY`, `STRIPE_SECRET_KEY`, `STRIPE_PRICE_ID` and `STRIPE_WEBHOOK_SECRET`. You can add the webhook secret after step 4.
4. Once it's live, add the Stripe webhook endpoint `https://<your-service>.onrender.com/billing/webhook` (see above) and set its secret.
5. Optional: add a custom domain under Settings → Custom Domains. If you do, set `BASE_URL` to it.

The blueprint uses the `starter` web plan and the `basic-256mb` Postgres plan. `free` works for a demo, but it sleeps when idle, and the free database expires after 30 days.

### Option B: any Docker host (Fly.io, Railway, a VPS…)

```bash
docker build -t resume-app .
docker run -p 8000:8000 \
  -e SECRET_KEY=... -e DATABASE_URL=postgres://... -e BASE_URL=https://your.domain \
  -e ANTHROPIC_API_KEY=... -e STRIPE_SECRET_KEY=... -e STRIPE_PRICE_ID=... -e STRIPE_WEBHOOK_SECRET=... \
  resume-app
```

Put it behind HTTPS. The container honours `X-Forwarded-*` headers and listens on `$PORT`. The health check is at `/healthz`. Tables are created automatically on first boot.

---

## Known limitations and next steps

Before scaling, consider these. None of them are needed to start charging.

- **No password reset or email verification** yet. Add a transactional email provider (Postmark, Resend, SES).
- **No login rate limiting**. Add one at the proxy or with a small middleware, or put Cloudflare in front.
- **Schema changes**: tables are created with `create_all`. Introduce Alembic before your first schema change in production.
- **AI costs**: each AI action is one Claude call. Tune `ai_credits_per_month` in `app/plans.py`, or set `ANTHROPIC_MODEL` to a cheaper model.
- Phone numbers without a `+country` prefix are assumed to be US numbers.
- Import from an existing PDF or LinkedIn, and cover letters, are natural next features.

## License

App code: yours. `cvengine/` stays under its upstream MIT license (see `cvengine/LICENSE`).
