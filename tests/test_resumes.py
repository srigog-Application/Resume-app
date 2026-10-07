from conftest import first_resume_id, set_user, signup

from app.resume_data import sample_resume


def _save(client, rid, data, title=None):
    body = {"data": data}
    if title:
        body["title"] = title
    return client.put(f"/api/resumes/{rid}", json=body)


def test_save_and_download_pdf(user_client):
    rid = first_resume_id(user_client)
    data = sample_resume().model_dump()
    assert _save(user_client, rid, data, "Engineering").status_code == 200

    r = user_client.get(f"/app/resumes/{rid}/pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    assert "Alex_Morgan_Resume.pdf" in r.headers["content-disposition"]


def test_preview_returns_png_pages_and_warnings(user_client):
    data = sample_resume().model_dump()
    data["basics"]["phone"] = "12"
    r = user_client.post("/api/preview", json={"data": data})
    body = r.json()
    assert r.status_code == 200
    assert body["pages"] and body["pages"][0].startswith("data:image/png;base64,")
    assert any("Phone" in w for w in body["warnings"])
    assert body["locked"] is False


def test_preview_reports_errors_instead_of_crashing(user_client):
    data = sample_resume().model_dump()
    data["experience"][0].update(start_date="2025-01", end_date="2020-01", current=False)
    body = user_client.post("/api/preview", json={"data": data}).json()
    assert body["pages"] == []
    assert "start_date" in body["error"]


def test_other_users_cannot_access_resume(client):
    client.email = signup(client)
    victim_id = first_resume_id(client)
    client.post("/logout")
    signup(client)  # a different user
    assert client.get(f"/app/resumes/{victim_id}").status_code == 404
    assert client.get(f"/app/resumes/{victim_id}/pdf").status_code == 404
    assert _save(client, victim_id, {}).status_code == 404
    assert client.get(f"/api/resumes/{victim_id}/versions").status_code == 404


def test_versions_create_restore_delete(user_client):
    rid = first_resume_id(user_client)
    data = sample_resume().model_dump()
    _save(user_client, rid, data)
    v = user_client.post(f"/api/resumes/{rid}/versions", json={"label": "Original"}).json()

    data["basics"]["name"] = "Changed Name"
    _save(user_client, rid, data)

    restored = user_client.post(f"/api/resumes/{rid}/versions/{v['id']}/restore").json()
    assert restored["data"]["basics"]["name"] == "Alex Morgan"

    pdf = user_client.get(f"/app/resumes/{rid}/versions/{v['id']}/pdf")
    assert pdf.content.startswith(b"%PDF")
    assert "Original" in pdf.headers["content-disposition"]

    assert user_client.delete(f"/api/resumes/{rid}/versions/{v['id']}").status_code == 200
    assert user_client.get(f"/api/resumes/{rid}/versions").json()["versions"] == []


def test_free_plan_limits(user_client):
    rid = first_resume_id(user_client)
    for i in range(3):
        assert user_client.post(f"/api/resumes/{rid}/versions",
                                json={"label": f"v{i}"}).status_code == 200
    r = user_client.post(f"/api/resumes/{rid}/versions", json={"label": "v4"})
    assert r.status_code == 402

    # Free plan: 3 resumes total (starter + two copies).
    for title in ("Copy", "Copy 2"):
        assert user_client.post(f"/api/resumes/{rid}/duplicate",
                                json={"title": title}).status_code == 200
    assert user_client.post(f"/api/resumes/{rid}/duplicate",
                            json={"title": "Copy 3"}).status_code == 402

    set_user(user_client.email, plan="pro")
    assert user_client.post(f"/api/resumes/{rid}/versions", json={"label": "v5"}).status_code == 200
    assert user_client.post(f"/api/resumes/{rid}/duplicate",
                            json={"title": "Copy 4"}).status_code == 200


def test_pro_template_locked_for_free_users(user_client):
    rid = first_resume_id(user_client)
    data = sample_resume().model_dump()
    data["design"]["template"] = "modern"  # Pro template
    _save(user_client, rid, data)

    assert user_client.post("/api/preview", json={"data": data}).json()["locked"] is True
    r = user_client.get(f"/app/resumes/{rid}/pdf", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/app/account"

    set_user(user_client.email, plan="pro")
    assert user_client.get(f"/app/resumes/{rid}/pdf").content.startswith(b"%PDF")


def test_unknown_template_and_bad_color_are_sanitized(user_client):
    rid = first_resume_id(user_client)
    data = sample_resume().model_dump()
    data["design"].update(template="../../etc", accent_color="red;}", page_size="huge")
    _save(user_client, rid, data)
    page = user_client.get(f"/app/resumes/{rid}")
    assert page.status_code == 200
    assert '"template": "classic"' in page.text


def test_delete_resume(user_client):
    rid = first_resume_id(user_client)
    r = user_client.post(f"/app/resumes/{rid}/delete", follow_redirects=False)
    assert r.status_code == 303
    assert user_client.get(f"/app/resumes/{rid}").status_code == 404
