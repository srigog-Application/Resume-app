"""Stripe subscription billing: Checkout, Customer Portal and webhooks.

The webhook is the source of truth for plan changes. The success redirect also
syncs immediately so users see Pro right away, even before the webhook lands
(or when running locally without `stripe listen`).
"""

import logging
from typing import Any

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import ProcessedStripeEvent, User
from ..security import require_user_page
from ..web import flash

log = logging.getLogger(__name__)
router = APIRouter(prefix="/billing")

ACTIVE_STATUSES = {"active", "trialing"}


def _stripe() -> Any:
    if not settings.billing_enabled:
        raise HTTPException(status_code=503, detail="Billing is not configured.")
    stripe.api_key = settings.stripe_secret_key
    return stripe


def apply_subscription(user: User, subscription: dict[str, Any]) -> None:
    status = subscription.get("status")
    user.stripe_subscription_id = subscription.get("id")
    user.subscription_status = status
    user.plan = "pro" if status in ACTIVE_STATUSES else "free"
    if customer := subscription.get("customer"):
        user.stripe_customer_id = customer if isinstance(customer, str) else customer.get("id")


@router.post("/checkout")
def checkout(request: Request, user: User = Depends(require_user_page),
             db: Session = Depends(get_db)):
    if user.is_pro:
        return RedirectResponse("/app/account", status_code=303)
    s = _stripe()
    params: dict[str, Any] = {
        "mode": "subscription",
        "line_items": [{"price": settings.stripe_price_id, "quantity": 1}],
        "client_reference_id": str(user.id),
        "metadata": {"user_id": str(user.id)},
        "subscription_data": {"metadata": {"user_id": str(user.id)}},
        "allow_promotion_codes": True,
        "success_url": f"{settings.base_url}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{settings.base_url}/app/account",
    }
    if user.stripe_customer_id:
        params["customer"] = user.stripe_customer_id
    else:
        params["customer_email"] = user.email
    session = s.checkout.Session.create(**params)
    return RedirectResponse(session.url, status_code=303)


@router.get("/success")
def success(request: Request, session_id: str = "", user: User = Depends(require_user_page),
            db: Session = Depends(get_db)):
    s = _stripe()
    try:
        session = s.checkout.Session.retrieve(session_id, expand=["subscription"]).to_dict()
    except stripe.StripeError:
        flash(request, "We couldn't confirm the payment yet. It may take a minute.", "warning")
        return RedirectResponse("/app/account", status_code=303)
    if session.get("client_reference_id") == str(user.id) and session.get("subscription"):
        user.stripe_customer_id = session.get("customer")
        apply_subscription(user, session["subscription"])
        db.commit()
        flash(request, "You're on Pro. Thanks for upgrading!", "success")
    return RedirectResponse("/app/account", status_code=303)


@router.post("/portal")
def portal(user: User = Depends(require_user_page)):
    s = _stripe()
    if not user.stripe_customer_id:
        return RedirectResponse("/app/account", status_code=303)
    session = s.billing_portal.Session.create(
        customer=user.stripe_customer_id, return_url=f"{settings.base_url}/app/account"
    )
    return RedirectResponse(session.url, status_code=303)


def _find_user(db: Session, obj: dict[str, Any]) -> User | None:
    metadata = obj.get("metadata") or {}
    uid = obj.get("client_reference_id") or metadata.get("user_id")
    if uid and str(uid).isdigit() and (user := db.get(User, int(uid))):
        return user
    customer = obj.get("customer")
    if customer:
        return db.scalar(select(User).where(User.stripe_customer_id == customer))
    return None


@router.post("/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)):
    if not settings.stripe_webhook_secret:
        return JSONResponse({"detail": "Webhook secret not configured."}, status_code=503)
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(
            payload, request.headers.get("stripe-signature", ""), settings.stripe_webhook_secret
        )
    except (ValueError, stripe.SignatureVerificationError):
        return JSONResponse({"detail": "Invalid signature."}, status_code=400)

    event = event.to_dict()  # StripeObjects aren't dicts in stripe-python >= 13.
    try:
        db.add(ProcessedStripeEvent(id=event["id"], type=event["type"]))
        db.flush()
    except IntegrityError:
        db.rollback()
        return {"received": True, "duplicate": True}

    obj = event["data"]["object"]
    etype = event["type"]
    if etype == "checkout.session.completed" and obj.get("mode") == "subscription":
        if user := _find_user(db, obj):
            user.stripe_customer_id = obj.get("customer")
            sub = _stripe().Subscription.retrieve(obj["subscription"])
            apply_subscription(user, sub.to_dict())
    elif etype in ("customer.subscription.created", "customer.subscription.updated",
                   "customer.subscription.deleted"):
        user = _find_user(db, obj)
        # Ignore events about an older subscription once the user has a newer one.
        stale = user and user.stripe_subscription_id not in (None, obj.get("id"))
        if user and not (stale and user.is_pro):
            apply_subscription(user, obj)
            if etype == "customer.subscription.deleted":
                user.plan = "free"
    db.commit()
    log.info("Processed Stripe event %s (%s)", event["id"], etype)
    return {"received": True}
