"""Add opaque public tracking and staff-safe complaint updates.

Revision ID: 20260924_0005
Revises: 20260921_0004
Create Date: 2026-09-24
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260924_0005"
down_revision: Union[str, Sequence[str], None] = "20260921_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("student_complaints")}
    if "tracking_code" not in columns:
        op.add_column("student_complaints", sa.Column("tracking_code", sa.String(length=40), nullable=True))
        op.create_index("ix_student_complaints_tracking_code", "student_complaints", ["tracking_code"], unique=True)
    if "public_status_note" not in columns:
        op.add_column("student_complaints", sa.Column("public_status_note", sa.String(length=500), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("student_complaints")}
    if "public_status_note" in columns:
        op.drop_column("student_complaints", "public_status_note")
    if "tracking_code" in columns:
        indexes = {index["name"] for index in inspect(bind).get_indexes("student_complaints")}
        if "ix_student_complaints_tracking_code" in indexes:
            op.drop_index("ix_student_complaints_tracking_code", table_name="student_complaints")
        op.drop_column("student_complaints", "tracking_code")
