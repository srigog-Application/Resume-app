"""Import, analysis, coach chat, cover letters, job tracker, Elite billing."""

import io
from types import SimpleNamespace

import docx
from conftest import first_resume_id, get_user, set_user, signup, used

from app import ai, ai_features
from app.resume_data import sample_resume

RESUME_TEXT = """Jordan Lee
Data Analyst
jordan@example.com | +1 312 555 0100 | linkedin.com/in/jordanlee

SUMMARY
Analyst with 4 years turning messy data into decisions for marketing teams.

EXPERIENCE
Data Analyst at Globex
• Built weekly revenue dashboards in Tableau used by 40 managers
• Responsible for SQL reporting
Junior Analyst at Initech
- Cleaned CRM data

EDUCATION
University of Illinois
• BS Statistics

SKILLS
Languages: SQL, Python
Tools: Tableau, Excel
"""

JD = ("We are hiring a Data Analyst to build dashboards in Tableau and Looker, write complex SQL "
      "in Snowflake, run A/B tests and partner with Marketing. Python and dbt preferred.")


def _docx_bytes(text: str) -> bytes:
    d = docx.Document()
    for line in text.splitlines():
        d.add_paragraph(line)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


# ------------------------------------------------------------------ import


def test_import_docx_creates_resume(user_client):
    r = user_client.post("/api/resumes/import", files={
        "file": ("jordan.docx", _docx_bytes(RESUME_TEXT),
                 "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title"] == "jordan" and body["url"].endswith("#analysis")

    page = user_client.get(f"/app/resumes/{body['id']}")
    assert "Jordan Lee" in page.text and "Globex" in page.text and "Tableau" in page.text


def test_import_rejects_bad_files(user_client):
    r = user_client.post("/api/resumes/import", files={"file": ("x.exe", b"MZ\x00\x01", "x")})
    assert r.status_code == 422
    r = user_client.post("/api/resumes/import", files={"file": ("x.pdf", b"%PDF-garbage", "x")})
    assert r.status_code == 422
    r = user_client.post("/api/resumes/import", files={"file": ("x.txt", b"too short", "x")})
    assert r.status_code == 502


def test_import_respects_resume_limit(user_client):
    rid = first_resume_id(user_client)
    for t in ("a", "b"):
        user_client.post(f"/api/resumes/{rid}/duplicate", json={"title": t})
    r = user_client.post("/api/resumes/import",
                         files={"file": ("r.txt", RESUME_TEXT.encode(), "text/plain")})
    assert r.status_code == 402


def test_demo_import_parser():
    data = ai_features._demo_import(RESUME_TEXT)
    assert data.basics.name == "Jordan Lee"
    assert data.basics.email == "jordan@example.com"
    assert data.experience[0].company == "Globex"
    assert len(data.experience[0].bullets) == 2
    assert {s.label for s in data.skills} == {"Languages", "Tools"}


# ------------------------------------------------------------------ analysis


def test_ats_check_is_free_and_flags_issues(user_client):
    data = sample_resume().model_dump()
    data["experience"][0]["bullets"] = ["Responsible for stuff", "I helped the team"]
    r = user_client.post("/api/ats-check", json={"data": data}).json()
    failed = {c["id"] for c in r["checks"] if not c["passed"]}
    assert {"verbs", "pronouns"} <= failed
    assert 0 < r["score"] < 100
    assert used(user_client.email, "analysis") == 0


def test_ai_analysis_is_metered(user_client):
    data = sample_resume().model_dump()
    for i in range(3):
        r = user_client.post("/api/ai/analysis", json={"data": data, "job_description": JD})
        assert r.status_code == 200
        assert r.json()["analysis_left"] == 2 - i
    assert "checks" in r.json() and r.json()["sections"]
    r = user_client.post("/api/ai/analysis", json={"data": data})
    assert r.status_code == 402 and "Pro" in r.json()["detail"]

    set_user(user_client.email, plan="elite")
    r = user_client.post("/api/ai/analysis", json={"data": data})
    assert r.status_code == 200 and r.json()["analysis_left"] is None


# ------------------------------------------------------------------ coach chat


def test_chat_flow_and_apply_edit(user_client):
    rid = first_resume_id(user_client)
    user_client.put(f"/api/resumes/{rid}", json={"data": sample_resume().model_dump()})

    r = user_client.post(f"/api/resumes/{rid}/chat", json={"message": "Improve my top role"})
    assert r.status_code == 200
    edit = r.json()["assistant"]["edits"][0]
    assert edit["kind"] == "experience_bullets"

    hist = user_client.get(f"/api/resumes/{rid}/chat").json()
    assert [m["role"] for m in hist["messages"]] == ["user", "assistant"]
    assert hist["credits_left"] == 19

    applied = user_client.post(f"/api/resumes/{rid}/apply-edit", json={"edit": edit}).json()
    assert applied["data"]["experience"][0]["bullets"] == edit["items"]

    bad = dict(edit, index=42)
    assert user_client.post(f"/api/resumes/{rid}/apply-edit",
                            json={"edit": bad}).status_code == 409

    user_client.delete(f"/api/resumes/{rid}/chat")
    assert user_client.get(f"/api/resumes/{rid}/chat").json()["messages"] == []


def test_apply_edit_kinds():
    data = sample_resume()
    E = ai_features.ResumeEdit
    d = ai_features.apply_edit(data, E(kind="summary", index=-1, label="", text="New", items=[],
                                       reason=""))
    assert d.summary == "New" and data.summary != "New"  # original untouched
    d = ai_features.apply_edit(data, E(kind="skill_group", index=-1, label="Cloud",
                                       text="AWS, GCP", items=[], reason=""))
    assert any(s.label == "Cloud" and s.details == "AWS, GCP" for s in d.skills)
    d = ai_features.apply_edit(data, E(kind="skill_group", index=-1, label="languages",
                                       text="Rust", items=[], reason=""))
    assert next(s for s in d.skills if s.label == "Languages").details == "Rust"


def test_chat_sends_history_to_claude(monkeypatch, override_settings):
    override_settings(anthropic_api_key="sk-test", anthropic_model="claude-opus-5")
    calls = []

    class Msgs:
        def parse(self, **kw):
            calls.append(kw)
            return SimpleNamespace(stop_reason="end_turn", parsed_output=ai_features.ChatReply(
                reply="What metric?", edits=[ai_features.ResumeEdit(
                    kind="experience_bullets", index=99, label="", text="", items=["x"],
                    reason="bad index")]))

    monkeypatch.setattr(ai, "_client", lambda: SimpleNamespace(beta=SimpleNamespace(
        messages=Msgs())))
    history = [{"role": "assistant", "content": "orphan"},
               {"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    reply = ai_features.chat(sample_resume(), history, "Improve it", JD)
    assert reply.edits == []  # out-of-range edit dropped
    msgs = calls[0]["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert "<resume>" in msgs[-1]["content"] and "<job_description>" in msgs[-1]["content"]
    assert "clarifying" in calls[0]["system"]


# ------------------------------------------------------------------ jobs


def test_job_tracker_crud_and_isolation(client):
    client.email = signup(client)
    rid = first_resume_id(client)
    r = client.post("/api/jobs", json={"company": "Acme", "title": "Analyst",
                                       "url": "acme.com/jobs/1", "description": JD,
                                       "resume_id": rid})
    assert r.status_code == 200
    job = r.json()
    assert job["url"] == "https://acme.com/jobs/1" and job["applied_at"] is None

    moved = client.patch(f"/api/jobs/{job['id']}/status", json={"status": "interviewing"})
    assert moved.json()["status"] == "interviewing" and moved.json()["applied_at"]
    assert client.patch(f"/api/jobs/{job['id']}/status",
                        json={"status": "hired!"}).status_code == 422
    assert client.post("/api/jobs", json={"company": "", "title": ""}).status_code == 422
    assert client.get("/app/jobs").status_code == 200

    client.post("/logout")
    signup(client)
    assert client.put(f"/api/jobs/{job['id']}", json={"company": "x"}).status_code == 404
    assert client.delete(f"/api/jobs/{job['id']}").status_code == 404
    # Can't link someone else's resume either.
    assert client.post("/api/jobs", json={"company": "x", "resume_id": rid}).status_code == 404


# ------------------------------------------------------------------ cover letters


def test_cover_letter_generate_edit_pdf(user_client):
    rid = first_resume_id(user_client)
    user_client.put(f"/api/resumes/{rid}", json={"data": sample_resume().model_dump()})
    job = user_client.post("/api/jobs", json={"company": "Acme", "title": "Engineer",
                                               "description": JD}).json()

    r = user_client.post("/api/letters/generate", json={"resume_id": rid, "job_id": job["id"]})
    assert r.status_code == 200, r.text
    letter = r.json()
    assert letter["title"] == "Acme · Engineer" and "Acme" in letter["body"]
    assert letter["left"] == 2

    saved = user_client.put(f"/api/letters/{letter['id']}",
                            json={"title": "Acme letter", "body": "Dear Acme,\n\n#panic(1)"})
    assert saved.status_code == 200
    pdf = user_client.get(f"/app/letters/{letter['id']}/pdf")
    assert pdf.content.startswith(b"%PDF")
    assert "Cover_Letter" in pdf.headers["content-disposition"]
    assert user_client.get(f"/app/letters/{letter['id']}").status_code == 200
    assert "Acme letter" in user_client.get("/app/letters").text

    for _ in range(2):
        user_client.post("/api/letters/generate", json={"resume_id": rid})
    r = user_client.post("/api/letters/generate", json={"resume_id": rid})
    assert r.status_code == 402


# ------------------------------------------------------------------ elite billing


def test_subscription_price_maps_to_plan(user_client, override_settings):
    from test_billing import _post_event

    override_settings(stripe_price_pro="price_pro", stripe_price_elite="price_elite")
    uid = get_user(user_client.email).id
    event = {"id": "evt_elite", "object": "event", "type": "customer.subscription.updated",
             "data": {"object": {"id": "sub_e", "object": "subscription", "status": "active",
                                 "customer": "cus_e", "metadata": {"user_id": str(uid)},
                                 "items": {"data": [{"price": {"id": "price_elite"}}]}}}}
    assert _post_event(user_client, event).status_code == 200
    assert get_user(user_client.email).plan == "elite"


def test_pages_render(user_client):
    for url in ("/", "/app", "/app/jobs", "/app/letters", "/app/account"):
        r = user_client.get(url)
        assert r.status_code == 200, url
    assert "Elite" in user_client.get("/app/account").text
