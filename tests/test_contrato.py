"""Quando a fonte manda dado ruim: um item isolado, ou o formato inteiro mudado."""

from __future__ import annotations

from dataclasses import replace

import pytest

from conectores import motor
from conectores.contrato import ContratoQuebrado
from conectores.fontes import PRODUTOS, _produto

from .conftest import EMPRESA


def test_item_ruim_fica_separado_e_o_resto_do_lote_entra(rodar, contar, conn, mundo, avisos):
    mundo.produtos[EMPRESA][30]["price"] = -10
    mundo.produtos[EMPRESA][31]["name"] = None

    resultado = rodar(PRODUTOS)

    assert resultado.contagem.rejeitadas == 2
    assert contar("core.produto") == len(mundo.produtos[EMPRESA]) - 2
    motivos = [r["motivo"] for r in conn.execute("select motivo from ops.rejeitado order by id")]
    assert sorted(motivos) == ["campo 'name' ausente", "campo 'price' negativo: -10"]
    # Faltam dois no banco, e isso não passa calado.
    assert resultado.conferencia == "divergente"
    assert "não confere" in avisos[0]


def test_item_recusado_sai_da_fila_quando_a_fonte_corrige(rodar, contar, mundo):
    mundo.produtos[EMPRESA][30]["price"] = -10
    rodar(PRODUTOS)
    assert contar("ops.rejeitado") == 1

    mundo.alterar_produto(EMPRESA, 30, price=180.0)
    resultado = rodar(PRODUTOS)

    assert contar("ops.rejeitado") == 0
    assert resultado.conferencia == "ok"


def test_poucos_itens_ruins_nao_sao_confundidos_com_mudanca_de_formato(rodar, contar, mundo):
    """Dois de três itens sem nome é maioria, mas é pouco para parar a rotina."""
    rodar(PRODUTOS)
    mundo.alterar_produto(EMPRESA, 10, name=None)
    mundo.alterar_produto(EMPRESA, 11, name=None)

    resultado = rodar(PRODUTOS)

    assert resultado.contagem.lidas == 3
    assert resultado.contagem.rejeitadas == 2
    assert contar("ops.rejeitado") == 2

    rodar(PRODUTOS)  # o item ruim é relido, mas não entra duas vezes na fila

    assert contar("ops.rejeitado") == 2


@pytest.fixture
def campo_renomeado(rodar, caos, mundo, conn):
    """Carga normal; depois a fonte troca `price` por `price_amount` sem avisar
    e 30 produtos mudam de preço. Devolve o id da execução que falhou.

    A execução lê 31 itens: os 30 alterados e o último da carga anterior, que
    empata com o marcador e é relido."""
    rodar(PRODUTOS)
    for indice in range(40, 70):
        mundo.alterar_produto(EMPRESA, indice, price=555.55)
    caos.renomear = {"produtos": {"price": "price_amount"}}

    with pytest.raises(ContratoQuebrado, match="campo 'price' ausente em 31 de 31"):
        rodar(PRODUTOS)

    return conn.execute("select id from ops.execucao where situacao = 'falhou'").fetchone()["id"]


def test_campo_renomeado_para_a_execucao_sem_estragar_o_que_ja_existe(
    campo_renomeado, conn, marcador, avisos
):
    # Nenhum preço novo entrou e nenhum preço antigo foi apagado.
    assert conn.execute("select count(*) as n from core.produto").fetchone()["n"] == 120
    assert conn.execute(
        "select count(*) as n from core.produto where preco = 555.55"
    ).fetchone()["n"] == 0
    # O marcador ficou onde estava: nada do que falhou foi dado como lido.
    execucao = conn.execute(
        "select marcador_inicial, marcador_final from ops.execucao where id = %s",
        [campo_renomeado],
    ).fetchone()
    assert execucao["marcador_final"] == execucao["marcador_inicial"] == marcador(PRODUTOS)
    # A resposta que chegou está guardada, e alguém foi avisado.
    guardada = conn.execute(
        "select corpo from raw.pagina where execucao_id = %s", [campo_renomeado]
    ).fetchone()["corpo"]
    assert len(guardada) == 31 and "price_amount" in guardada[0]
    assert "reservas.produtos falhou" in avisos[-1]


def test_depois_de_corrigir_o_conector_o_bruto_e_reaplicado_sem_chamar_a_fonte(
    campo_renomeado, conn, caos, marcador
):
    corrigido = replace(
        PRODUTOS,
        converter=lambda item, empresa: _produto(
            {**item, "price": item.get("price_amount")}, empresa
        ),
    )
    chamadas_antes = caos.requisicoes
    marcador_antes = marcador(PRODUTOS)

    resultado = motor.reprocessar(conn, corrigido, campo_renomeado, avisar=lambda *_: None)

    assert resultado.contagem.atualizadas == 30
    assert caos.requisicoes == chamadas_antes
    assert marcador(PRODUTOS) > marcador_antes
    assert conn.execute(
        "select count(*) as n from core.produto where preco = 555.55"
    ).fetchone()["n"] == 30


def test_reprocesso_de_execucao_antiga_nao_passa_por_cima_de_dado_mais_novo(rodar, conn, mundo):
    """A execução 1 leu o preço antigo. Depois o preço mudou e foi lido de novo.
    Reaplicar a resposta bruta da execução 1 não pode trazer o preço antigo de volta."""
    primeira = rodar(PRODUTOS)
    alterado = mundo.alterar_produto(EMPRESA, 10, price=777.77)
    rodar(PRODUTOS)

    resultado = motor.reprocessar(conn, PRODUTOS, primeira.execucao, avisar=lambda *_: None)

    assert resultado.contagem.atualizadas == 0
    preco = conn.execute(
        "select preco from core.produto where id_origem = %s", [alterado["id"]]
    ).fetchone()["preco"]
    assert float(preco) == 777.77
