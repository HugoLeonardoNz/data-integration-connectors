"""Situação de cada rotina, para o comando `status` e para quem monitora."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from psycopg import Connection

from . import config


@dataclass(frozen=True)
class Rotina:
    fonte: str
    recurso: str
    empresa: str
    problema: str | None
    ultimo_sucesso: datetime | None
    marcador: str | None
    rejeitados: int


def situacao(
    conn: Connection,
    *,
    agora: datetime | None = None,
    tolerancia_horas: float | None = None,
) -> list[Rotina]:
    """Lê `marts.saude_das_fontes` e diz o que há de errado em cada rotina.

    "Atrasada" é o alerta do silêncio: a rotina que nem chegou a rodar não
    grava falha nenhuma, então o que denuncia é o tempo sem sucesso.
    """
    agora = agora or datetime.now(UTC)
    limite = timedelta(
        hours=config.HORAS_DE_TOLERANCIA if tolerancia_horas is None else tolerancia_horas
    )
    rotinas = []
    for linha in conn.execute(
        "select * from marts.saude_das_fontes order by fonte, recurso, empresa"
    ):
        sucesso = linha["ultimo_sucesso"]
        if linha["ultima_situacao"] == "falhou":
            problema = f"falhou: {linha['ultimo_erro']}"
        elif sucesso is None:
            problema = "nunca terminou com sucesso"
        elif agora - sucesso > limite:
            horas = (agora - sucesso).total_seconds() / 3600
            problema = f"atrasada: {horas:.0f}h sem sucesso"
        elif linha["conferencia"] == "divergente":
            problema = "contagem não confere com a fonte"
        elif linha["rejeitados"]:
            problema = f"{linha['rejeitados']} item(ns) recusado(s)"
        else:
            problema = None
        rotinas.append(
            Rotina(
                linha["fonte"], linha["recurso"], linha["empresa"], problema,
                sucesso, linha["marcador"], linha["rejeitados"],
            )
        )
    return rotinas
