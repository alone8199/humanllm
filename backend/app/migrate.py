"""Tiny idempotent migration runner.

Applies every *.sql file in the migrations/ directory in lexical order, once,
tracking applied versions in `schema_migrations`. The SQL is written to be
portable across SQLite and PostgreSQL (no native enum types, VARCHAR for
status/role/kind, JSON for structured columns).
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.database import engine

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def _split(sql: str) -> list[str]:
    out, buf = [], []
    for line in sql.splitlines():
        if line.strip().startswith("--"):
            continue
        buf.append(line)
        if line.strip().endswith(";"):
            stmt = "\n".join(buf).strip()
            if stmt:
                out.append(stmt)
            buf = []
    tail = "\n".join(buf).strip()
    if tail:
        out.append(tail)
    return out


async def run_migrations(eng: AsyncEngine | None = None) -> list[str]:
    eng = eng or engine
    applied_versions: list[str] = []
    async with eng.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version TEXT PRIMARY KEY, applied_at TIMESTAMP)"
            )
        )
        rows = (await conn.execute(text("SELECT version FROM schema_migrations"))).fetchall()
        done = {r[0] for r in rows}

        for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = sql_file.stem
            if version in done:
                continue
            statements = _split(sql_file.read_text(encoding="utf-8"))
            for stmt in statements:
                await conn.execute(text(stmt))
            await conn.execute(
                text("INSERT INTO schema_migrations(version) VALUES (:v)"),
                {"v": version},
            )
            applied_versions.append(version)
    return applied_versions
