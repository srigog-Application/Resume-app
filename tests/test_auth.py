from conftest import get_user, signup


def test_landing_page(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "ATS" in r.text and "Pricing" in r.text


def test_signup_creates_user_and_starter_resume(client):
    email = signup(client)
    user = get_user(email)
    assert user.plan == "free"
    assert client.get("/app").status_code == 200
    assert "My Resume" in client.get("/app").text


def test_duplicate_email_rejected(client):
    email = signup(client)
    client.post("/logout")
    r = client.post("/signup", data={"email": email.upper(), "password": "password123"})
    assert r.status_code == 400
    assert "already exists" in r.text


def test_short_password_rejected(client):
    r = client.post("/signup", data={"email": "short@example.com", "password": "123"})
    assert r.status_code == 400


def test_login_logout(client):
    email = signup(client, password="correct-horse")
    client.post("/logout")
    assert client.get("/app", follow_redirects=False).status_code == 303

    bad = client.post("/login", data={"email": email, "password": "wrong-pass"})
    assert bad.status_code == 400
    assert "Incorrect" in bad.text

    ok = client.post("/login", data={"email": email, "password": "correct-horse"},
                     follow_redirects=False)
    assert ok.status_code == 303
    assert client.get("/app").status_code == 200


def test_login_redirect_is_local_only(client):
    email = signup(client)
    client.post("/logout")
    r = client.post("/login", data={"email": email, "password": "password123",
                                    "next": "https://evil.example"}, follow_redirects=False)
    assert r.headers["location"] == "/app"


def test_password_is_hashed(client):
    email = signup(client, password="plaintext-secret")
    assert "plaintext-secret" not in get_user(email).password_hash


def test_cross_origin_post_blocked(user_client):
    r = user_client.post("/api/preview", json={"data": {}},
                         headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_api_requires_login(client):
    assert client.post("/api/preview", json={"data": {}}).status_code == 401
