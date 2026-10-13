"""Os testes rodam contra um PostgreSQL de verdade e contra a API simulada
servida por HTTP numa porta local. Nenhuma espera é real: o cliente recebe uma
função de dormir que só anota quanto esperaria.

O banco usado é `conectores_teste`, criado aqui. O banco da demonstração não é
tocado.
"""

from __future__ import annotations

import os
import socket
import threading
import time
from contextlib import contextmanager
from functools import partial

import httpx
import psycopg
import pytest
import uvicorn

from conectores import banco, config, fontes, motor
from conectores.cliente import ClienteApi
from simulador.app import CLIENT_ID, CLIENT_SECRET, Caos, criar_app
from simulador.dados import Mundo, Tamanho

EMPRESA = "rota-sul"
BANCO_DE_TESTE = "conectores_teste"
URL_BASE = os.getenv("DATABASE_URL", config.DATABASE_URL)
URL_DE_TESTE = URL_BASE.rsplit("/", 1)[0] + "/" + BANCO_DE_TESTE

TABELAS = (
    "ops.execucao, ops.marcador, ops.rejeitado, raw.pagina, "
    "core.produto, core.campanha_dia, core.clique, core.lead, core.venda"
)


def limpar(conexao) -> None:
    conexao.execute(f"truncate {TABELAS} restart identity cascade")


def mundo_pequeno() -> Mundo:
    return Mundo(
        tamanho=Tamanho(produtos=120, campanhas_por_plataforma=2, dias=20, cliques=300, leads=200)
    )


@contextmanager
def no_ar(app):
    """Sobe a API simulada numa porta livre e devolve um cliente HTTP para ela."""
    soquete = socket.socket()
    soquete.bind(("127.0.0.1", 0))
    servidor = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    linha = threading.Thread(target=servidor.run, kwargs={"sockets": [soquete]}, daemon=True)
    linha.start()
    while not servidor.started:
        time.sleep(0.01)
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{soquete.getsockname()[1]}") as http:
            yield http
    finally:
        servidor.should_exit = True
        linha.join(timeout=5)


@pytest.fixture(scope="session")
def banco_de_teste() -> str:
    with psycopg.connect(URL_BASE, autocommit=True) as admin:
        existe = admin.execute(
            "select 1 from pg_database where datname = %s", [BANCO_DE_TESTE]
        ).fetchone()
        if not existe:
            admin.execute(f"create database {BANCO_DE_TESTE}")
    with banco.conectar(URL_DE_TESTE) as conn:
        conn.execute("drop schema if exists ops, raw, core, marts cascade")
        conn.execute("drop table if exists public.migracao")
        banco.migrar(conn)
    return URL_DE_TESTE


@pytest.fixture
def conn(banco_de_teste):
    with banco.conectar(banco_de_teste) as conexao:
        limpar(conexao)
        yield conexao


@pytest.fixture(autouse=True)
def paginas_pequenas(monkeypatch):
    """50 por página: o mundo de teste é pequeno e precisa de mais de uma página."""
    monkeypatch.setattr(fontes, "TAMANHO_DA_PAGINA", 50)


@pytest.fixture
def mundo() -> Mundo:
    return mundo_pequeno()


@pytest.fixture
def caos() -> Caos:
    return Caos()


@pytest.fixture
def app(mundo, caos):
    return criar_app(mundo, caos)


@pytest.fixture
def api(app):
    with no_ar(app) as http:
        yield http


@pytest.fixture
def esperas() -> list[float]:
    """Quanto o cliente teria esperado entre tentativas. Ninguém dorme no teste."""
    return []


@pytest.fixture
def cliente(api, esperas) -> ClienteApi:
    return ClienteApi(api, CLIENT_ID, CLIENT_SECRET, dormir=esperas.append)


@pytest.fixture
def avisos() -> list[str]:
    return []


@pytest.fixture
def rodar(conn, cliente, avisos):
    """rodar(RECURSO) sincroniza a empresa padrão; rodar(RECURSO, "outra") muda a empresa."""

    def _rodar(recurso, empresa=EMPRESA):
        return motor.sincronizar(
            conn, cliente, recurso, empresa, avisar=lambda t, d: avisos.append(f"{t} | {d}")
        )

    return _rodar


@pytest.fixture
def contar(conn):
    def _contar(tabela: str, empresa: str = EMPRESA) -> int:
        return conn.execute(
            f"select count(*) as n from {tabela} where empresa = %s", [empresa]
        ).fetchone()["n"]

    return _contar


@pytest.fixture
def marcador(conn):
    return partial(motor.ler_marcador, conn, empresa=EMPRESA)
