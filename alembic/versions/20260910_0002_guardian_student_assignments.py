"""Add explicit wali asuh to student assignments.

Revision ID: 20260910_0002
Revises: 20260725_0001
Create Date: 2026-09-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260910_0002"
down_revision: Union[str, Sequence[str], None] = "20260725_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "guardian_student_assignments" in inspector.get_table_names():
        return

    op.create_table(
        "guardian_student_assignments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("guardian_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("patient_id", sa.String(length=50), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("guardian_id", "patient_id", name="uq_guardian_student_assignment"),
    )
    op.create_index("ix_guardian_student_assignments_school_id", "guardian_student_assignments", ["school_id"])
    op.create_index("ix_guardian_student_assignments_guardian_id", "guardian_student_assignments", ["guardian_id"])
    op.create_index("ix_guardian_student_assignments_patient_id", "guardian_student_assignments", ["patient_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if "guardian_student_assignments" in inspect(bind).get_table_names():
        op.drop_table("guardian_student_assignments")
