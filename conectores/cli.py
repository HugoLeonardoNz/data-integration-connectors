"""Linha de comando.

    python -m conectores migrar
    python -m conectores ciclo                      # tudo, de todas as empresas
    python -m conectores sincronizar crm.leads --empresa rota-sul
    python -m conectores status                     # sai com 1 se houver problema
    python -m conectores reprocessar crm.leads 42   # reaplica o bruto da execução 42
    python -m conectores agendar --intervalo 900
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

import httpx

from . import banco, config, saude
from .cliente import ClienteApi
from .fontes import RECURSOS
from .motor import JaEmExecucao, reprocessar, sincronizar

log = logging.getLogger("conectores")


def _cliente() -> ClienteApi:
    http = httpx.Client(base_url=config.API_URL, timeout=30)
    return ClienteApi(http, config.API_CLIENT_ID, config.API_CLIENT_SECRET)


def _ciclo(conn, cliente, recursos, empresas) -> int:
    """Roda cada recurso de cada empresa. A falha de um não impede os outros."""
    falhas = 0
    for recurso in recursos:
        for empresa in empresas:
            try:
                r = sincronizar(conn, cliente, recurso, empresa)
            except JaEmExecucao:
                log.warning("%s %s: já está rodando, pulado", recurso.rotulo, empresa)
            except Exception:
                if conn.closed:
                    # Sem banco não há ciclo. O processo cai, e quem o agenda
                    # (cron, Docker) sobe outro com conexão nova.
                    raise
                falhas += 1  # o motor já registrou a falha e avisou
            else:
                c = r.contagem
                print(
                    f"{recurso.rotulo:<20} {empresa:<15} lidas {c.lidas:>5}  "
                    f"novas {c.inseridas:>5}  alteradas {c.atualizadas:>5}  "
                    f"recusadas {c.rejeitadas:>3}  conferência {r.conferencia or '-'}"
                )
    return falhas


def _status(conn) -> int:
    rotinas = saude.situacao(conn)
    if not rotinas:
        print("nenhuma execução registrada")
        return 1
    for r in rotinas:
        sucesso = r.ultimo_sucesso.astimezone().strftime("%d/%m %H:%M") if r.ultimo_sucesso else "-"
        print(
            f"{'ATENÇÃO' if r.problema else 'ok':<8} {r.fonte + '.' + r.recurso:<20} "
            f"{r.empresa:<15} último sucesso {sucesso:<12} {r.problema or ''}"
        )
    return 1 if any(r.problema for r in rotinas) else 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    p = argparse.ArgumentParser(prog="conectores", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="comando", required=True)
    sub.add_parser("migrar", help="aplica as migrações pendentes")
    sub.add_parser("ciclo", help="sincroniza todos os recursos de todas as empresas")
    sub.add_parser("status", help="mostra a situação de cada rotina")
    s = sub.add_parser("sincronizar", help="sincroniza um recurso")
    s.add_argument("recurso", choices=sorted(RECURSOS))
    s.add_argument("--empresa", action="append", help="pode repetir; padrão: todas")
    r = sub.add_parser("reprocessar", help="reaplica as páginas brutas de uma execução")
    r.add_argument("recurso", choices=sorted(RECURSOS))
    r.add_argument("execucao", type=int)
    a = sub.add_parser("agendar", help="repete o ciclo a cada intervalo")
    a.add_argument("--intervalo", type=int, default=900, help="segundos entre ciclos")
    args = p.parse_args(argv)

    with banco.conectar() as conn:
        if args.comando == "migrar":
            aplicadas = banco.migrar(conn)
            print("aplicadas:", ", ".join(aplicadas) if aplicadas else "nenhuma pendente")
            return 0
        if args.comando == "status":
            return _status(conn)
        if args.comando == "reprocessar":
            c = reprocessar(conn, RECURSOS[args.recurso], args.execucao).contagem
            print(f"novas {c.inseridas}  alteradas {c.atualizadas}  recusadas {c.rejeitadas}")
            return 0

        cliente = _cliente()
        if args.comando == "sincronizar":
            empresas = args.empresa or config.EMPRESAS
            return 1 if _ciclo(conn, cliente, [RECURSOS[args.recurso]], empresas) else 0
        if args.comando == "ciclo":
            return 1 if _ciclo(conn, cliente, RECURSOS.values(), config.EMPRESAS) else 0
        while True:  # agendar
            _ciclo(conn, cliente, RECURSOS.values(), config.EMPRESAS)
            time.sleep(args.intervalo)


if __name__ == "__main__":
    sys.exit(main())
