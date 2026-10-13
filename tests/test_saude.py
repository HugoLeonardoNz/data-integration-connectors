"""Como se fica sabendo que uma rotina falhou, ou que nem rodou."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from conectores import saude
from conectores.cliente import FonteIndisponivel
from conectores.fontes import CAMPANHAS, LEADS, PRODUTOS


def test_rotina_em_dia_nao_tem_problema(rodar, conn):
    rodar(PRODUTOS)

    (rotina,) = saude.situacao(conn)

    assert rotina.problema is None
    assert rotina.ultimo_sucesso is not None


def test_falha_aparece_com_o_motivo_e_mantem_a_data_do_ultimo_sucesso(rodar, conn, caos):
    rodar(PRODUTOS)
    caos.respostas_ate_cair = 0
    with pytest.raises(FonteIndisponivel):
        rodar(PRODUTOS)

    (rotina,) = saude.situacao(conn)

    assert rotina.problema.startswith("falhou: FonteIndisponivel")
    assert rotina.ultimo_sucesso is not None  # o painel sabe até quando o dado vale


def test_rotina_que_parou_de_rodar_aparece_como_atrasada(rodar, conn):
    """Ninguém falhou: o agendador é que não disparou. Só o tempo denuncia."""
    rodar(PRODUTOS)
    rodar(LEADS)
    dois_dias_depois = datetime.now(UTC) + timedelta(hours=48)

    rotinas = saude.situacao(conn, agora=dois_dias_depois, tolerancia_horas=26)

    assert [r.problema for r in rotinas] == ["atrasada: 48h sem sucesso"] * 2


def test_falha_repetida_avisa_uma_vez_e_avisa_de_novo_quando_volta(rodar, caos, avisos):
    """Rotina a cada 15 minutos, fonte fora do ar a noite toda: um aviso, não trinta."""
    rodar(PRODUTOS)
    caos.respostas_ate_cair = 0
    for _ in range(3):
        with pytest.raises(FonteIndisponivel):
            rodar(PRODUTOS)

    assert len(avisos) == 1
    assert "reservas.produtos falhou" in avisos[0]

    caos.respostas_ate_cair = None
    rodar(PRODUTOS)

    assert len(avisos) == 2
    assert "voltou ao normal" in avisos[1]


def test_contagem_que_nao_confere_aparece_no_status(rodar, conn, mundo):
    mundo.produtos["rota-sul"][30]["price"] = -10

    rodar(PRODUTOS)

    (rotina,) = saude.situacao(conn)
    assert rotina.problema == "contagem não confere com a fonte"
    assert rotina.rejeitados == 1


def test_item_recusado_aparece_no_status_mesmo_sem_conferencia(rodar, conn, mundo):
    """Campanhas não têm contagem na fonte. O item recusado é o único sinal."""
    mundo.insights["rota-sul"][0]["spend"] = -1

    rodar(CAMPANHAS)

    (rotina,) = saude.situacao(conn)
    assert rotina.problema == "1 item(ns) recusado(s)"
