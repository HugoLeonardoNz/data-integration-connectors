"""Motor de sincronização: o mesmo caminho para todo conector.

Para cada página que a fonte devolve:

1. a resposta bruta é gravada e confirmada sozinha;
2. numa única transação, os itens válidos são gravados por chave (upsert), os
   inválidos vão para `ops.rejeitado` e o marcador avança.

Se o processo cair entre uma página e outra, o banco fica exatamente no fim da
última página confirmada, e a próxima execução retoma dali. Se cair no meio de
uma página, a transação desfaz tudo e o marcador não se move. Reler um trecho
não duplica nada, porque a gravação é por chave.

Cada linha guarda quando foi lida na fonte (`lido_em`). Uma leitura mais
antiga nunca passa por cima de uma mais nova, o que torna seguro reaplicar a
resposta bruta de uma execução velha.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import datetime

import psycopg
from psycopg import Connection, sql
from psycopg.types.json import Jsonb

from . import alerta
from .cliente import ClienteApi, ErroDeApi, FonteIndisponivel
from .contrato import ContratoQuebrado, ItemInvalido

log = logging.getLogger("conectores.motor")

# Com menos itens que isso sem o mesmo campo, não dá para dizer que o formato
# mudou: são recusados um a um. Sem esse piso, um único item ruim numa página
# pequena travaria a rotina para sempre.
MINIMO_PARA_QUEBRA = 5


class JaEmExecucao(Exception):
    """Outra execução do mesmo recurso e empresa ainda está rodando."""


@dataclass(frozen=True)
class Pagina:
    """Um lote da fonte. `marcador` é até onde a leitura pode ser dada como
    confirmada depois que este lote estiver gravado. `recebida_em` só vem
    preenchida no reprocesso: é quando a página foi lida da fonte."""

    itens: list[dict]
    marcador: str | None = None
    recebida_em: datetime | None = None


@dataclass(frozen=True)
class Recurso:
    """O que um conector precisa declarar. O resto é do motor."""

    fonte: str
    nome: str
    tabela: str
    chave: tuple[str, ...]
    paginas: Callable[[ClienteApi, str, str | None], Iterator[Pagina]]
    converter: Callable[[dict, str], dict]
    id_do_item: Callable[[dict], str] = lambda item: str(item.get("id"))
    total_na_fonte: Callable[[ClienteApi, str], int] | None = None

    @property
    def rotulo(self) -> str:
        return f"{self.fonte}.{self.nome}"


@dataclass(frozen=True)
class Contagem:
    lidas: int = 0
    inseridas: int = 0
    atualizadas: int = 0
    rejeitadas: int = 0

    def __add__(self, outra: Contagem) -> Contagem:
        return Contagem(
            self.lidas + outra.lidas,
            self.inseridas + outra.inseridas,
            self.atualizadas + outra.atualizadas,
            self.rejeitadas + outra.rejeitadas,
        )


@dataclass(frozen=True)
class Resultado:
    execucao: int
    paginas: int
    contagem: Contagem
    conferencia: str | None


Avisar = Callable[[str, str], None]


def sincronizar(
    conn: Connection,
    cliente: ClienteApi,
    recurso: Recurso,
    empresa: str,
    *,
    avisar: Avisar = alerta.avisar,
) -> Resultado:
    """Lê a fonte a partir do marcador e grava o que mudou."""
    with _trava(conn, recurso, empresa):
        marcador = ler_marcador(conn, recurso, empresa)
        execucao = _abrir(conn, recurso, empresa, marcador)
        paginas = recurso.paginas(cliente, empresa, marcador)
        return _executar(conn, recurso, empresa, execucao, paginas, cliente, avisar)


def reprocessar(
    conn: Connection,
    recurso: Recurso,
    execucao_origem: int,
    *,
    avisar: Avisar = alerta.avisar,
) -> Resultado:
    """Aplica de novo as páginas brutas de uma execução, sem chamar a fonte.

    É o caminho depois de corrigir um conector: o que chegou enquanto ele
    estava quebrado já está guardado.
    """
    guardadas = conn.execute(
        "select empresa, marcador, corpo, recebida_em from raw.pagina "
        "where execucao_id = %s and fonte = %s and recurso = %s order by numero",
        [execucao_origem, recurso.fonte, recurso.nome],
    ).fetchall()
    if not guardadas:
        raise LookupError(f"execução {execucao_origem} não tem página de {recurso.rotulo}")
    empresa = guardadas[0]["empresa"]

    with _trava(conn, recurso, empresa):
        execucao = _abrir(
            conn, recurso, empresa, ler_marcador(conn, recurso, empresa), execucao_origem
        )
        # Os recusados daquela execução serão julgados de novo, pelo conector atual.
        conn.execute("delete from ops.rejeitado where execucao_id = %s", [execucao_origem])
        paginas = (Pagina(p["corpo"], p["marcador"], p["recebida_em"]) for p in guardadas)
        return _executar(conn, recurso, empresa, execucao, paginas, None, avisar)


def ler_marcador(conn: Connection, recurso: Recurso, empresa: str) -> str | None:
    linha = conn.execute(
        "select valor from ops.marcador where fonte = %s and recurso = %s and empresa = %s",
        [recurso.fonte, recurso.nome, empresa],
    ).fetchone()
    return linha["valor"] if linha else None


def _executar(
    conn: Connection,
    recurso: Recurso,
    empresa: str,
    execucao: int,
    paginas: Iterable[Pagina],
    cliente: ClienteApi | None,
    avisar: Avisar,
) -> Resultado:
    total = Contagem()
    numero = 0
    try:
        for numero, pagina in enumerate(paginas, start=1):
            lida_em = pagina.recebida_em
            if cliente is not None:
                lida_em = _guardar_bruto(conn, recurso, empresa, execucao, numero, pagina)
            with conn.transaction():
                parcial = total + _aplicar(conn, recurso, empresa, execucao, pagina.itens, lida_em)
                if pagina.marcador:
                    _gravar_marcador(conn, recurso, empresa, pagina.marcador)
                _registrar_progresso(conn, execucao, numero, parcial)
            total = parcial
        conferencia = None
        if cliente is not None and recurso.total_na_fonte is not None:
            try:
                conferencia = _conferir(conn, cliente, recurso, empresa, execucao, avisar)
            except (FonteIndisponivel, ErroDeApi) as erro:
                # Os dados já entraram. Marcar a execução como falha por causa
                # da conferência diria que a carga falhou, e ela não falhou.
                log.warning(
                    "%s %s: sem conferência nesta execução: %s", recurso.rotulo, empresa, erro
                )
    except Exception as erro:
        tipo = type(erro).__name__
        try:
            repetida = _erro_anterior(conn, recurso, empresa, execucao) == tipo
            _fechar(conn, recurso, empresa, execucao, "falhou", f"{tipo}: {erro}")
        except psycopg.Error:
            # Sem banco não há onde registrar. A execução fica "rodando" e a
            # próxima a marca como interrompida. O erro que sobe é o original.
            log.exception("não foi possível registrar a falha da execução %s", execucao)
            repetida = False
        # Avisa quando a rotina quebra, não a cada execução enquanto está quebrada.
        if repetida:
            log.warning("%s %s continua falhando: %s", recurso.rotulo, empresa, erro)
        else:
            avisar(f"{recurso.rotulo} falhou para {empresa}", f"execução {execucao}: {erro}")
        raise
    voltou = _erro_anterior(conn, recurso, empresa, execucao) is not None
    _fechar(conn, recurso, empresa, execucao, "ok")
    if voltou:
        avisar(f"{recurso.rotulo} voltou ao normal para {empresa}", f"execução {execucao}")
    log.debug("%s %s: %s", recurso.rotulo, empresa, total)
    return Resultado(execucao, numero, total, conferencia)


def _anterior(conn: Connection, recurso: Recurso, empresa: str, execucao: int) -> dict | None:
    return conn.execute(
        "select situacao, erro, conferencia from ops.execucao "
        "where fonte = %s and recurso = %s and empresa = %s and id < %s "
        "order by id desc limit 1",
        [recurso.fonte, recurso.nome, empresa, execucao],
    ).fetchone()


def _erro_anterior(conn: Connection, recurso: Recurso, empresa: str, execucao: int) -> str | None:
    """O tipo do erro da execução anterior, se ela falhou."""
    anterior = _anterior(conn, recurso, empresa, execucao)
    if not anterior or anterior["situacao"] != "falhou":
        return None
    return (anterior["erro"] or "").split(":", 1)[0]


@contextmanager
def _trava(conn: Connection, recurso: Recurso, empresa: str):
    """Trava do PostgreSQL por (recurso, empresa). Solta sozinha se a conexão cair,
    então um processo morto não deixa a rotina presa."""
    nome = f"{recurso.rotulo}.{empresa}"
    obteve = conn.execute("select pg_try_advisory_lock(hashtext(%s)) as ok", [nome]).fetchone()
    if not obteve["ok"]:
        raise JaEmExecucao(nome)
    try:
        yield
    finally:
        # Se a conexão caiu, a trava já foi solta pelo PostgreSQL.
        with suppress(psycopg.Error):
            conn.execute("select pg_advisory_unlock(hashtext(%s))", [nome])


def _abrir(
    conn: Connection,
    recurso: Recurso,
    empresa: str,
    marcador: str | None,
    reprocesso_de: int | None = None,
) -> int:
    # Com a trava na mão, uma execução ainda "rodando" só pode ser de um
    # processo que morreu sem fechar. Fica registrada como falha.
    conn.execute(
        "update ops.execucao set situacao = 'falhou', terminada_em = now(), "
        "erro = 'interrompida: o processo terminou sem fechar a execução' "
        "where fonte = %s and recurso = %s and empresa = %s and situacao = 'rodando'",
        [recurso.fonte, recurso.nome, empresa],
    )
    linha = conn.execute(
        "insert into ops.execucao (fonte, recurso, empresa, marcador_inicial, reprocesso_de) "
        "values (%s, %s, %s, %s, %s) returning id",
        [recurso.fonte, recurso.nome, empresa, marcador, reprocesso_de],
    ).fetchone()
    return linha["id"]


def _guardar_bruto(
    conn: Connection, recurso: Recurso, empresa: str, execucao: int, numero: int, pagina: Pagina
) -> datetime:
    linha = conn.execute(
        "insert into raw.pagina (execucao_id, fonte, recurso, empresa, numero, marcador, corpo) "
        "values (%s, %s, %s, %s, %s, %s, %s) returning recebida_em",
        [execucao, recurso.fonte, recurso.nome, empresa, numero, pagina.marcador,
         Jsonb(pagina.itens)],
    ).fetchone()
    return linha["recebida_em"]


def _aplicar(
    conn: Connection,
    recurso: Recurso,
    empresa: str,
    execucao: int,
    itens: list[dict],
    lida_em: datetime,
) -> Contagem:
    linhas, aceitos, recusados = [], [], []
    ausentes: Counter[str] = Counter()
    for item in itens:
        try:
            linhas.append(recurso.converter(item, empresa))
            aceitos.append(recurso.id_do_item(item))
        except ItemInvalido as erro:
            recusados.append((item, str(erro)))
            if erro.campo_ausente:
                ausentes[erro.campo_ausente] += 1

    # Um item sem preço é um item ruim. Mais da metade da página sem o mesmo
    # campo é a fonte que mudou o formato: gravar o resto seria publicar um
    # dado pela metade. Para tudo, e o bruto já está guardado.
    if ausentes:
        campo, quantos = ausentes.most_common(1)[0]
        if quantos >= MINIMO_PARA_QUEBRA and quantos * 2 > len(itens):
            raise ContratoQuebrado(
                f"campo '{campo}' ausente em {quantos} de {len(itens)} itens de {recurso.rotulo}"
            )

    inseridas = atualizadas = 0
    if linhas:
        with conn.cursor() as cur:
            parametros = [
                {**linha, "execucao_id": execucao, "lido_em": lida_em} for linha in linhas
            ]
            cur.executemany(_sql_de_gravacao(recurso, list(linhas[0])), parametros, returning=True)
            while True:
                gravada = cur.fetchone()
                if gravada is not None:
                    inseridas += gravada["inserida"]
                    atualizadas += not gravada["inserida"]
                if not cur.nextset():
                    break

    # Sai da fila o que a fonte mandou de novo: o que agora é válido foi
    # gravado acima, e o que continua ruim é registrado abaixo, uma vez só.
    conn.execute(
        "delete from ops.rejeitado "
        "where fonte = %s and recurso = %s and empresa = %s and chave = any(%s)",
        [recurso.fonte, recurso.nome, empresa,
         aceitos + [recurso.id_do_item(item) for item, _ in recusados]],
    )
    for item, motivo in recusados:
        conn.execute(
            "insert into ops.rejeitado (execucao_id, fonte, recurso, empresa, chave, motivo, item) "
            "values (%s, %s, %s, %s, %s, %s, %s)",
            [execucao, recurso.fonte, recurso.nome, empresa, recurso.id_do_item(item), motivo,
             Jsonb(item)],
        )
    return Contagem(len(itens), inseridas, atualizadas, len(recusados))


def _sql_de_gravacao(recurso: Recurso, colunas: list[str]) -> sql.Composed:
    """Grava por chave. Linha igual à que já existe não é tocada, e por isso
    não é devolvida: `atualizadas` conta só o que mudou de verdade. Linha lida
    antes da que está no banco também não entra."""
    esquema, nome = recurso.tabela.split(".")
    dados = [c for c in colunas if c not in recurso.chave]
    return sql.SQL(
        "insert into {tabela} as atual ({colunas}, execucao_id, lido_em) "
        "values ({valores}, %(execucao_id)s, %(lido_em)s) "
        "on conflict ({chave}) do update set {atribuicoes}, "
        "execucao_id = excluded.execucao_id, lido_em = excluded.lido_em, gravado_em = now() "
        "where excluded.lido_em >= atual.lido_em "
        "and ({antes}) is distinct from ({depois}) "
        "returning (xmax = 0) as inserida"
    ).format(
        tabela=sql.Identifier(esquema, nome),
        colunas=sql.SQL(", ").join(map(sql.Identifier, colunas)),
        valores=sql.SQL(", ").join(map(sql.Placeholder, colunas)),
        chave=sql.SQL(", ").join(map(sql.Identifier, recurso.chave)),
        atribuicoes=sql.SQL(", ").join(
            sql.SQL("{c} = excluded.{c}").format(c=sql.Identifier(c)) for c in dados
        ),
        antes=sql.SQL(", ").join(sql.Identifier("atual", c) for c in dados),
        depois=sql.SQL(", ").join(sql.Identifier("excluded", c) for c in dados),
    )


def _gravar_marcador(conn: Connection, recurso: Recurso, empresa: str, valor: str) -> None:
    # `greatest` impede o marcador de andar para trás num reprocesso. Vale
    # porque todo marcador é data ou data e hora em ISO, que ordena como texto.
    conn.execute(
        "insert into ops.marcador (fonte, recurso, empresa, valor) values (%s, %s, %s, %s) "
        "on conflict (fonte, recurso, empresa) do update "
        "set valor = greatest(ops.marcador.valor, excluded.valor), atualizado_em = now()",
        [recurso.fonte, recurso.nome, empresa, valor],
    )


def _registrar_progresso(conn: Connection, execucao: int, paginas: int, c: Contagem) -> None:
    conn.execute(
        "update ops.execucao set paginas = %s, lidas = %s, inseridas = %s, "
        "atualizadas = %s, rejeitadas = %s where id = %s",
        [paginas, c.lidas, c.inseridas, c.atualizadas, c.rejeitadas, execucao],
    )


def _conferir(
    conn: Connection,
    cliente: ClienteApi,
    recurso: Recurso,
    empresa: str,
    execucao: int,
    avisar: Avisar,
) -> str:
    """Compara a contagem da fonte com a do banco ao fim da execução."""
    na_fonte = recurso.total_na_fonte(cliente, empresa)
    esquema, nome = recurso.tabela.split(".")
    no_banco = conn.execute(
        sql.SQL("select count(*) as n from {} where empresa = %s").format(
            sql.Identifier(esquema, nome)
        ),
        [empresa],
    ).fetchone()["n"]
    conferencia = "ok" if na_fonte == no_banco else "divergente"
    conn.execute(
        "update ops.execucao set total_na_fonte = %s, total_no_banco = %s, conferencia = %s "
        "where id = %s",
        [na_fonte, no_banco, conferencia, execucao],
    )
    anterior = _anterior(conn, recurso, empresa, execucao)
    if conferencia == "divergente" and (not anterior or anterior["conferencia"] != "divergente"):
        avisar(
            f"{recurso.rotulo} não confere para {empresa}",
            f"execução {execucao}: {na_fonte} na fonte, {no_banco} no banco",
        )
    return conferencia


def _fechar(
    conn: Connection,
    recurso: Recurso,
    empresa: str,
    execucao: int,
    situacao: str,
    erro: str | None = None,
) -> None:
    conn.execute(
        "update ops.execucao set situacao = %s, erro = %s, terminada_em = now(), "
        "marcador_final = %s where id = %s",
        [situacao, erro, ler_marcador(conn, recurso, empresa), execucao],
    )
