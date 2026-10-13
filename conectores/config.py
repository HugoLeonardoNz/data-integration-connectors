"""Configuração lida do ambiente. Os padrões batem com o docker-compose.yml."""

from __future__ import annotations

import os

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
