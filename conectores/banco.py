"""Conexão com o PostgreSQL e aplicação das migrações."""

from __future__ import annotations

from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from . import config

PASTA_SQL = Path(__file__).resolve().parent.parent / "sql"


def conectar(url: str | None = None) -> psycopg.Connection:
    """Abre a conexão em autocommit.

    O motor abre transação explícita só em volta do que precisa ser atômico
    (o lote e o marcador). O resto, como o registro de uma falha, é gravado na
    hora e não se perde num rollback.
    """
    return psycopg.connect(url or config.DATABASE_URL, autocommit=True, row_factory=dict_row)


def migrar(conn: psycopg.Connection) -> list[str]:
    """Aplica, em ordem, os arquivos de `sql/` que ainda não rodaram."""
    conn.execute(
        "create table if not exists public.migracao ("
        "arquivo text primary key, aplicada_em timestamptz not null default now())"
    )
    feitas = {linha["arquivo"] for linha in conn.execute("select arquivo from public.migracao")}
    aplicadas = []
    for arquivo in sorted(PASTA_SQL.glob("*.sql")):
        if arquivo.name in feitas:
            continue
        with conn.transaction():
            conn.execute(arquivo.read_text(encoding="utf-8"))
            conn.execute("insert into public.migracao (arquivo) values (%s)", [arquivo.name])
        aplicadas.append(arquivo.name)
    return aplicadas
