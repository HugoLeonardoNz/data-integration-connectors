"""Não duplicar e não perder, inclusive quando a execução cai no meio."""

from __future__ import annotations

import pytest

from conectores import fontes, motor
from conectores.cliente import FonteIndisponivel
from conectores.contrato import ContratoQuebrado
from conectores.fontes import PRODUTOS
from conectores.motor import JaEmExecucao

from .conftest import EMPRESA


def _retrato(conn):
    """Cada linha com a execução que a gravou. Se nada foi tocado, não muda."""
    return conn.execute(
        "select id_origem, preco, execucao_id, gravado_em from core.produto order by id_origem"
    ).fetchall()


def test_carga_inicial_traz_tudo_e_confere_com_a_fonte(rodar, contar, mundo):
    resultado = rodar(PRODUTOS)

    total = len(mundo.produtos[EMPRESA])
    assert resultado.contagem.inseridas == total == contar("core.produto")
    assert resultado.paginas == 3  # 120 produtos, 50 por página
    assert resultado.conferencia == "ok"


def test_rodar_de_novo_nao_duplica_nem_toca_no_que_ja_esta_igual(rodar, contar, conn):
    rodar(PRODUTOS)
    antes = _retrato(conn)

    segunda = rodar(PRODUTOS)

    assert segunda.contagem.inseridas == 0
    assert segunda.contagem.atualizadas == 0
    assert _retrato(conn) == antes


def test_execucao_seguinte_le_so_o_que_mudou(rodar, conn, mundo):
    rodar(PRODUTOS)
    for indice in (10, 55, 90):
        mundo.alterar_produto(EMPRESA, indice, price=999.90)

    resultado = rodar(PRODUTOS)

    assert resultado.contagem.atualizadas == 3
    assert resultado.contagem.lidas < 10  # as 3 alteradas e o que empata com o marcador
    alterados = conn.execute("select count(*) as n from core.produto where preco = 999.90")
    assert alterados.fetchone()["n"] == 3


def test_produto_desativado_na_origem_fica_inativo_e_nao_some(rodar, contar, conn, mundo):
    rodar(PRODUTOS)
    desativado = mundo.alterar_produto(EMPRESA, 20, active=False)

    rodar(PRODUTOS)

    linha = conn.execute(
        "select ativo from core.produto where id_origem = %s", [desativado["id"]]
    ).fetchone()
    assert linha["ativo"] is False
    assert contar("core.produto") == len(mundo.produtos[EMPRESA])


def test_queda_no_meio_retoma_do_ultimo_lote_confirmado(
    rodar, contar, conn, caos, mundo, marcador, avisos
):
    caos.respostas_ate_cair = 2  # entrega duas páginas e sai do ar

    with pytest.raises(FonteIndisponivel):
        rodar(PRODUTOS)

    assert contar("core.produto") == 100
    falha = conn.execute("select situacao, lidas, erro from ops.execucao").fetchone()
    assert (falha["situacao"], falha["lidas"]) == ("falhou", 100)
    assert marcador(PRODUTOS) is not None
    assert len(avisos) == 1

    caos.respostas_ate_cair = None
    retomada = rodar(PRODUTOS)

    assert contar("core.produto") == len(mundo.produtos[EMPRESA])
    assert retomada.contagem.lidas < 40  # não recomeçou do zero
    assert retomada.conferencia == "ok"


def test_queda_entre_registros_com_a_mesma_data_nao_perde_nenhum(
    rodar, contar, caos, mundo, monkeypatch
):
    """Oito produtos têm a mesma data de alteração. A primeira página termina
    no meio deles e a fonte cai. Se a retomada pedisse "depois do marcador",
    os que ficaram para a segunda página sumiriam."""
    ordenados = sorted(mundo.produtos[EMPRESA], key=lambda p: (p["updated_at"], p["id"]))
    datas = [p["updated_at"] for p in ordenados]
    empatada = max(set(datas), key=datas.count)
    assert datas.count(empatada) == 8
    monkeypatch.setattr(fontes, "TAMANHO_DA_PAGINA", datas.index(empatada) + 3)
    caos.respostas_ate_cair = 1

    with pytest.raises(FonteIndisponivel):
        rodar(PRODUTOS)
    caos.respostas_ate_cair = None
    rodar(PRODUTOS)

    assert contar("core.produto") == len(mundo.produtos[EMPRESA])


def test_fonte_que_devolve_sempre_o_mesmo_cursor_nao_prende_a_rotina():
    class FontePresa:
        def get(self, caminho, **parametros):
            item = {"id": "p1", "updated_at": "2026-10-01T00:00:00Z"}
            return {"data": [item], "next_cursor": "o-mesmo"}

    with pytest.raises(ContratoQuebrado, match="mesmo cursor"):
        list(PRODUTOS.paginas(FontePresa(), EMPRESA, None))


def test_conferencia_fora_do_ar_nao_transforma_carga_boa_em_falha(rodar, contar, conn, caos):
    caos.respostas_ate_cair = 3  # as três páginas chegam; a consulta do total, não

    resultado = rodar(PRODUTOS)

    assert resultado.conferencia is None
    assert contar("core.produto") == 120
    assert conn.execute("select situacao from ops.execucao").fetchone()["situacao"] == "ok"


def test_erro_ao_gravar_desfaz_o_lote_inteiro(rodar, contar, conn, marcador, monkeypatch):
    gravar = motor._gravar_marcador
    chamadas = []

    def falha_na_segunda(*args):
        chamadas.append(args[-1])
        if len(chamadas) == 2:
            raise RuntimeError("banco caiu no meio do lote")
        gravar(*args)

    monkeypatch.setattr(motor, "_gravar_marcador", falha_na_segunda)

    with pytest.raises(RuntimeError):
        rodar(PRODUTOS)

    # A página 2 foi desfeita inteira: nem as linhas nem o marcador dela ficaram.
    assert contar("core.produto") == 50
    assert marcador(PRODUTOS) == chamadas[0]
    # Mas a resposta bruta dela está guardada.
    assert conn.execute("select count(*) as n from raw.pagina").fetchone()["n"] == 2


def test_duas_execucoes_do_mesmo_recurso_nao_rodam_juntas(rodar, conn, banco_de_teste):
    from conectores import banco

    with banco.conectar(banco_de_teste) as outra:
        outra.execute("select pg_advisory_lock(hashtext(%s))", [f"reservas.produtos.{EMPRESA}"])

        with pytest.raises(JaEmExecucao):
            rodar(PRODUTOS)

    assert conn.execute("select count(*) as n from ops.execucao").fetchone()["n"] == 0


def test_execucao_que_morreu_sem_fechar_vira_falha(rodar, conn):
    conn.execute(
        "insert into ops.execucao (fonte, recurso, empresa) values ('reservas', 'produtos', %s)",
        [EMPRESA],
    )

    rodar(PRODUTOS)

    orfa = conn.execute("select situacao, erro from ops.execucao where id = 1").fetchone()
    assert orfa["situacao"] == "falhou"
    assert orfa["erro"].startswith("interrompida")


def test_cada_empresa_fica_com_os_proprios_dados(rodar, contar, conn, mundo):
    rodar(PRODUTOS, "rota-sul")
    rodar(PRODUTOS, "rota-serra")

    assert contar("core.produto", "rota-sul") == len(mundo.produtos["rota-sul"])
    assert contar("core.produto", "rota-serra") == len(mundo.produtos["rota-serra"])
    assert contar("core.produto", "rota-nordeste") == 0
    marcadores = conn.execute("select count(*) as n from ops.marcador").fetchone()["n"]
    assert marcadores == 2
