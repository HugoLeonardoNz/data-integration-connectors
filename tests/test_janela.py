"""Anúncios: os números dos últimos dias são revistos pela plataforma."""

from __future__ import annotations

from decimal import Decimal

from conectores.fontes import CAMPANHAS, DIAS_DE_REVISAO_DE_ANUNCIOS

from .conftest import EMPRESA

CAMPANHAS_NO_TESTE = 6  # 3 plataformas, 2 campanhas em cada


def _investimento_na_fonte(mundo) -> Decimal:
    return sum(Decimal(str(i["spend"])) for i in mundo.insights[EMPRESA])


def _investimento_no_banco(conn) -> Decimal:
    return conn.execute("select sum(investimento) as total from core.campanha_dia").fetchone()[
        "total"
    ]


def test_carga_inicial_traz_todos_os_dias(rodar, contar, conn, mundo):
    rodar(CAMPANHAS)

    assert contar("core.campanha_dia") == len(mundo.insights[EMPRESA]) == 20 * CAMPANHAS_NO_TESTE
    assert _investimento_no_banco(conn) == _investimento_na_fonte(mundo)


def test_numero_revisto_pela_plataforma_e_corrigido_sem_duplicar(rodar, contar, conn, mundo):
    rodar(CAMPANHAS)
    revistos = mundo.rever_ultimos_dias(EMPRESA, dias=3)

    resultado = rodar(CAMPANHAS)

    assert resultado.contagem.atualizadas == revistos == 3 * CAMPANHAS_NO_TESTE
    assert resultado.contagem.inseridas == 0
    assert contar("core.campanha_dia") == len(mundo.insights[EMPRESA])
    assert _investimento_no_banco(conn) == _investimento_na_fonte(mundo)


def test_dia_novo_entra_e_so_a_janela_e_relida(rodar, mundo):
    rodar(CAMPANHAS)
    mundo.novo_dia(EMPRESA)

    resultado = rodar(CAMPANHAS)

    assert resultado.contagem.inseridas == CAMPANHAS_NO_TESTE
    # A janela de revisão, o último dia já lido e o dia novo. Não os 21 dias.
    assert resultado.contagem.lidas == (DIAS_DE_REVISAO_DE_ANUNCIOS + 2) * CAMPANHAS_NO_TESTE
