"""Configuração lida do ambiente. Os padrões batem com o docker-compose.yml."""

from __future__ import annotations

import os
from pathlib import Path


def _carregar_env() -> None:
    """Lê o `.env` da raiz do projeto, se existir. O que já está no ambiente vale mais."""
    arquivo = Path(__file__).resolve().parent.parent / ".env"
    if not arquivo.exists():
        return
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        chave, igual, valor = linha.partition("=")
        if igual and not chave.lstrip().startswith("#"):
            os.environ.setdefault(chave.strip(), valor.strip())


_carregar_env()

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://conectores:conectores@localhost:5544/conectores"
)
API_URL = os.getenv("API_URL", "http://localhost:8090")
API_CLIENT_ID = os.getenv("API_CLIENT_ID", "demo")
API_CLIENT_SECRET = os.getenv("API_CLIENT_SECRET", "demo-secret")

EMPRESAS = tuple(
    e.strip()
    for e in os.getenv("EMPRESAS", "rota-sul,rota-nordeste,rota-serra").split(",")
    if e.strip()
)

# Rotina sem sucesso há mais tempo que isso aparece como atrasada no `status`.
HORAS_DE_TOLERANCIA = float(os.getenv("HORAS_DE_TOLERANCIA", "26"))

ALERTA_WEBHOOK_URL = os.getenv("ALERTA_WEBHOOK_URL", "")
