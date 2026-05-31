from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Column,
    Date
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class UserORM(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class PatientORM(Base):
    __tablename__ = "patients"

    id: Mapped[str] = mapped_column(
        String(50),
        primary_key=True
    )

    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False
    )

    age: Mapped[int] = mapped_column(
        Integer,
        nullable=False
    )

    gender: Mapped[str] = mapped_column(
        String(30),
        nullable=False
    )

    class_name: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True
    )
    parent_phone = Column(
        String,
        nullable=True
    )

    birth_date: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True
    )

    assessments: Mapped[list["AssessmentORM"]] = relationship(
        back_populates="patient",
        cascade="all, delete-orphan",
    )

    uks_visits: Mapped[list["UKSVisitORM"]] = relationship(
        back_populates="patient",
        cascade="all, delete-orphan",
    )


class AssessmentORM(Base):
    __tablename__ = "assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), nullable=False)
    complaints: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    observations: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    vital_signs: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    patient: Mapped[PatientORM] = relationship(back_populates="assessments")
    recommendations: Mapped[list["RecommendationORM"]] = relationship(
        back_populates="assessment",
        cascade="all, delete-orphan",
    )


class RecommendationORM(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessments.id"), nullable=False)
    nanda_code: Mapped[str] = mapped_column(String(20), nullable=False)
    nanda_label: Mapped[str] = mapped_column(String(255), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    nic: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    noc: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    assessment: Mapped[AssessmentORM] = relationship(back_populates="recommendations")


class UKSVisitORM(Base):
    __tablename__ = "uks_visits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), nullable=False, index=True)
    visit_date: Mapped[str] = mapped_column(String(10), nullable=False)
    complaint: Mapped[str] = mapped_column(String(255), nullable=False)
    examination: Mapped[str] = mapped_column(String(255), nullable=False)
    treatment: Mapped[str] = mapped_column(String(255), nullable=False)
    diagnosis: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    referral_to: Mapped[str | None] = mapped_column(String(255), nullable=True)
    referral_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    referral_place: Mapped[str | None] = mapped_column(String(255), nullable=True)
    control_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    control_done: Mapped[bool] = mapped_column(Boolean, default=False)

    patient: Mapped[PatientORM] = relationship(back_populates="uks_visits")
    medications: Mapped[list["UKSMedicationORM"]] = relationship(
        back_populates="visit",
        cascade="all, delete-orphan",
    )


class UKSMedicationORM(Base):
    __tablename__ = "uks_medications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    visit_id: Mapped[int] = mapped_column(ForeignKey("uks_visits.id"), nullable=False, index=True)
    medicine_name: Mapped[str] = mapped_column(String(255), nullable=False)
    dosage: Mapped[str] = mapped_column(String(100), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    visit: Mapped[UKSVisitORM] = relationship(back_populates="medications")


class MedicineInventoryORM(Base):
    __tablename__ = "medicine_inventory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    unit: Mapped[str] = mapped_column(String(50), nullable=False, default="tablet")
    stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    minimum_stock: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
