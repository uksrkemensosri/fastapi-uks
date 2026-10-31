"""Additive collaboration records; no production data is deleted on cancellation."""
from datetime import datetime
from sqlalchemy import ForeignKey, Integer, String, JSON, DateTime, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.database import Base


class FasyankesCaseORM(Base):
    __tablename__ = 'fasyankes_cases'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey('schools.id'), index=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey('patients.id'), index=True)
    referral_id: Mapped[int | None] = mapped_column(ForeignKey('bpjs_referrals.id'), unique=True)
    uks_visit_id: Mapped[int | None] = mapped_column(ForeignKey('uks_visits.id'))
    version: Mapped[int] = mapped_column(Integer, default=1)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FasyankesRevisionORM(Base):
    __tablename__ = 'fasyankes_revisions'
    __table_args__ = (UniqueConstraint('case_id', 'version'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey('fasyankes_cases.id'), index=True)
    version: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    action: Mapped[str] = mapped_column(String(50))
    snapshot: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FasyankesNotificationORM(Base):
    __tablename__ = 'fasyankes_notifications'
    __table_args__ = (UniqueConstraint('case_id', 'version', 'recipient_id'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey('fasyankes_cases.id'), index=True)
    version: Mapped[int] = mapped_column(Integer)
    recipient_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
