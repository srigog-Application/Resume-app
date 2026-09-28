import os
import pathlib
import sys
import tempfile

import pytest

# Configure an isolated database before the app is imported.
_tmp = tempfile.mkdtemp(prefix="resume-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["STRIPE_SECRET_KEY"] = ""
os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test"
os.environ["ENVIRONMENT"] = "test"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


_counter = iter(range(10**6))


def signup(client: TestClient, email: str | None = None, password: str = "password123") -> str:
    email = email or f"user{next(_counter)}@example.com"
    r = client.post("/signup", data={"email": email, "password": password},
                    follow_redirects=False)
    assert r.status_code == 303, r.text
    return email


@pytest.fixture
def user_client(client):
    email = signup(client)
    client.email = email
    return client


def first_resume_id(client: TestClient) -> int:
    with SessionLocal() as db:
        user = db.query(User).filter_by(email=client.email).one()
        return user.resumes[0].id


def set_user(email: str, **fields):
    with SessionLocal() as db:
        user = db.query(User).filter_by(email=email).one()
        for k, v in fields.items():
            setattr(user, k, v)
        db.commit()


def get_user(email: str) -> User:
    with SessionLocal() as db:
        return db.query(User).filter_by(email=email).one()


@pytest.fixture
def override_settings():
    """Temporarily change fields on the frozen settings object."""
    original = {}

    def _set(**kwargs):
        for k, v in kwargs.items():
            original.setdefault(k, getattr(settings, k))
            object.__setattr__(settings, k, v)

    yield _set
    for k, v in original.items():
        object.__setattr__(settings, k, v)
