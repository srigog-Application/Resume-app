"""Regression tests for issues found in the code and security reviews."""

import pytest
from conftest import first_resume_id, signup

from app import ai_features
from app.renderer import render_pdf
from app.resume_data import sample_resume, to_engine_input


def test_deleted_resume_chat_does_not_leak_to_reused_id(client):
    """SQLite reuses the highest rowid; orphaned chat rows used to show up for the next user."""
    client.email = signup(client)
    rid = first_resume_id(client)
    client.put(f"/api/resumes/{rid}", json={"data": sample_resume().model_dump()})
    assert client.post(f"/api/resumes/{rid}/chat",
                       json={"message": "SECRET from A"}).status_code == 200
    job = client.post("/api/jobs", json={"company": "Acme", "resume_id": rid}).json()
    client.post(f"/app/resumes/{rid}/delete")
    # Foreign keys are enforced: the job's link to the deleted resume is cleared.
    assert client.get("/api/jobs").json()["jobs"][0]["resume_id"] is None
    assert job["resume_id"] == rid
    client.post("/logout")

    client.email = signup(client)  # user B; their starter resume may get A's old id
    rid_b = first_resume_id(client)
    msgs = client.get(f"/api/resumes/{rid_b}/chat").json()["messages"]
    assert all("SECRET" not in m["content"] for m in msgs)


@pytest.mark.parametrize("site", [
    'https://a.com/"+panic("x")+"', 'https://a.com/x"), panic("x"), ("',
    'https://a.com/\\', "https://a.com/ space", "https://a.com/[x]", 'https://a"b.com',
])
def test_website_cannot_break_out_of_typst_string(site):
    data = sample_resume()
    data.basics.website = site
    engine_input, warnings = to_engine_input(data)
    assert "website" not in engine_input["cv"]  # rejected by the app layer...
    assert warnings
    assert render_pdf(data).content.startswith(b"%PDF")


def test_engine_escapes_connection_urls_even_without_app_filter():
    """Defence in depth: the engine itself escapes header link targets."""
    from cvengine.renderer.templater.templater import render_full_template
    from cvengine.schema.cvengine_model_builder import build_cvengine_model_from_commented_map

    engine_input, _ = to_engine_input(sample_resume())
    # URL normalisation percent-encodes quotes in the path, but not in the host.
    engine_input["cv"]["website"] = 'https://a"b.com'
    model = build_cvengine_model_from_commented_map(engine_input)
    assert '"' in str(model.cv.website)
    src = render_full_template(model, "typst")
    assert '#link("https://a\\"b.com/"' in src  # quote escaped inside the string literal


def test_coach_edit_follows_its_entry_after_reorder(user_client):
    rid = first_resume_id(user_client)
    data = sample_resume()
    user_client.put(f"/api/resumes/{rid}", json={"data": data.model_dump()})
    edit = ai_features.ResumeEdit(kind="experience_bullets", index=0, label="", text="",
                                  items=["New Northwind bullet"], reason="")
    target = ai_features.edit_target(data, edit)  # Northwind Labs entry

    swapped = data.model_dump()
    swapped["experience"].reverse()  # user reorders: Northwind is now index 1
    user_client.put(f"/api/resumes/{rid}", json={"data": swapped})
    out = user_client.post(f"/api/resumes/{rid}/apply-edit",
                           json={"edit": edit.model_dump(), "target": target}).json()["data"]
    assert out["experience"][1]["company"] == "Northwind Labs"
    assert out["experience"][1]["bullets"] == ["New Northwind bullet"]
    assert out["experience"][0]["bullets"] != ["New Northwind bullet"]  # Brightline untouched

    swapped["experience"] = swapped["experience"][:1]  # user deletes Northwind
    user_client.put(f"/api/resumes/{rid}", json={"data": swapped})
    r = user_client.post(f"/api/resumes/{rid}/apply-edit",
                         json={"edit": edit.model_dump(), "target": target})
    assert r.status_code == 409


def test_chat_edits_are_stored_with_their_target(user_client):
    rid = first_resume_id(user_client)
    user_client.put(f"/api/resumes/{rid}", json={"data": sample_resume().model_dump()})
    edit = user_client.post(f"/api/resumes/{rid}/chat",
                            json={"message": "help"}).json()["assistant"]["edits"][0]
    assert edit["target"] == "senior software engineer|northwind labs"


def test_metering_is_atomic_under_concurrency(client, monkeypatch):
    """Two requests that both read count=2 must not both get the last of 3 credits.

    A barrier after the read forces the interleaving that breaks a
    read-modify-write implementation: both threads read before either writes.
    """
    import contextlib
    import threading

    from app import plans
    from app.db import SessionLocal
    from app.models import User
    from app.security import hash_password

    with SessionLocal() as setup:
        u = User(email=f"race{id(monkeypatch)}@example.com", password_hash=hash_password("x" * 10))
        setup.add(u)
        setup.commit()
        uid = u.id
        for _ in range(2):
            assert plans.consume(setup, u, "analysis")
        setup.commit()

    barrier = threading.Barrier(2, timeout=5)
    original = plans._usage_row

    def read_then_wait(db, user, feature):
        row = original(db, user, feature)
        _ = row.count  # the value a read-modify-write implementation would use
        with contextlib.suppress(threading.BrokenBarrierError):
            barrier.wait()
        return row

    monkeypatch.setattr(plans, "_usage_row", read_then_wait)
    results = []

    def worker():
        with SessionLocal() as db:
            user = db.get(User, uid)
            ok = plans.consume(db, user, "analysis")
            db.commit()
            results.append(ok)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert sorted(results) == [False, True]
