from types import SimpleNamespace

import pytest
from conftest import used

from app import ai
from app.resume_data import sample_resume

JD = (
    "We are hiring a Senior Software Engineer to build payment services in Go and Python on "
    "AWS with PostgreSQL and Kafka. Experience with Kubernetes and CI/CD is required."
)


def test_demo_mode_bullets_consume_credit(user_client):
    r = user_client.post("/api/ai/bullets", json={"bullets": ["responsible for reports"]})
    assert r.status_code == 200
    body = r.json()
    assert body["bullets"][0].startswith("Managed reports")
    assert "[X%]" in body["bullets"][0]
    assert body["credits_left"] == 19
    assert used(user_client.email, "chat") == 1


def test_credits_exhausted_returns_402(user_client):
    for _ in range(20):
        assert user_client.post("/api/ai/bullets", json={"bullets": ["x"]}).status_code == 200
    r = user_client.post("/api/ai/bullets", json={"bullets": ["did things"]})
    assert r.status_code == 402
    assert "Upgrade" in r.json()["detail"]


def test_failed_ai_call_refunds_credit(user_client):
    r = user_client.post("/api/ai/bullets", json={"bullets": ["   "]})
    assert r.status_code == 422  # input problem, not a server error
    assert used(user_client.email, "chat") == 0


def test_ai_service_error_refunds_and_502(user_client, monkeypatch):
    def boom(*a):
        raise ai.AIError("The AI service is busy.")

    monkeypatch.setattr(ai, "rewrite_bullets", boom)
    r = user_client.post("/api/ai/bullets", json={"bullets": ["did x"]})
    assert r.status_code == 502 and used(user_client.email, "chat") == 0


def test_unexpected_error_still_refunds(user_client, monkeypatch):
    def boom(*a):
        raise ValueError("unexpected")

    monkeypatch.setattr(ai, "rewrite_bullets", boom)
    import pytest as _pytest
    with _pytest.raises(ValueError):
        user_client.post("/api/ai/bullets", json={"bullets": ["did x"]})
    assert used(user_client.email, "chat") == 0


def test_bullet_length_capped(user_client):
    r = user_client.post("/api/ai/bullets", json={"bullets": ["x" * 1001]})
    assert r.status_code == 422 and used(user_client.email, "chat") == 0


def test_tailor_demo_and_keywords(user_client):
    data = sample_resume().model_dump()
    r = user_client.post("/api/ai/tailor", json={"data": data, "job_description": JD})
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]
    assert "Kafka" in body["missing_keywords"]

    k = user_client.post("/api/keywords", json={"data": data, "job_description": JD}).json()
    assert "AWS" in k["matched"] and "Kafka" in k["missing"]
    assert 0 < k["score"] < 100


def test_tailor_requires_real_job_description(user_client):
    r = user_client.post("/api/ai/tailor", json={"data": {}, "job_description": "short"})
    assert r.status_code == 422


class FakeMessages:
    def __init__(self, parsed, stop_reason="end_turn"):
        self.parsed, self.stop_reason, self.calls = parsed, stop_reason, []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason=self.stop_reason, parsed_output=self.parsed)


@pytest.fixture
def fake_claude(monkeypatch, override_settings):
    override_settings(anthropic_api_key="sk-test", anthropic_model="claude-opus-5")

    def install(parsed, stop_reason="end_turn"):
        messages = FakeMessages(parsed, stop_reason)
        client = SimpleNamespace(beta=SimpleNamespace(messages=messages))
        monkeypatch.setattr(ai, "_client", lambda: client)
        return messages

    return install


def test_claude_request_shape(fake_claude):
    messages = fake_claude(ai.BulletRewrites(bullets=["Led X", "Built Y", "extra"]))
    out = ai.rewrite_bullets(["did x", "made y"], "Engineer", "Acme", JD)
    assert out == ["Led X", "Built Y"]  # trimmed to input length
    call = messages.calls[0]
    assert call["model"] == "claude-opus-5"
    assert call["output_format"] is ai.BulletRewrites
    assert call["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in call["betas"]
    prompt = call["messages"][0]["content"]
    assert "Engineer at Acme" in prompt and "<job_description>" in prompt
    assert "Never invent" in call["system"]


def test_claude_refusal_is_reported(fake_claude):
    fake_claude(None, stop_reason="refusal")
    with pytest.raises(ai.AIError, match="declined"):
        ai.write_summary(sample_resume())


def test_tailor_drops_out_of_range_entries(fake_claude):
    fake_claude(ai.TailorResult(
        summary="S", skills_to_add=["Kafka"], missing_keywords=[], notes=[],
        experience=[ai.ExperienceTailoring(index=0, bullets=["a"]),
                    ai.ExperienceTailoring(index=99, bullets=["b"])]))
    result = ai.tailor(sample_resume(), JD)
    assert [e.index for e in result.experience] == [0]


def test_no_fallbacks_for_other_models(fake_claude, override_settings):
    messages = fake_claude(ai.SummaryOut(summary="Hi"))
    override_settings(anthropic_model="claude-haiku-4-5")
    ai.write_summary(sample_resume())
    assert "fallbacks" not in messages.calls[0]
