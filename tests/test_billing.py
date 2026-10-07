import hashlib
import hmac
import json
import time

from conftest import get_user

SECRET = "whsec_test"


def _post_event(client, event, secret=SECRET):
    payload = json.dumps(event)
    ts = int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.{payload}".encode(), hashlib.sha256).hexdigest()
    return client.post("/billing/webhook", content=payload, headers={
        "Stripe-Signature": f"t={ts},v1={sig}", "Content-Type": "application/json"})


def _sub_event(event_id, etype, user_id, status, sub_id="sub_1"):
    return {"id": event_id, "object": "event", "type": etype, "data": {"object": {
        "id": sub_id, "object": "subscription", "status": status, "customer": "cus_123",
        "metadata": {"user_id": str(user_id)}}}}


def test_subscription_lifecycle(user_client):
    uid = get_user(user_client.email).id

    r = _post_event(user_client, _sub_event("evt_1", "customer.subscription.created", uid,
                                            "active"))
    assert r.status_code == 200
    user = get_user(user_client.email)
    assert user.plan == "pro" and user.stripe_customer_id == "cus_123"

    # Replayed event is ignored.
    assert _post_event(user_client, _sub_event("evt_1", "customer.subscription.created", uid,
                                               "active")).json()["duplicate"]

    _post_event(user_client, _sub_event("evt_2", "customer.subscription.updated", uid,
                                        "past_due"))
    assert get_user(user_client.email).plan == "free"

    _post_event(user_client, _sub_event("evt_3", "customer.subscription.updated", uid, "active"))
    assert get_user(user_client.email).plan == "pro"

    _post_event(user_client, _sub_event("evt_4", "customer.subscription.deleted", uid,
                                        "canceled"))
    assert get_user(user_client.email).plan == "free"


def test_stale_subscription_event_does_not_downgrade(user_client):
    uid = get_user(user_client.email).id
    _post_event(user_client, _sub_event("evt_a", "customer.subscription.created", uid,
                                        "active", sub_id="sub_new"))
    _post_event(user_client, _sub_event("evt_b", "customer.subscription.deleted", uid,
                                        "canceled", sub_id="sub_old"))
    assert get_user(user_client.email).plan == "pro"


def test_webhook_rejects_bad_signature(client):
    r = _post_event(client, _sub_event("evt_x", "customer.subscription.created", 1, "active"),
                    secret="whsec_wrong")
    assert r.status_code == 400


def test_webhook_exempt_from_origin_check(client):
    event = _sub_event("evt_y", "customer.subscription.created", 999999, "active")
    payload = json.dumps(event)
    ts = int(time.time())
    sig = hmac.new(SECRET.encode(), f"{ts}.{payload}".encode(), hashlib.sha256).hexdigest()
    r = client.post("/billing/webhook", content=payload, headers={
        "Stripe-Signature": f"t={ts},v1={sig}", "Origin": "https://stripe.com"})
    assert r.status_code == 200


def test_checkout_unavailable_without_stripe_keys(user_client):
    r = user_client.post("/billing/checkout")
    assert r.status_code == 503
    assert "set up on this server" in user_client.get("/app/account").text


def _stripe_obj(data):
    import stripe

    return stripe.StripeObject.construct_from(data, "sk_test")


def test_checkout_and_success_sync(user_client, override_settings, monkeypatch):
    import stripe

    override_settings(stripe_secret_key="sk_test_123", stripe_price_pro="price_123")
    uid = get_user(user_client.email).id
    created = {}

    def fake_create(**params):
        created.update(params)
        return _stripe_obj({"id": "cs_1", "url": "https://checkout.stripe.com/c/cs_1"})

    def fake_retrieve(session_id, expand=None):
        assert session_id == "cs_1" and expand == ["subscription"]
        return _stripe_obj({"id": "cs_1", "client_reference_id": str(uid), "customer": "cus_9",
                            "subscription": {"id": "sub_9", "object": "subscription",
                                             "status": "active", "customer": "cus_9"}})

    monkeypatch.setattr(stripe.checkout.Session, "create", staticmethod(fake_create))
    monkeypatch.setattr(stripe.checkout.Session, "retrieve", staticmethod(fake_retrieve))

    r = user_client.post("/billing/checkout", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("https://checkout.stripe")
    assert created["line_items"] == [{"price": "price_123", "quantity": 1}]
    assert created["client_reference_id"] == str(uid)
    assert created["customer_email"] == user_client.email

    r = user_client.get("/billing/success?session_id=cs_1", follow_redirects=False)
    assert r.status_code == 303
    user = get_user(user_client.email)
    assert user.plan == "pro" and user.stripe_customer_id == "cus_9"


def test_checkout_completed_webhook(user_client, override_settings, monkeypatch):
    import stripe

    override_settings(stripe_secret_key="sk_test_123", stripe_price_pro="price_123")
    uid = get_user(user_client.email).id
    monkeypatch.setattr(stripe.Subscription, "retrieve", staticmethod(lambda sid: _stripe_obj(
        {"id": sid, "object": "subscription", "status": "trialing", "customer": "cus_7"})))
    event = {"id": "evt_cs", "object": "event", "type": "checkout.session.completed",
             "data": {"object": {"id": "cs_2", "object": "checkout.session", "mode": "subscription",
                                 "client_reference_id": str(uid), "customer": "cus_7",
                                 "subscription": "sub_7"}}}
    assert _post_event(user_client, event).status_code == 200
    user = get_user(user_client.email)
    assert user.plan == "pro" and user.stripe_subscription_id == "sub_7"
