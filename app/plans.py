"""Free / Pro / Elite limits in one place, so pricing copy and enforcement agree.

AI usage is metered per feature per 30-day period (see `Usage`). `None`
means unlimited.
"""

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import Usage, User, utcnow

FEATURES = {
    "analysis": "Resume analyses",
    "tailor": "Job tailorings",
    "cover_letter": "Cover letters",
    "chat": "AI chat & rewrite credits",
}


@dataclass(frozen=True)
class Plan:
    key: str
    name: str
    price_label: str
    max_resumes: int | None
    max_versions_per_resume: int | None
    templates: str  # "free" or "all"
    quotas: dict[str, int | None] = field(default_factory=dict)


FREE = Plan("free", "Free", "$0", max_resumes=3, max_versions_per_resume=3, templates="free",
            quotas={"analysis": 3, "tailor": 3, "cover_letter": 3, "chat": 20})
PRO = Plan("pro", "Pro", "$11.99", max_resumes=None, max_versions_per_resume=None,
           templates="all",
           quotas={"analysis": 100, "tailor": 100, "cover_letter": 100, "chat": 500})
ELITE = Plan("elite", "Elite", "$23.99", max_resumes=None, max_versions_per_resume=None,
             templates="all",
             quotas={"analysis": None, "tailor": None, "cover_letter": 100, "chat": 500})
PLANS = {p.key: p for p in (FREE, PRO, ELITE)}
PAID_PLANS = (PRO, ELITE)

PERIOD = dt.timedelta(days=30)


def plan_for(user: User) -> Plan:
    return PLANS.get(user.plan, FREE)


def _period_start(user: User) -> dt.datetime:
    """Usage resets every 30 days from signup."""
    start = user.created_at
    periods = (utcnow() - start) // PERIOD
    return start + periods * PERIOD


def _usage_row(db: Session, user: User, feature: str) -> Usage:
    start = _period_start(user)
    row = db.scalar(select(Usage).where(
        Usage.user_id == user.id, Usage.feature == feature, Usage.period_start == start))
    if row is None:
        row = Usage(user_id=user.id, feature=feature, period_start=start, count=0)
        try:
            with db.begin_nested():  # Two concurrent first-uses may race to insert.
                db.add(row)
        except IntegrityError:
            row = db.scalar(select(Usage).where(
                Usage.user_id == user.id, Usage.feature == feature,
                Usage.period_start == start))
    return row


def remaining(db: Session, user: User, feature: str) -> int | None:
    limit = plan_for(user).quotas[feature]
    if limit is None:
        return None
    return max(0, limit - _usage_row(db, user, feature).count)


def usage_summary(db: Session, user: User) -> list[dict]:
    plan = plan_for(user)
    out = []
    for key, label in FEATURES.items():
        used = _usage_row(db, user, key).count
        limit = plan.quotas[key]
        out.append({"key": key, "label": label, "used": used, "limit": limit,
                    "left": None if limit is None else max(0, limit - used)})
    return out


def consume(db: Session, user: User, feature: str) -> bool:
    """Reserve one use of `feature`. Returns False when the quota is exhausted."""
    row = _usage_row(db, user, feature)
    limit = plan_for(user).quotas[feature]
    if limit is not None and row.count >= limit:
        return False
    row.count += 1
    return True


def refund(db: Session, user: User, feature: str) -> None:
    row = _usage_row(db, user, feature)
    row.count = max(0, row.count - 1)


def upgrade_hint(user: User, feature: str) -> str:
    label = FEATURES[feature].lower()
    plan = plan_for(user)
    if plan.key == "free":
        return f"You've used all your free {label} this month. Upgrade to Pro for " \
               f"{PRO.quotas[feature]} per month."
    if plan.key == "pro" and ELITE.quotas[feature] is None:
        return f"You've used all {label} on Pro this month. Elite makes them unlimited."
    return f"You've used all {label} this month. Your quota resets in under 30 days."
