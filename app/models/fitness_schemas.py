from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


FITNESS_STATUSES = ("REGISTERED", "COMPLETED")


class FitnessEventCreate(BaseModel):
    academic_year: str = Field(min_length=4, max_length=20)
    event_name: str = Field(min_length=3, max_length=120)
    start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    is_active: bool = False


class FitnessEventUpdate(BaseModel):
    academic_year: Optional[str] = Field(default=None, min_length=4, max_length=20)
    event_name: Optional[str] = Field(default=None, min_length=3, max_length=120)
    start_date: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    is_active: Optional[bool] = None


class FitnessEventResponse(BaseModel):
    id: int
    academic_year: str
    event_name: str
    start_date: str
    end_date: str
    is_active: bool


class FitnessStudentCreate(BaseModel):
    nis: str = Field(min_length=1, max_length=50)
    full_name: str = Field(min_length=2, max_length=200)
    gender: str = Field(min_length=1, max_length=30)
    birth_date: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    class_name: Optional[str] = Field(default=None, max_length=50)
    section: Optional[str] = Field(default=None, max_length=50)
    parent_name: Optional[str] = Field(default=None, max_length=200)
    parent_phone: Optional[str] = Field(default=None, max_length=30)


class FitnessStudentResponse(BaseModel):
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
    next_station: Optional[str] = None
    whatsapp_status: Optional[str] = None
    whatsapp_message: Optional[str] = None


class FitnessExaminationSubmit(BaseModel):
    weight: float = Field(gt=0, le=300)
    height: float = Field(gt=0, le=250)
    blood_pressure: str = Field(min_length=3, max_length=30)
    oxygen_saturation: float = Field(ge=50, le=100)
    temperature: float = Field(ge=30, le=45)
    notes: Optional[str] = None


class FitnessQueueItem(BaseModel):
    id: int
    queue_number: Optional[int] = None
    student_name: str
    class_name: Optional[str] = None
    section: Optional[str] = None
    current_status: str
    next_station: Optional[str] = None


class FitnessDashboardResponse(BaseModel):
    total_registered: int
    completed: int
    in_progress: int
    waiting_queue: int
    completion_percentage: float
    recent_students: list[FitnessStudentResponse]


class FitnessSummaryResponse(BaseModel):
    student: FitnessStudentResponse
    examination: Optional[dict] = None
    generated_at: datetime
