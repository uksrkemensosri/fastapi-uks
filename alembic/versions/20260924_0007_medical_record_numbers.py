"""Add optional existing medical record numbers for student cards.

Revision ID: 20260924_0007
Revises: 20260924_0006
Create Date: 2026-09-24
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260924_0007"
down_revision: Union[str, Sequence[str], None] = "20260924_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("patients")}
    if "medical_record_number" not in columns:
        op.add_column("patients", sa.Column("medical_record_number", sa.String(length=30), nullable=True))
        op.create_index("ix_patients_medical_record_number", "patients", ["medical_record_number"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("patients")}
    if "medical_record_number" in columns:
        indexes = {index["name"] for index in inspect(bind).get_indexes("patients")}
        if "ix_patients_medical_record_number" in indexes:
            op.drop_index("ix_patients_medical_record_number", table_name="patients")
        op.drop_column("patients", "medical_record_number")
