import datetime as dt
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    # Billing
    plan: Mapped[str] = mapped_column(String(20), default="free")
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), index=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255))
    subscription_status: Mapped[str | None] = mapped_column(String(50))

    # AI usage metering (reset monthly)
    ai_credits_used: Mapped[int] = mapped_column(Integer, default=0)
    ai_period_start: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    resumes: Mapped[list["Resume"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", order_by="Resume.updated_at.desc()"
    )

    @property
    def is_pro(self) -> bool:
        return self.plan == "pro"


class Resume(Base):
    __tablename__ = "resumes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="resumes")
    versions: Mapped[list["ResumeVersion"]] = relationship(
        back_populates="resume",
        cascade="all, delete-orphan",
        order_by="ResumeVersion.created_at.desc()",
    )


class ResumeVersion(Base):
    """A named, immutable snapshot of a resume's content and design."""

    __tablename__ = "resume_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    resume_id: Mapped[int] = mapped_column(
        ForeignKey("resumes.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(200))
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    resume: Mapped[Resume] = relationship(back_populates="versions")


class ProcessedStripeEvent(Base):
    """Stripe may deliver a webhook more than once; remember what we handled."""

    __tablename__ = "stripe_events"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    type: Mapped[str] = mapped_column(String(100), default="")
