"""Ligar a venda à campanha, com parte dos leads chegando sem origem."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal

import pytest

from conectores import banco, motor
from conectores.cliente import ClienteApi
from conectores.fontes import RECURSOS
from simulador.app import CLIENT_ID, CLIENT_SECRET, criar_app
from simulador.dados import EMPRESAS

from .conftest import EMPRESA, limpar, mundo_pequeno, no_ar

# Como o simulador gerou cada lead -> o que a visão deve concluir.
ESPERADO = {
    "clique": "clique",
    "formulario": "formulario",
    "utm": "utm",
    "nenhuma": "nao_identificada",
}


@pytest.fixture(scope="module")
def mundo():
    return mundo_pequeno()


@pytest.fixture(scope="module")
def conn(banco_de_teste, mundo):
    """Tudo carregado uma vez para o módulo: estes testes só leem."""
    with banco.conectar(banco_de_teste) as conexao, no_ar(criar_app(mundo)) as http:
        limpar(conexao)
        cliente = ClienteApi(http, CLIENT_ID, CLIENT_SECRET)
        for recurso in RECURSOS.values():
            for empresa in EMPRESAS:
                motor.sincronizar(conexao, cliente, recurso, empresa)
        yield conexao


def _reais(valores) -> Decimal:
    return sum((Decimal(str(v)) for v in valores), Decimal("0.00"))


def test_todo_lead_recebe_exatamente_uma_origem(conn, mundo):
    linhas = conn.execute("select empresa, id_lead from marts.atribuicao_lead").fetchall()

    total = sum(len(mundo.leads[e]) for e in EMPRESAS)
    assert len(linhas) == total
    assert len({(linha["empresa"], linha["id_lead"]) for linha in linhas}) == total


def test_a_origem_encontrada_e_a_que_o_lead_realmente_teve(conn, mundo):
    encontrada = {
        linha["id_lead"]: linha["metodo"]
        for linha in conn.execute(
            "select id_lead, metodo from marts.atribuicao_lead where empresa = %s", [EMPRESA]
        )
    }

    for lead in mundo.leads[EMPRESA]:
        assert encontrada[lead["id"]] == ESPERADO[lead["_origem"]], lead["id"]


def test_lead_sem_origem_aparece_como_nao_identificado_e_nao_e_rateado(
    conn, mundo
):
    sem_origem = Counter(lead["_origem"] for lead in mundo.leads[EMPRESA])["nenhuma"]

    linha = conn.execute(
        "select leads from marts.resultado_por_campanha "
        "where empresa = %s and plataforma = 'nao_identificada'",
        [EMPRESA],
    ).fetchone()

    assert sem_origem > 0
    assert linha["leads"] == sem_origem


@pytest.mark.parametrize("empresa", EMPRESAS)
def test_receita_e_investimento_do_painel_fecham_com_a_fonte(conn, mundo, empresa):
    painel = conn.execute(
        "select sum(receita) as receita, sum(investimento) as investimento, sum(vendas) as vendas "
        "from marts.resultado_por_campanha where empresa = %s",
        [empresa],
    ).fetchone()

    ganhas = [v for v in mundo.vendas[empresa] if v["status"] == "won"]
    assert painel["vendas"] == len(ganhas)
    assert painel["receita"] == _reais(v["amount"] for v in ganhas)
    assert painel["investimento"] == _reais(i["spend"] for i in mundo.insights[empresa])


def test_venda_de_balcao_sem_lead_entra_como_nao_identificada(conn, mundo):
    de_balcao = [
        v for v in mundo.vendas[EMPRESA] if v["lead_id"] is None and v["status"] == "won"
    ]
    sem_origem = {lead["id"] for lead in mundo.leads[EMPRESA] if lead["_origem"] == "nenhuma"}
    de_lead_sem_origem = [
        v for v in mundo.vendas[EMPRESA] if v["lead_id"] in sem_origem and v["status"] == "won"
    ]

    linha = conn.execute(
        "select vendas, receita from marts.resultado_por_campanha "
        "where empresa = %s and plataforma = 'nao_identificada'",
        [EMPRESA],
    ).fetchone()

    assert de_balcao, "o mundo de teste precisa ter venda de balcão ganha"
    assert linha["vendas"] == len(de_balcao) + len(de_lead_sem_origem)
    assert linha["receita"] == _reais(v["amount"] for v in de_balcao + de_lead_sem_origem)
