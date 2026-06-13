from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class RecommendationCreate(BaseModel):
    recommendation_text: str = Field(min_length=2)


class RecommendationResponse(BaseModel):
    id: int
    letter_number: str
    student_id: str
    student_name: str
    source_type: str
    source_id: str
    recommendation_text: str
    findings: list
    created_by: Optional[int] = None
    created_at: datetime


class HealthHistoryResponse(BaseModel):
    biodata: dict
    uks_visits: list[dict]
    ckg_history: list[dict]
    medicine_history: list[dict]
    recommendations: list[RecommendationResponse]


class UKSVisitHealthDetailResponse(BaseModel):
    id: int
    patient_id: str
    patient_name: str
    visit_date: str
    complaint: str
    examination: str
    diagnosis: Optional[str] = None
    treatment: str
    notes: Optional[str] = None
    referral_to: Optional[str] = None
    referral_status: Optional[str] = None
    referral_place: Optional[str] = None
    control_date: Optional[str] = None
    medications: list[dict]
