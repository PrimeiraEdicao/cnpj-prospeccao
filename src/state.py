from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, text


def _database_url() -> str:
    return os.getenv("DATABASE_URL", "sqlite:///data/contact_state.db")


def get_engine():
    url = _database_url()
    if url.startswith("sqlite:///"):
        path = Path(url.removeprefix("sqlite:///"))
        path.parent.mkdir(parents=True, exist_ok=True)
        return create_engine(url, future=True, connect_args={"check_same_thread": False})
    return create_engine(url, future=True, pool_pre_ping=True)


def init_db(engine=None):
    engine = engine or get_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS contact_attempts (
                attempt_id VARCHAR(64) PRIMARY KEY,
                cnpj VARCHAR(14) NOT NULL,
                phone VARCHAR(20),
                contact_name VARCHAR(255),
                message TEXT,
                attempted_at VARCHAR(40) NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS company_contact_state (
                cnpj VARCHAR(14) PRIMARY KEY,
                attempt_count INTEGER NOT NULL,
                first_attempt_at VARCHAR(40) NOT NULL,
                last_attempt_at VARCHAR(40) NOT NULL,
                last_phone VARCHAR(20),
                last_contact_name VARCHAR(255)
            )
        """))
    return engine


def record_attempt(
    attempt_id: str,
    cnpj: str,
    phone: str,
    contact_name: str,
    message: str,
    engine=None,
) -> bool:
    """Registra idempotentemente. Retorna True quando foi inserção nova."""
    engine = engine or init_db()
    now = datetime.now(timezone.utc).isoformat()
    with engine.begin() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM contact_attempts WHERE attempt_id = :attempt_id"),
            {"attempt_id": attempt_id},
        ).first()
        if exists:
            return False
        conn.execute(text("""
            INSERT INTO contact_attempts(attempt_id, cnpj, phone, contact_name, message, attempted_at)
            VALUES (:attempt_id, :cnpj, :phone, :contact_name, :message, :attempted_at)
        """), {
            "attempt_id": attempt_id,
            "cnpj": cnpj,
            "phone": phone,
            "contact_name": contact_name,
            "message": message,
            "attempted_at": now,
        })
        row = conn.execute(
            text("SELECT attempt_count, first_attempt_at FROM company_contact_state WHERE cnpj = :cnpj"),
            {"cnpj": cnpj},
        ).mappings().first()
        if row:
            conn.execute(text("""
                UPDATE company_contact_state
                SET attempt_count = :count,
                    last_attempt_at = :now,
                    last_phone = :phone,
                    last_contact_name = :contact_name
                WHERE cnpj = :cnpj
            """), {
                "count": int(row["attempt_count"]) + 1,
                "now": now,
                "phone": phone,
                "contact_name": contact_name,
                "cnpj": cnpj,
            })
        else:
            conn.execute(text("""
                INSERT INTO company_contact_state(
                    cnpj, attempt_count, first_attempt_at, last_attempt_at, last_phone, last_contact_name
                ) VALUES (:cnpj, 1, :now, :now, :phone, :contact_name)
            """), {
                "cnpj": cnpj,
                "now": now,
                "phone": phone,
                "contact_name": contact_name,
            })
    return True


def get_states(cnpjs: list[str] | None = None, engine=None):
    engine = engine or init_db()
    with engine.begin() as conn:
        if not cnpjs:
            rows = conn.execute(text("SELECT * FROM company_contact_state")).mappings().all()
            return [dict(r) for r in rows]

        # Faz lotes pequenos para não depender do limite de parâmetros de SQLite/Postgres.
        all_rows = []
        batch_size = 500
        for start in range(0, len(cnpjs), batch_size):
            batch = cnpjs[start:start + batch_size]
            placeholders = ",".join(f":v{i}" for i in range(len(batch)))
            params = {f"v{i}": c for i, c in enumerate(batch)}
            rows = conn.execute(
                text(f"SELECT * FROM company_contact_state WHERE cnpj IN ({placeholders})"),
                params,
            ).mappings().all()
            all_rows.extend(rows)
    return [dict(r) for r in all_rows]
