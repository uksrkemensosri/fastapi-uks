"""Add public QR student complaint intake.

Revision ID: 20260918_0003
Revises: 20260910_0002
Create Date: 2026-09-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260918_0003"
down_revision: Union[str, Sequence[str], None] = "20260910_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "student_complaints" in inspector.get_table_names():
        return
    op.create_table(
        "student_complaints",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("patient_id", sa.String(length=50), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("complaint", sa.String(length=500), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="MENUNGGU"),
        sa.Column("handled_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("handled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("visit_id", sa.Integer(), sa.ForeignKey("uks_visits.id"), nullable=True, unique=True),
    )
    for name, columns in (
        ("ix_student_complaints_school_id", ["school_id"]),
        ("ix_student_complaints_patient_id", ["patient_id"]),
        ("ix_student_complaints_submitted_at", ["submitted_at"]),
        ("ix_student_complaints_status", ["status"]),
        ("ix_student_complaints_handled_by", ["handled_by"]),
        ("ix_student_complaints_visit_id", ["visit_id"]),
    ):
        op.create_index(name, "student_complaints", columns)


def downgrade() -> None:
    bind = op.get_bind()
    if "student_complaints" in inspect(bind).get_table_names():
        op.drop_table("student_complaints")
