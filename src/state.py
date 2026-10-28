from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, text


def _database_url() -> str:
    return os.getenv("DATABASE_URL", "sqlite:///data/contact_state.db")


def get_engine():
    url = _database_url()
    # URLs padrão de Supabase/Neon precisam usar o driver psycopg 3 instalado.
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url.removeprefix("postgres://")
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url.removeprefix("postgresql://")
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
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS company_reviews (
                cnpj VARCHAR(14) PRIMARY KEY,
                status VARCHAR(20) NOT NULL,
                source TEXT NOT NULL,
                reviewed_at VARCHAR(40) NOT NULL
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
        result = conn.execute(text("""
            INSERT INTO contact_attempts(attempt_id, cnpj, phone, contact_name, message, attempted_at)
            VALUES (:attempt_id, :cnpj, :phone, :contact_name, :message, :attempted_at)
            ON CONFLICT (attempt_id) DO NOTHING
        """), {
            "attempt_id": attempt_id,
            "cnpj": cnpj,
            "phone": phone,
            "contact_name": contact_name,
            "message": message,
            "attempted_at": now,
        })
        if result.rowcount == 0:
            return False
        # Incremento atômico: abas concorrentes não perdem tentativas nem duplicam o mesmo clique.
        conn.execute(text("""
            INSERT INTO company_contact_state(
                cnpj, attempt_count, first_attempt_at, last_attempt_at, last_phone, last_contact_name
            ) VALUES (:cnpj, 1, :now, :now, :phone, :contact_name)
            ON CONFLICT (cnpj) DO UPDATE SET
                attempt_count = company_contact_state.attempt_count + 1,
                last_attempt_at = excluded.last_attempt_at,
                last_phone = excluded.last_phone,
                last_contact_name = excluded.last_contact_name
        """), {"cnpj": cnpj, "now": now, "phone": phone, "contact_name": contact_name})
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


def import_reviews(records, engine=None) -> tuple[int, int]:
    """Persiste revisões sem inventar tentativas, telefones ou mensagens enviadas."""
    from .reviews import REVIEW_LABELS, import_cnpj
    records = list(records)
    if any(import_cnpj(row.get("cnpj")) != row.get("cnpj") or row.get("status") not in REVIEW_LABELS
           for row in records):
        raise ValueError("A lista de revisão contém CNPJ ou motivo inválido.")
    records = list({row["cnpj"]: row for row in records}.values())
    engine = engine or init_db()
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    with engine.begin() as conn:
        for row in records:
            result = conn.execute(text("""
                INSERT INTO company_reviews(cnpj, status, source, reviewed_at)
                VALUES (:cnpj, :status, :source, :reviewed_at)
                ON CONFLICT (cnpj) DO NOTHING
            """), {"cnpj": row["cnpj"], "status": row["status"],
                   "source": row.get("source", ""), "reviewed_at": now})
            inserted += int(result.rowcount > 0)
    return inserted, len(records) - inserted


def get_reviews(engine=None):
    engine = engine or init_db()
    with engine.connect() as conn:
        return [dict(row) for row in conn.execute(text("SELECT * FROM company_reviews")).mappings()]


def confirm_contacts(cnpjs, visible, engine=None, registry_writer=None) -> tuple[int, int]:
    """Confirma só empresas selecionáveis da página atual, em uma transação.

    A confirmação é independente de abertura e não inventa envio/entrega pelo WhatsApp.
    """
    from .reviews import import_cnpj
    if not isinstance(cnpjs, list) or not cnpjs or len(cnpjs) > 100:
        raise ValueError("Selecione de 1 a 100 empresas da página atual.")
    if any(not isinstance(n, str) or import_cnpj(n) != n for n in cnpjs):
        raise ValueError("A seleção contém um CNPJ inválido.")
    numbers = list(dict.fromkeys(cnpjs))
    allowed = set(visible.loc[~visible["reviewed"], "cnpj"].astype(str))
    if not set(numbers).issubset(allowed):
        raise ValueError("A seleção mudou ou contém uma empresa revisada. Atualize a lista.")
    records = [{"cnpj": n, "status": "contatado", "source": "Confirmação manual no aplicativo"} for n in numbers]
    if registry_writer is not None:
        registry_writer(records)
    return import_reviews(records, engine)
