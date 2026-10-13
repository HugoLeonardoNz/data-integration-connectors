"""Aviso de falha. Sempre vai para o log; vai para um webhook se houver um configurado."""

from __future__ import annotations

import logging

import httpx

from . import config

log = logging.getLogger("conectores.alerta")


def avisar(titulo: str, detalhe: str) -> None:
    log.error("%s | %s", titulo, detalhe)
    if not config.ALERTA_WEBHOOK_URL:
        return
    try:
        httpx.post(
            config.ALERTA_WEBHOOK_URL,
            json={"text": f"{titulo}\n{detalhe}"},
            timeout=10,
        ).raise_for_status()
    except httpx.HTTPError as erro:
        # O aviso que não saiu não pode derrubar a rotina, mas tem que deixar rastro.
        log.error("alerta não entregue: %s", erro)
