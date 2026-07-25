from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Column,
    Date,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class UserORM(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"), nullable=True, index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    nip: Mapped[str | None] = mapped_column(String(50), nullable=True)
    jabatan: Mapped[str | None] = mapped_column(String(100), nullable=True)
    signature_image: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    school: Mapped["SchoolORM | None"] = relationship(back_populates="users")


class SchoolORM(Base):
    __tablename__ = "schools"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    school_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    school_name: Mapped[str] = mapped_column(String(255), nullable=False)
    province: Mapped[str | None] = mapped_column(String(100), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    principal_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)

    users: Mapped[list[UserORM]] = relationship(back_populates="school")


class AuditLogORM(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"), nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    username: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class RecommendationLetterORM(Base):
    __tablename__ = "recommendation_letters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"), nullable=True, index=True)
    letter_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    student_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    student_name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    recommendation_text: Mapped[str] = mapped_column(Text, nullable=False)
    findings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    user: Mapped[UserORM | None] = relationship()


class CKGEventORM(Base):
    __tablename__ = "ckg_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"), nullable=True, index=True)
    academic_year: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    event_name: Mapped[str] = mapped_column(String(120), nullable=False)
    start_date: Mapped[str] = mapped_column(String(10), nullable=False)
    end_date: Mapped[str] = mapped_column(String(10), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    students: Mapped[list["CKGStudentORM"]] = relationship(back_populates="event", cascade="all, delete-orphan")
    assignments: Mapped[list["CKGStationAssignmentORM"]] = relationship(back_populates="event", cascade="all, delete-orphan")


class CKGStudentORM(Base):
    __tablename__ = "ckg_students"
    __table_args__ = (UniqueConstraint("event_id", "nis", name="uq_ckg_students_event_nis"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"), nullable=True, index=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("ckg_events.id"), nullable=False, index=True)
    nis: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    gender: Mapped[str] = mapped_column(String(30), nullable=False)
    birth_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    class_name: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    section: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    parent_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    parent_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="REGISTERED", index=True)
    queue_number: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    needs_referral: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    event: Mapped[CKGEventORM] = relationship(back_populates="students")
    anthropometry: Mapped["CKGAnthropometryORM | None"] = relationship(back_populates="student", cascade="all, delete-orphan", uselist=False)
    ttv: Mapped["CKGTTVORM | None"] = relationship(back_populates="student", cascade="all, delete-orphan", uselist=False)
    vision: Mapped["CKGVisionORM | None"] = relationship(back_populates="student", cascade="all, delete-orphan", uselist=False)
    dental: Mapped["CKGDentalORM | None"] = relationship(back_populates="student", cascade="all, delete-orphan", uselist=False)
    general_screening: Mapped["CKGGeneralScreeningORM | None"] = relationship(back_populates="student", cascade="all, delete-orphan", uselist=False)
    referrals: Mapped[list["CKGReferralORM"]] = relationship(back_populates="student", cascade="all, delete-orphan")


class CKGStationAssignmentORM(Base):
    __tablename__ = "ckg_station_assignments"
    __table_args__ = (UniqueConstraint("event_id", "user_id", "station", name="uq_ckg_assignment_event_user_station"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"), nullable=True, index=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("ckg_events.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    station: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    event: Mapped[CKGEventORM] = relationship(back_populates="assignments")
    user: Mapped[UserORM] = relationship()


class CKGAnthropometryORM(Base):
    __tablename__ = "ckg_anthropometry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"), nullable=True, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("ckg_students.id"), unique=True, nullable=False, index=True)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    height: Mapped[float] = mapped_column(Float, nullable=False)
    bmi: Mapped[float] = mapped_column(Float, nullable=False)
    examined_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    student: Mapped[CKGStudentORM] = relationship(back_populates="anthropometry")


class CKGTTVORM(Base):
    __tablename__ = "ckg_ttv"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"), nullable=True, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("ckg_students.id"), unique=True, nullable=False, index=True)
    blood_pressure: Mapped[str] = mapped_column(String(30), nullable=False)
    pulse: Mapped[int] = mapped_column(Integer, nullable=False)
    respiratory_rate: Mapped[int] = mapped_column(Integer, nullable=False)
    temperature: Mapped[float] = mapped_column(Float, nullable=False)
    examined_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    student: Mapped[CKGStudentORM] = relationship(back_populates="ttv")


class CKGVisionORM(Base):
    __tablename__ = "ckg_vision"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"), nullable=True, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("ckg_students.id"), unique=True, nullable=False, index=True)
    right_eye: Mapped[str] = mapped_column(String(50), nullable=False)
    left_eye: Mapped[str] = mapped_column(String(50), nullable=False)
    examined_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    student: Mapped[CKGStudentORM] = relationship(back_populates="vision")


class CKGDentalORM(Base):
    __tablename__ = "ckg_dental"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"), nullable=True, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("ckg_students.id"), unique=True, nullable=False, index=True)
    caries: Mapped[str] = mapped_column(String(120), nullable=False)
    oral_hygiene: Mapped[str] = mapped_column(String(120), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    examined_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    student: Mapped[CKGStudentORM] = relationship(back_populates="dental")


class CKGGeneralScreeningORM(Base):
    __tablename__ = "ckg_general_screening"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"), nullable=True, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("ckg_students.id"), unique=True, nullable=False, index=True)
    physical_findings: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    examined_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    student: Mapped[CKGStudentORM] = relationship(back_populates="general_screening")


class CKGReferralORM(Base):
    __tablename__ = "ckg_referrals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"), nullable=True, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("ckg_students.id"), nullable=False, index=True)
    station: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    referral_destination: Mapped[str] = mapped_column(String(200), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    student: Mapped[CKGStudentORM] = relationship(back_populates="referrals")


class PatientORM(Base):
    __tablename__ = "patients"

    id: Mapped[str] = mapped_column(
        String(50),
        primary_key=True
    )
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"), nullable=True, index=True)

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
    parent_name = Column(
        String(200),
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
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"), nullable=True, index=True)
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
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"), nullable=True, index=True)
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
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"), nullable=True, index=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), nullable=False, index=True)
    visit_date: Mapped[str] = mapped_column(String(10), nullable=False)
    complaint = mapped_column(String(255), nullable=False)
    examination = mapped_column(Text, nullable=False)
    treatment = mapped_column(Text, nullable=False)
    diagnosis = mapped_column(Text, nullable=True)
    notes = mapped_column(Text, nullable=True)
    referral_to: Mapped[str | None] = mapped_column(String(255), nullable=True)
    referral_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    referral_place: Mapped[str | None] = mapped_column(String(255), nullable=True)
    control_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    control_done: Mapped[bool] = mapped_column(Boolean, default=False)
    whatsapp_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    whatsapp_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    patient: Mapped[PatientORM] = relationship(back_populates="uks_visits")
    medications: Mapped[list["UKSMedicationORM"]] = relationship(
        back_populates="visit",
        cascade="all, delete-orphan",
    )


class UKSMedicationORM(Base):
    __tablename__ = "uks_medications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"), nullable=True, index=True)
    visit_id: Mapped[int] = mapped_column(ForeignKey("uks_visits.id"), nullable=False, index=True)
    medicine_name: Mapped[str] = mapped_column(String(255), nullable=False)
    dosage: Mapped[str] = mapped_column(String(100), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    visit: Mapped[UKSVisitORM] = relationship(back_populates="medications")


class MedicineInventoryORM(Base):
    __tablename__ = "medicine_inventory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    unit: Mapped[str] = mapped_column(String(50), nullable=False, default="tablet")
    stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    minimum_stock: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
class SchoolSettingORM(Base):
    __tablename__ = "school_settings"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        default=1
    )
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"), nullable=True, index=True)

    school_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True
    )

    address: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True
    )

    phone: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True
    )

    email: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True
    )

    logo_url: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True
    )
class MedicineTransactionORM(Base):
    __tablename__ = "medicine_transactions"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True
    )
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"), nullable=True, index=True)

    medicine_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True
    )

    transaction_type: Mapped[str] = mapped_column(
        String(10),
        nullable=False
    )  # IN / OUT

    quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False
    )

    transaction_date: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    notes: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True
    )
