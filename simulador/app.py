"""A API simulada, com os comportamentos que dão trabalho numa API real:
OAuth com token que vence, dois tipos de paginação, limite de requisições e
falhas que podem ser ligadas de fora.

Subir sozinha:  uvicorn simulador.app:app --port 8090
"""

from __future__ import annotations

import base64
import secrets
from dataclasses import dataclass, field
from urllib.parse import parse_qs

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse

from .dados import Mundo

CLIENT_ID = "demo"
CLIENT_SECRET = "demo-secret"


class _PaginaDeErro(Exception):
    pass


@dataclass
class Caos:
    """Falhas sob encomenda. Os testes mexem aqui direto; com a API no ar,
    o mesmo se faz por `POST /_caos`."""

    erros_500: int = 0  # as próximas N requisições respondem 500
    limite_429: int = 0  # as próximas N respondem 429 com Retry-After
    respostas_ate_cair: int | None = None  # responde N vezes e fica fora do ar
    paginas_de_erro: int = 0  # as próximas N respondem 200 com HTML, como um proxy
    erros_no_token: int = 0  # as próximas N emissões de token respondem 503
    validade_do_token: int = 3600  # o `expires_in` informado, em segundos
    renomear: dict[str, dict[str, str]] = field(default_factory=dict)  # recurso -> {de: para}
    requisicoes: int = 0  # quantas chamadas de dados chegaram


def _codificar(tempo: str, id_: str) -> str:
    return base64.urlsafe_b64encode(f"{tempo}|{id_}".encode()).decode()


def _decodificar(cursor: str) -> tuple[str, str]:
    try:
        tempo, id_ = base64.urlsafe_b64decode(cursor.encode()).decode().split("|", 1)
    except ValueError:
        raise HTTPException(400, "cursor inválido") from None
    return tempo, id_


