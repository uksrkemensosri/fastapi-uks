from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, delete, func, inspect, select, text
from sqlalchemy.engine import Engine

from app.db.database import normalize_database_url
from app.db.models import Base


DEFAULT_SQLITE_PATH = Path("emr_keperawatan.db")
TABLE_ORDER = [
    "users",
    "patients",
    "school_settings",
    "medicine_inventory",
    "assessments",
    "uks_visits",
    "recommendations",
    "uks_medications",
]


def sqlite_url_from_path(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def backup_sqlite(sqlite_path: Path, backup_dir: Path) -> Path:
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite file not found: {sqlite_path}")

    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"{sqlite_path.stem}_before_postgres_migration_{timestamp}{sqlite_path.suffix}"
    shutil.copy2(sqlite_path, backup_path)
    return backup_path


def load_rows(source: Engine, table_name: str) -> list[dict[str, Any]]:
    table = Base.metadata.tables[table_name]
    with source.connect() as conn:
        if not inspect(conn).has_table(table_name):
            return []

        source_columns = {col["name"] for col in inspect(conn).get_columns(table_name)}
        selected_columns = [table.c[name] for name in table.c.keys() if name in source_columns]
        if not selected_columns:
            return []

        rows = conn.execute(select(*selected_columns)).mappings().all()
        return [dict(row) for row in rows]


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized = {}
    for key, value in row.items():
        if isinstance(value, str) and value and value[0] in "[{":
            try:
                normalized[key] = json.loads(value)
                continue
            except json.JSONDecodeError:
                pass
        normalized[key] = value
    return normalized


def table_count(engine: Engine, table_name: str) -> int:
    table = Base.metadata.tables[table_name]
    with engine.connect() as conn:
        if not inspect(conn).has_table(table_name):
            return 0
        return int(conn.execute(select(func.count()).select_from(table)).scalar_one())


def reset_target_tables(target: Engine) -> None:
    with target.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(delete(table))


def reset_postgres_sequences(target: Engine) -> None:
    sequence_tables = [
        ("users", "id"),
        ("assessments", "id"),
        ("recommendations", "id"),
        ("uks_visits", "id"),
        ("uks_medications", "id"),
        ("medicine_inventory", "id"),
        ("school_settings", "id"),
    ]

    with target.begin() as conn:
        for table_name, column_name in sequence_tables:
            if table_name not in Base.metadata.tables:
                continue
            conn.execute(
                text(
                    """
                    SELECT setval(
                        pg_get_serial_sequence(:table_name, :column_name),
                        COALESCE((SELECT MAX(id) FROM {table_name}), 1),
                        (SELECT COUNT(*) FROM {table_name}) > 0
                    )
                    """.format(table_name=table_name)
                ),
                {"table_name": table_name, "column_name": column_name},
            )


def migrate(sqlite_path: Path, postgres_url: str, backup_dir: Path, replace: bool) -> None:
    postgres_url = normalize_database_url(postgres_url)
    if postgres_url.startswith("sqlite"):
        raise ValueError("Target DATABASE_URL must be PostgreSQL, not SQLite.")

    backup_path = backup_sqlite(sqlite_path, backup_dir)
    print(f"SQLite backup created: {backup_path}")

    source = create_engine(sqlite_url_from_path(sqlite_path), future=True)
    target = create_engine(postgres_url, future=True)

    Base.metadata.create_all(bind=target)

    target_has_data = any(table_count(target, name) > 0 for name in TABLE_ORDER if name in Base.metadata.tables)
    if target_has_data and not replace:
        raise RuntimeError(
            "PostgreSQL target already has data. Re-run with --replace to clear target tables first."
        )

    if replace:
        reset_target_tables(target)
        print("Target PostgreSQL tables cleared.")

    total_rows = 0
    with target.begin() as conn:
        for table_name in TABLE_ORDER:
            if table_name not in Base.metadata.tables:
                continue

            rows = [normalize_row(row) for row in load_rows(source, table_name)]
            if not rows:
                print(f"{table_name}: 0 rows")
                continue

            table = Base.metadata.tables[table_name]
            conn.execute(table.insert(), rows)
            total_rows += len(rows)
            print(f"{table_name}: {len(rows)} rows")

    reset_postgres_sequences(target)
    print(f"Migration complete. Total rows copied: {total_rows}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backup SQLite and migrate data to PostgreSQL Railway.")
    parser.add_argument("--sqlite", default=str(DEFAULT_SQLITE_PATH), help="SQLite DB path. Default: emr_keperawatan.db")
    parser.add_argument("--postgres-url", default=os.getenv("DATABASE_URL"), help="Railway PostgreSQL DATABASE_URL")
    parser.add_argument("--backup-dir", default="backups", help="Backup directory. Default: backups")
    parser.add_argument("--replace", action="store_true", help="Clear PostgreSQL tables before importing data")
    args = parser.parse_args()

    if not args.postgres_url:
        raise RuntimeError("Set DATABASE_URL or pass --postgres-url with your Railway PostgreSQL URL.")

    migrate(
        sqlite_path=Path(args.sqlite),
        postgres_url=args.postgres_url,
        backup_dir=Path(args.backup_dir),
        replace=args.replace,
    )


if __name__ == "__main__":
    main()
