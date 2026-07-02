from typing import Optional, List
from datetime import date, datetime
from pydantic import BaseModel, Field, field_validator


class Patient(BaseModel):
    id: str
    name: str
    age: int = Field(ge=0)
    gender: str


class NursingAssessment(BaseModel):
    patient: Patient
    complaints: List[str] = Field(default_factory=list)
    vital_signs: Optional[dict] = None
    observations: List[str] = Field(default_factory=list)


class ExpertRecommendation(BaseModel):
    nanda_code: str
    nanda_label: str
    confidence: float
    nic: List[str]
    noc: List[str]


class AssessmentResponse(BaseModel):
    patient_id: str
    recommendations: List[ExpertRecommendation]


class PatientSummary(BaseModel):
    id: str
    name: str
    age: int
    gender: str
    class_name: Optional[str] = None
    birth_date: Optional[str] = None
    parent_name: Optional[str] = None
    parent_phone: Optional[str] = None


class PatientCreate(BaseModel):
    id: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=2, max_length=200)
    age: int = Field(ge=0, le=120)
    gender: str = Field(min_length=1, max_length=30)
    class_name: Optional[str] = Field(default=None, max_length=50)
    birth_date: Optional[str] = None
    parent_name: Optional[str] = Field(default=None, max_length=200)
    parent_phone: Optional[str] = Field(default=None, max_length=30)

class UKSVisitCreate(BaseModel):

    patient_id: Optional[str] = None
    visit_date: Optional[date] = None

    complaint: Optional[str] = None
    examination: Optional[str] = None
    treatment: Optional[str] = None
    diagnosis: Optional[str] = None
    notes: Optional[str] = None

    referral_to: Optional[str] = None
    referral_place: Optional[str] = None
    referral_status: Optional[str] = None
    control_date: Optional[date] = None
    control_done: Optional[bool] = None

class UKSVisitResponse(BaseModel):
    id: int
    patient_id: str
    visit_date: str
    complaint: str
    examination: str
    treatment: str
    diagnosis: Optional[str] = None
    notes: Optional[str] = None
    referral_to: Optional[str] = None
    referral_status: Optional[str] = None
    whatsapp_status: Optional[str] = None
    whatsapp_message: Optional[str] = None


class AICareSuggestionRequest(BaseModel):
    complaint: str = Field(min_length=2, max_length=255)
    examination: str = Field(min_length=2, max_length=255)


class AICareSuggestionResponse(BaseModel):
    diagnosis: str
    intervention: str
    implementation: str
    follow_up: str
    confidence: float
    source: Optional[str] = None
    model: Optional[str] = None


class UKSMedicationCreate(BaseModel):
    medicine_name: str = Field(min_length=2, max_length=255)
    dosage: str = Field(min_length=1, max_length=100)
    quantity: int = Field(ge=1, le=1000)
    notes: Optional[str] = Field(default=None, max_length=500)


class UKSMedicationResponse(BaseModel):
    id: int
    visit_id: int
    medicine_name: str
    dosage: str
    quantity: int
    notes: Optional[str] = None
    remaining_stock: Optional[int] = None


class MedicineInventoryCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    unit: str = Field(min_length=1, max_length=50)
    stock: int = Field(ge=0, le=100000)
    minimum_stock: int = Field(default=10, ge=0, le=100000)


class MedicineInventoryUpdate(BaseModel):
    unit: Optional[str] = Field(default=None, min_length=1, max_length=50)
    stock: Optional[int] = Field(default=None, ge=0, le=100000)
    minimum_stock: Optional[int] = Field(default=None, ge=0, le=100000)


class MedicineStockAdjustment(BaseModel):
    adjustment_type: str = Field(pattern="^(IN|OUT|SET)$")
    quantity: int = Field(ge=0, le=100000)
    notes: Optional[str] = Field(default=None, max_length=500)


class MedicineInventoryResponse(BaseModel):
    id: int
    name: str
    unit: str
    stock: int
    minimum_stock: int
    is_low_stock: bool


class UKSReferralUpdate(BaseModel):
    referral_to: Optional[str] = Field(default=None, max_length=255)
    referral_status: str = Field(pattern="^(dirujuk|selesai|ditunda)$")


class ComplaintStat(BaseModel):
    complaint: str
    total: int


class UKSDailyReportResponse(BaseModel):
    date: str
    total_visits: int
    total_referrals: int
    top_complaints: List[ComplaintStat]


class UKSMonthlyReportResponse(BaseModel):
    month: str
    total_visits: int
    total_referrals: int
    top_complaints: List[ComplaintStat]


class AssessmentSummary(BaseModel):
    id: int
    patient_id: str
    complaints: List[str]
    observations: List[str]
    vital_signs: Optional[dict] = None
    recommendations: List[ExpertRecommendation]


class PatientAssessmentsResponse(BaseModel):
    patient: PatientSummary
    assessments: List[AssessmentSummary]


USER_ROLE_PATTERN = "^(admin|perawat|kepala_sekolah|wali_asuh|tim_uksr)$"


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    full_name: str = Field(min_length=2, max_length=100)
    role: str = Field(pattern=USER_ROLE_PATTERN)
    password: str = Field(min_length=6)
    nip: Optional[str] = Field(default=None, max_length=50)
    jabatan: Optional[str] = Field(default=None, max_length=100)

    @field_validator("role", mode="before")
    @classmethod
    def normalize_role(cls, value: str) -> str:
        if isinstance(value, str):
            return value.strip().lower().replace(" ", "_").replace("-", "_")
        return value


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=6)


class UserUpdate(BaseModel):
    username: Optional[str] = Field(default=None, min_length=3, max_length=50)
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    role: Optional[str] = Field(default=None, pattern=USER_ROLE_PATTERN)
    nip: Optional[str] = Field(default=None, max_length=50)
    jabatan: Optional[str] = Field(default=None, max_length=100)
    is_active: Optional[bool] = None

    @field_validator("role", mode="before")
    @classmethod
    def normalize_role(cls, value: str | None) -> str | None:
        if isinstance(value, str):
            return value.strip().lower().replace(" ", "_").replace("-", "_")
        return value


class PasswordResetRequest(BaseModel):
    new_password: str = Field(min_length=6)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: Optional[str] = None


class UserResponse(BaseModel):
    id: int
    username: str
    full_name: str
    role: str
    is_active: bool
    nip: Optional[str] = None
    jabatan: Optional[str] = None
    signature_image: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class UserProfileUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    nip: Optional[str] = Field(default=None, max_length=50)
    jabatan: Optional[str] = Field(default=None, max_length=100)
    signature_image: Optional[str] = None


class AuditLogResponse(BaseModel):
    id: int
    user_id: Optional[int] = None
    username: Optional[str] = None
    action: str
    entity_type: str
    entity_id: Optional[str] = None
    details: Optional[str] = None
    timestamp: datetime


class AuditLogListResponse(BaseModel):
    items: List[AuditLogResponse]
    total: int
    page: int
    page_size: int
class SchoolSettingUpdate(BaseModel):
    school_name: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    logo_url: Optional[str] = None


class SchoolSettingResponse(BaseModel):
    school_name: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    logo_url: Optional[str] = None
