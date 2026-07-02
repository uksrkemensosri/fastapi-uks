from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


STATIONS = ("REGISTRATION", "ANTROPOMETRI", "TTV", "VISUS", "GIGI", "SCREENING_UMUM")
STATUSES = (
    "REGISTERED",
    "ANTROPOMETRI_DONE",
    "TTV_DONE",
    "VISUS_DONE",
    "GIGI_DONE",
    "SCREENING_DONE",
    "COMPLETED",
)


def normalize_station(value: str) -> str:
    return value.strip().upper().replace(" ", "_")


class CKGEventCreate(BaseModel):
    academic_year: str = Field(min_length=4, max_length=20)
    event_name: str = Field(min_length=3, max_length=120)
    start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    is_active: bool = False


class CKGEventUpdate(BaseModel):
    academic_year: Optional[str] = Field(default=None, min_length=4, max_length=20)
    event_name: Optional[str] = Field(default=None, min_length=3, max_length=120)
    start_date: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    is_active: Optional[bool] = None


class CKGEventResponse(BaseModel):
    id: int
    academic_year: str
    event_name: str
    start_date: str
    end_date: str
    is_active: bool


class CKGStudentCreate(BaseModel):
    nis: str = Field(min_length=1, max_length=50)
    full_name: str = Field(min_length=2, max_length=200)
    gender: str = Field(min_length=1, max_length=30)
    birth_date: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    class_name: Optional[str] = Field(default=None, max_length=50)
    section: Optional[str] = Field(default=None, max_length=50)
    parent_name: Optional[str] = Field(default=None, max_length=200)
    parent_phone: Optional[str] = Field(default=None, max_length=30)


class CKGStudentResponse(BaseModel):
    id: int
    event_id: int
    nis: str
    full_name: str
    gender: str
    birth_date: Optional[str] = None
    class_name: Optional[str] = None
    section: Optional[str] = None
    parent_name: Optional[str] = None
    parent_phone: Optional[str] = None
    status: str
    queue_number: Optional[int] = None
    needs_referral: bool
    next_station: Optional[str] = None


class CKGStudentImportRequest(BaseModel):
    students: list[CKGStudentCreate] = Field(min_length=1)


class CKGStationAssignmentCreate(BaseModel):
    user_id: int
    station: str

    @field_validator("station", mode="before")
    @classmethod
    def validate_station(cls, value: str) -> str:
        station = normalize_station(value)
        if station not in STATIONS:
            raise ValueError("Invalid station")
        return station


class CKGStationAssignmentResponse(BaseModel):
    id: int
    event_id: int
    user_id: int
    username: str
    full_name: str
    station: str


class CKGQueueItem(BaseModel):
    id: int
    queue_number: Optional[int] = None
    student_name: str
    class_name: Optional[str] = None
    section: Optional[str] = None
    current_status: str
    next_station: Optional[str] = None


class CKGAnthropometrySubmit(BaseModel):
    weight: float = Field(gt=0, le=300)
    height: float = Field(gt=0, le=250)


class CKGTTVSubmit(BaseModel):
    blood_pressure: str = Field(min_length=3, max_length=30)
    pulse: int = Field(ge=20, le=250)
    respiratory_rate: int = Field(ge=5, le=80)
    temperature: float = Field(ge=30, le=45)


class CKGVisionSubmit(BaseModel):
    right_eye: str = Field(min_length=1, max_length=50)
    left_eye: str = Field(min_length=1, max_length=50)


class CKGDentalSubmit(BaseModel):
    caries: str = Field(min_length=1, max_length=120)
    oral_hygiene: str = Field(min_length=1, max_length=120)
    notes: Optional[str] = None


class CKGGeneralSubmit(BaseModel):
    physical_findings: Optional[str] = None
    notes: Optional[str] = None
    recommendation: Optional[str] = None


class CKGReferralCreate(BaseModel):
    station: str
    reason: str = Field(min_length=2)
    referral_destination: str = Field(min_length=2, max_length=200)
    notes: Optional[str] = None

    @field_validator("station", mode="before")
    @classmethod
    def validate_station(cls, value: str) -> str:
        station = normalize_station(value)
        if station not in STATIONS:
            raise ValueError("Invalid station")
        return station


class CKGDashboardResponse(BaseModel):
    total_registered: int
    completed: int
    in_progress: int
    waiting_queue: int
    completion_percentage: float
    students_per_station: dict[str, int]
    daily_progress: dict[str, int]
    recent_students: list[CKGStudentResponse]
    students_needing_referral: list[CKGStudentResponse]


class CKGSummaryResponse(BaseModel):
    student: CKGStudentResponse
    anthropometry: Optional[dict] = None
    ttv: Optional[dict] = None
    vision: Optional[dict] = None
    dental: Optional[dict] = None
    general_screening: Optional[dict] = None
    referrals: list[dict]
    generated_at: datetime
