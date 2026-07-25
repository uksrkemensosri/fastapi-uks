"""Add multi-tenant school ownership.

Revision ID: 20260725_0001
Revises:
Create Date: 2026-07-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision: str = "20260725_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TENANT_TABLES = [
    "users",
    "audit_logs",
    "recommendation_letters",
    "ckg_events",
    "ckg_students",
    "ckg_station_assignments",
    "ckg_anthropometry",
    "ckg_ttv",
    "ckg_vision",
    "ckg_dental",
    "ckg_general_screening",
    "ckg_referrals",
    "patients",
    "assessments",
    "recommendations",
    "uks_visits",
    "uks_medications",
    "medicine_inventory",
    "school_settings",
    "medicine_transactions",
]


def _table_exists(table_name: str) -> bool:
    return table_name in inspect(op.get_bind()).get_table_names()


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table_name)}


def _index_exists(table_name: str, index_name: str) -> bool:
    return any(index["name"] == index_name for index in inspect(op.get_bind()).get_indexes(table_name))


def _foreign_key_exists(table_name: str, fk_name: str) -> bool:
    return any(fk["name"] == fk_name for fk in inspect(op.get_bind()).get_foreign_keys(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if not _table_exists("schools"):
        op.create_table(
            "schools",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("school_code", sa.String(length=50), nullable=False),
            sa.Column("school_name", sa.String(length=255), nullable=False),
            sa.Column("province", sa.String(length=100), nullable=True),
            sa.Column("city", sa.String(length=100), nullable=True),
            sa.Column("address", sa.String(length=500), nullable=True),
            sa.Column("phone", sa.String(length=50), nullable=True),
            sa.Column("email", sa.String(length=255), nullable=True),
            sa.Column("logo_url", sa.String(length=500), nullable=True),
            sa.Column("principal_name", sa.String(length=200), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.UniqueConstraint("school_code", name="uq_schools_school_code"),
        )
        op.create_index("ix_schools_school_code", "schools", ["school_code"])
        op.create_index("ix_schools_is_active", "schools", ["is_active"])

    bind.execute(
        text(
            """
            INSERT INTO schools (school_code, school_name, is_active)
            SELECT 'SR-DEMO', 'Sekolah Rakyat Demo', TRUE
            WHERE NOT EXISTS (SELECT 1 FROM schools WHERE school_code = 'SR-DEMO')
            """
        )
    )

    default_school_id = bind.execute(
        text("SELECT id FROM schools WHERE school_code = 'SR-DEMO' ORDER BY id LIMIT 1")
    ).scalar_one()

    for table_name in TENANT_TABLES:
        if not _table_exists(table_name):
            continue
        if "school_id" not in _columns(table_name):
            op.add_column(table_name, sa.Column("school_id", sa.Integer(), nullable=True))
        index_name = f"ix_{table_name}_school_id"
        if not _index_exists(table_name, index_name):
            op.create_index(index_name, table_name, ["school_id"])
        bind.execute(
            text(f"UPDATE {table_name} SET school_id = :school_id WHERE school_id IS NULL"),
            {"school_id": default_school_id},
        )
        fk_name = f"fk_{table_name}_school_id_schools"
        if dialect != "sqlite" and not _foreign_key_exists(table_name, fk_name):
            op.create_foreign_key(fk_name, table_name, "schools", ["school_id"], ["id"])

    if dialect.startswith("postgresql"):
        bind.execute(text("ALTER TABLE medicine_inventory DROP CONSTRAINT IF EXISTS medicine_inventory_name_key"))


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    for table_name in reversed(TENANT_TABLES):
        if not _table_exists(table_name) or "school_id" not in _columns(table_name):
            continue
        fk_name = f"fk_{table_name}_school_id_schools"
        if dialect != "sqlite" and _foreign_key_exists(table_name, fk_name):
            op.drop_constraint(fk_name, table_name, type_="foreignkey")
        index_name = f"ix_{table_name}_school_id"
        if _index_exists(table_name, index_name):
            op.drop_index(index_name, table_name=table_name)
        op.drop_column(table_name, "school_id")

    if _table_exists("schools"):
        op.drop_table("schools")
