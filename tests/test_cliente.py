"""O cliente HTTP diante de token vencido, limite de requisições e fonte instável."""

from __future__ import annotations

import pytest

from conectores.cliente import ClienteApi, ErroDeApi, FonteIndisponivel

from .conftest import EMPRESA

TOTAL = "/reservas/v1/produtos/total"


def test_erro_passageiro_e_repetido_com_espera_crescente(cliente, caos, esperas):
    caos.erros_500 = 2

    assert cliente.get(TOTAL, empresa=EMPRESA)["total"] == 120
    assert len(esperas) == 2
    assert esperas[0] <= 0.5 <= esperas[1]  # 1ª espera até 0,5s; a 2ª, de 0,5s a 1s


def test_limite_de_requisicoes_espera_o_que_a_fonte_pediu(cliente, caos, esperas):
    caos.limite_429 = 1

    cliente.get(TOTAL, empresa=EMPRESA)

    assert esperas == [2.0]  # o Retry-After do simulador


def test_token_vencido_e_renovado_sem_gastar_tentativa(cliente, app, esperas):
    cliente.get(TOTAL, empresa=EMPRESA)
    app.state.tokens.clear()

    assert cliente.get(TOTAL, empresa=EMPRESA)["total"] == 120
    assert esperas == []


def test_erro_de_quem_chamou_nao_e_repetido(cliente, caos):
    with pytest.raises(ErroDeApi):
        cliente.get(TOTAL, empresa="empresa-que-nao-existe")

    assert caos.requisicoes == 1


def test_fonte_fora_do_ar_desiste_depois_das_tentativas(cliente, caos, esperas):
    caos.respostas_ate_cair = 0

    with pytest.raises(FonteIndisponivel):
        cliente.get(TOTAL, empresa=EMPRESA)

    assert caos.requisicoes == 5
    assert len(esperas) == 4


def test_pagina_de_erro_com_status_200_e_tratada_como_falha_passageira(cliente, caos, esperas):
    """Um proxy no caminho responde HTML com status 200. Não é dado, e não é
    motivo para desistir."""
    caos.paginas_de_erro = 1

    assert cliente.get(TOTAL, empresa=EMPRESA)["total"] == 120
    assert len(esperas) == 1


def test_servico_de_token_fora_do_ar_tambem_e_repetido(cliente, caos, esperas):
    caos.erros_no_token = 2

    assert cliente.get(TOTAL, empresa=EMPRESA)["total"] == 120
    assert len(esperas) == 2


def test_token_e_renovado_antes_de_vencer(api, app, caos):
    """A fonte nunca chega a recusar: o cliente troca o token pela validade informada."""
    agora = [0.0]
    cliente = ClienteApi(api, "demo", "demo-secret", relogio=lambda: agora[0])
    caos.validade_do_token = 600

    cliente.get(TOTAL, empresa=EMPRESA)
    agora[0] = 500  # ainda dentro da validade, com folga
    cliente.get(TOTAL, empresa=EMPRESA)
    assert len(app.state.tokens) == 1

    agora[0] = 560  # a menos de um minuto de vencer
    cliente.get(TOTAL, empresa=EMPRESA)
    assert len(app.state.tokens) == 2


def test_credencial_errada_falha_na_hora(api):
    intruso = ClienteApi(api, "demo", "senha-errada")

    with pytest.raises(ErroDeApi):
        intruso.get(TOTAL, empresa=EMPRESA)