def criar_app(mundo: Mundo | None = None, caos: Caos | None = None) -> FastAPI:
    mundo = mundo or Mundo()
    caos = caos or Caos()
    tokens: set[str] = set()
    app = FastAPI(title="API simulada de reservas, anúncios e CRM")
    app.state.mundo, app.state.caos, app.state.tokens = mundo, caos, tokens

    @app.exception_handler(_PaginaDeErro)
    async def pagina_de_erro(request: Request, erro: _PaginaDeErro) -> HTMLResponse:
        return HTMLResponse("<html><body>Bad gateway</body></html>", status_code=200)

    def porteiro(request: Request) -> None:
        caos.requisicoes += 1
        if caos.erros_500 > 0:
            caos.erros_500 -= 1
            raise HTTPException(500, "erro interno")
        if caos.limite_429 > 0:
            caos.limite_429 -= 1
            raise HTTPException(429, "devagar", headers={"Retry-After": "2"})
        if caos.paginas_de_erro > 0:
            caos.paginas_de_erro -= 1
            raise _PaginaDeErro
        if caos.respostas_ate_cair is not None:
            if caos.respostas_ate_cair == 0:
                raise HTTPException(503, "fora do ar")
            caos.respostas_ate_cair -= 1
        esquema, _, token = request.headers.get("Authorization", "").partition(" ")
        if esquema != "Bearer" or token not in tokens:
            raise HTTPException(401, "token inválido ou vencido")

    def registros(colecao: dict[str, list[dict]], empresa: str) -> list[dict]:
        if empresa not in colecao:
            raise HTTPException(404, f"empresa desconhecida: {empresa}")
        return colecao[empresa]

    def servir(recurso: str, itens: list[dict]) -> list[dict]:
        troca = caos.renomear.get(recurso, {})
        return [
            {troca.get(k, k): v for k, v in item.items() if not k.startswith("_")}
            for item in itens
        ]

    def por_cursor(recurso, itens, campo, updated_since, cursor, limit) -> dict:
        """Paginação por posição (data de alteração + id), estável mesmo se
        entrarem registros novos entre uma página e outra."""
        ordenados = sorted(itens, key=lambda r: (r[campo], r["id"]))
        if updated_since:
            ordenados = [r for r in ordenados if r[campo] >= updated_since]
        if cursor:
            posicao = _decodificar(cursor)
            ordenados = [r for r in ordenados if (r[campo], r["id"]) > posicao]
        pagina = ordenados[:limit]
        proximo = None
        if len(ordenados) > limit:
            proximo = _codificar(pagina[-1][campo], pagina[-1]["id"])
        return {"data": servir(recurso, pagina), "next_cursor": proximo}

    @app.post("/oauth/token")
    async def token(request: Request) -> dict:
        if caos.erros_no_token > 0:
            caos.erros_no_token -= 1
            raise HTTPException(503, "serviço de autenticação fora do ar")
        corpo = parse_qs((await request.body()).decode())
        credencial = (corpo.get("client_id", [""])[0], corpo.get("client_secret", [""])[0])
        if credencial != (CLIENT_ID, CLIENT_SECRET):
            raise HTTPException(401, "credencial recusada")
        novo = secrets.token_urlsafe(24)
        tokens.add(novo)
        return {
            "access_token": novo,
            "token_type": "bearer",
            "expires_in": caos.validade_do_token,
        }

    @app.get("/reservas/v1/produtos", dependencies=[Depends(porteiro)])
    def produtos(empresa: str, updated_since: str | None = None, cursor: str | None = None,
                 limit: int = 100) -> dict:
        itens = registros(mundo.produtos, empresa)
        return por_cursor("produtos", itens, "updated_at", updated_since, cursor, limit)

    @app.get("/reservas/v1/produtos/total", dependencies=[Depends(porteiro)])
    def total_de_produtos(empresa: str) -> dict:
        return {"total": len(registros(mundo.produtos, empresa))}

    @app.get("/ads/v1/insights", dependencies=[Depends(porteiro)])
    def insights(empresa: str, since: str | None = None, page: int = 1,
                 page_size: int = 100) -> dict:
        """Paginação por número de página, como nos relatórios de anúncios."""
        itens = sorted(
            (i for i in registros(mundo.insights, empresa) if not since or i["date"] >= since),
            key=lambda i: (i["date"], i["platform"], i["campaign_id"]),
        )
        inicio = (page - 1) * page_size
        return {
            "data": servir("insights", itens[inicio : inicio + page_size]),
            "page": page,
            "total_pages": max(1, -(-len(itens) // page_size)),
        }

    @app.get("/ads/v1/cliques", dependencies=[Depends(porteiro)])
    def cliques(empresa: str, updated_since: str | None = None, cursor: str | None = None,
                limit: int = 100) -> dict:
        itens = registros(mundo.cliques, empresa)
        return por_cursor("cliques", itens, "clicked_at", updated_since, cursor, limit)

    @app.get("/ads/v1/cliques/total", dependencies=[Depends(porteiro)])
    def total_de_cliques(empresa: str) -> dict:
        return {"total": len(registros(mundo.cliques, empresa))}

    @app.get("/crm/v1/leads", dependencies=[Depends(porteiro)])
    def leads(empresa: str, updated_since: str | None = None, cursor: str | None = None,
              limit: int = 100) -> dict:
        itens = registros(mundo.leads, empresa)
        return por_cursor("leads", itens, "updated_at", updated_since, cursor, limit)

    @app.get("/crm/v1/leads/total", dependencies=[Depends(porteiro)])
    def total_de_leads(empresa: str) -> dict:
        return {"total": len(registros(mundo.leads, empresa))}

    @app.get("/crm/v1/vendas", dependencies=[Depends(porteiro)])
    def vendas(empresa: str, updated_since: str | None = None, cursor: str | None = None,
               limit: int = 100) -> dict:
        itens = registros(mundo.vendas, empresa)
        return por_cursor("vendas", itens, "updated_at", updated_since, cursor, limit)

    @app.get("/crm/v1/vendas/total", dependencies=[Depends(porteiro)])
    def total_de_vendas(empresa: str) -> dict:
        return {"total": len(registros(mundo.vendas, empresa))}

    @app.post("/_caos")
    async def ligar_caos(request: Request) -> dict:
        """Liga falhas com a API no ar. Ex.: {"erros_500": 3} ou
        {"renomear": {"produtos": {"price": "price_amount"}}}. {"vencer_tokens": true}
        invalida os tokens emitidos; {"alterar_produtos": 30} reajusta o preço de
        30 produtos de cada empresa, como faria a operação na origem."""
        pedido = await request.json()
        if pedido.pop("vencer_tokens", False):
            tokens.clear()
        for indice in range(pedido.pop("alterar_produtos", 0)):
            for empresa in mundo.produtos:
                preco = mundo.produtos[empresa][indice]["price"]
                mundo.alterar_produto(empresa, indice, price=round(preco * 1.05, 2))
        for chave, valor in pedido.items():
            if chave not in (
                "erros_500", "limite_429", "respostas_ate_cair", "renomear",
                "paginas_de_erro", "erros_no_token", "validade_do_token",
            ):
                raise HTTPException(400, f"opção desconhecida: {chave}")
            setattr(caos, chave, valor)
        return {"caos": caos.__dict__}

    return app


app = criar_app()
