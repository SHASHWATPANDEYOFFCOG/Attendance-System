"""Additive schema migration for SQLite.

`Base.metadata.create_all` creates missing *tables* but never touches an existing table, so a
database created before the organisation/timetable domain was added would silently lack the new
columns and fail at query time rather than at startup.

This module closes that gap by diffing the mapped metadata against the live database and
emitting `ALTER TABLE ... ADD COLUMN` / `CREATE INDEX` for anything missing.

Deliberate limits -- it is additive only:

* It never drops or retypes a column. SQLite cannot do either without a table rebuild, and a
  silent rebuild of a table holding attendance records is not something a migration should do
  unattended.
* Every new column must therefore be NULLable or carry a constant server default, and must not
  introduce a UNIQUE constraint. SQLite rejects all three in `ADD COLUMN`.

If you need a destructive change, write an explicit one-off script and back the file up first.
"""
from __future__ import annotations

from typing import Iterable

from sqlalchemy import Index, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.schema import CreateIndex

from app.models import Base
from occlubio.utils import get_logger

log = get_logger("app.migrate")


def _column_ddl(engine: Engine, column) -> str:
    """Render a single column as SQLite DDL."""
    type_sql = column.type.compile(engine.dialect)
    parts = [f'"{column.name}"', type_sql]

    if column.server_default is not None:
        parts.append(f"DEFAULT {column.server_default.arg}")
    elif not column.nullable:
        # ADD COLUMN NOT NULL needs a default; without one SQLite refuses on a non-empty table.
        raise RuntimeError(
            f"cannot add NOT NULL column {column.table.name}.{column.name} without a "
            f"server_default -- make it nullable or give it a server default"
        )
    if not column.nullable:
        parts.append("NOT NULL")
    return " ".join(parts)


def pending_changes(engine: Engine) -> tuple[list[str], list[Index]]:
    """Return (column DDL statements, indexes) that the live database is missing."""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    statements: list[str] = []
    missing_indexes: list[Index] = []

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue                                   # create_all will handle the whole table

        have = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name not in have:
                statements.append(
                    f'ALTER TABLE "{table.name}" ADD COLUMN {_column_ddl(engine, column)}'
                )

        have_idx = {i["name"] for i in inspector.get_indexes(table.name)}
        for index in table.indexes:
            if index.name not in have_idx:
                missing_indexes.append(index)

    return statements, missing_indexes


def migrate(engine: Engine | None = None) -> dict:
    """Create missing tables, then add missing columns and indexes. Idempotent."""
    if engine is None:
        from app.db import engine as default_engine
        engine = default_engine

    Base.metadata.create_all(engine)                   # new tables first
    statements, indexes = pending_changes(engine)

    applied: list[str] = []
    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
            applied.append(stmt)
            log.info("migrated: %s", stmt)
        for index in indexes:
            # A new index on a pre-existing table; the column it covers was just added above.
            try:
                conn.execute(CreateIndex(index))
                applied.append(f"CREATE INDEX {index.name}")
                log.info("migrated: CREATE INDEX %s", index.name)
            except Exception as exc:                    # noqa: BLE001 - index may already exist
                log.debug("index %s skipped: %s", index.name, exc)

    if not applied:
        log.info("schema up to date")
    return {"applied": applied, "count": len(applied)}


def describe(engine: Engine | None = None) -> Iterable[str]:
    """What migrate() would do, without doing it."""
    if engine is None:
        from app.db import engine as default_engine
        engine = default_engine
    statements, indexes = pending_changes(engine)
    return statements + [f"CREATE INDEX {i.name}" for i in indexes]


if __name__ == "__main__":
    import sys

    from app.db import engine as default_engine

    if "--dry-run" in sys.argv:
        todo = list(describe(default_engine))
        print("\n".join(todo) if todo else "schema up to date")
    else:
        result = migrate(default_engine)
        print(f"applied {result['count']} change(s)")
        for line in result["applied"]:
            print("  " + line)
