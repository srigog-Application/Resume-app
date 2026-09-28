"""Free vs. Pro limits in one place, so pricing copy and enforcement agree."""

import datetime as dt
from dataclasses import dataclass

from .models import User, utcnow


@dataclass(frozen=True)
class Plan:
    key: str
    name: str
    max_resumes: int | None  # None = unlimited
    max_versions_per_resume: int | None
    ai_credits_per_month: int
    templates: str  # "free" or "all"


FREE = Plan("free", "Free", max_resumes=2, max_versions_per_resume=3, ai_credits_per_month=10,
            templates="free")
PRO = Plan("pro", "Pro", max_resumes=None, max_versions_per_resume=None,
           ai_credits_per_month=500, templates="all")


def plan_for(user: User) -> Plan:
    return PRO if user.is_pro else FREE


AI_PERIOD = dt.timedelta(days=30)


def _roll_period(user: User) -> None:
    if utcnow() - user.ai_period_start >= AI_PERIOD:
        user.ai_period_start = utcnow()
        user.ai_credits_used = 0


def ai_credits_left(user: User) -> int:
    _roll_period(user)
    return max(0, plan_for(user).ai_credits_per_month - user.ai_credits_used)


def consume_ai_credit(user: User) -> bool:
    """Reserve one AI credit. Returns False when the monthly quota is exhausted."""
    if ai_credits_left(user) <= 0:
        return False
    user.ai_credits_used += 1
    return True


def refund_ai_credit(user: User) -> None:
    user.ai_credits_used = max(0, user.ai_credits_used - 1)
