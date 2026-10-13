"""Os conectores. Cada um diz de onde ler, como paginar e como converter um item.

Há dois jeitos de ler, porque as fontes são de dois tipos:

- `por_alteracao`: a fonte tem data de alteração e filtro por ela (reservas,
  CRM, cliques). Lê só o que mudou desde o marcador.
- `por_janela`: a fonte entrega números por dia e os corrige depois (anúncios
  costumam rever os últimos dias). Relê uma janela a cada execução. O tamanho
  da janela é de cada fonte: depende de por quanto tempo ela ainda revê um dia.

Para acrescentar uma fonte, escreva a função de conversão e registre um
`Recurso` em `RECURSOS`. O motor não muda.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import date, timedelta

from . import contrato as c
from .cliente import ClienteApi
from .contrato import ContratoQuebrado
from .motor import Pagina, Recurso

TAMANHO_DA_PAGINA = 200


def _itens(corpo: dict, caminho: str) -> list[dict]:
    itens = corpo.get("data") if isinstance(corpo, dict) else None
    if not isinstance(itens, list):
        raise ContratoQuebrado(f"{caminho} respondeu sem a lista 'data'")
    return itens


def por_alteracao(
    caminho: str, campo: str = "updated_at"
) -> Callable[[ClienteApi, str, str | None], Iterator[Pagina]]:
    def paginas(cliente: ClienteApi, empresa: str, marcador: str | None) -> Iterator[Pagina]:
        cursor = None
        while True:
            # O filtro é "a partir de", com o marcador incluído: dois registros
            # podem ter a mesma data de alteração e só um ter sido lido antes
            # da queda. Reler o que empata não custa nada, a gravação é por chave.
            corpo = cliente.get(
                caminho,
                empresa=empresa,
                updated_since=marcador,
                cursor=cursor,
                limit=TAMANHO_DA_PAGINA,
            )
            itens = _itens(corpo, caminho)
            if itens:
                # A fonte ordena por data de alteração, então o maior valor da
                # página é até onde a leitura chegou.
                lidos = [str(i[campo]) for i in itens if i.get(campo)]
                yield Pagina(itens, max(lidos) if lidos else None)
            proximo = corpo.get("next_cursor")
            if not proximo:
                return
            if proximo == cursor:
                # Sem isto, uma fonte com defeito na paginação prenderia a
                # rotina num laço, relendo a mesma página para sempre.
                raise ContratoQuebrado(f"{caminho} devolveu o mesmo cursor duas vezes")
            cursor = proximo

    return paginas


def por_janela(
    caminho: str, dias_de_revisao: int, campo: str = "date"
) -> Callable[[ClienteApi, str, str | None], Iterator[Pagina]]:
    def paginas(cliente: ClienteApi, empresa: str, marcador: str | None) -> Iterator[Pagina]:
        desde = None
        if marcador:
            desde = (date.fromisoformat(marcador) - timedelta(days=dias_de_revisao)).isoformat()
        numero = 1
        while True:
            corpo = cliente.get(
                caminho, empresa=empresa, since=desde, page=numero, page_size=TAMANHO_DA_PAGINA
            )
            itens = _itens(corpo, caminho)
            if itens:
                # Como em `por_alteracao`, conta com a fonte devolvendo os dias
                # em ordem: o marcador de uma página não pode passar à frente
                # de um dia que ainda está numa página seguinte.
                lidos = [str(i[campo]) for i in itens if i.get(campo)]
                yield Pagina(itens, max(lidos) if lidos else None)
            if numero >= int(corpo.get("total_pages", 1)):
                return
            numero += 1

    return paginas


def _total(caminho: str) -> Callable[[ClienteApi, str], int]:
    return lambda cliente, empresa: int(cliente.get(caminho, empresa=empresa)["total"])


def _produto(item: dict, empresa: str) -> dict:
    return {
        "empresa": empresa,
        "id_origem": c.texto(item, "id"),
        "nome": c.texto(item, "name"),
        "categoria": c.texto(item, "category", obrigatorio=False),
        "preco": c.dinheiro(item, "price"),
        "moeda": c.texto(item, "currency"),
        "vagas": c.inteiro(item, "availability"),
        "ativo": c.booleano(item, "active"),
        "atualizado_na_origem": c.instante(item, "updated_at"),
    }


def _campanha_dia(item: dict, empresa: str) -> dict:
    return {
        "empresa": empresa,
        "plataforma": c.texto(item, "platform"),
        "id_campanha": c.texto(item, "campaign_id"),
        "dia": c.dia(item, "date"),
        "nome_campanha": c.texto(item, "campaign_name"),
        "investimento": c.dinheiro(item, "spend"),
        "impressoes": c.inteiro(item, "impressions"),
        "cliques": c.inteiro(item, "clicks"),
    }


def _clique(item: dict, empresa: str) -> dict:
    return {
        "empresa": empresa,
        "id_origem": c.texto(item, "id"),
        "plataforma": c.texto(item, "platform"),
        "id_campanha": c.texto(item, "campaign_id"),
        "clicado_em": c.instante(item, "clicked_at"),
    }


def _lead(item: dict, empresa: str) -> dict:
    return {
        "empresa": empresa,
        "id_origem": c.texto(item, "id"),
        "loja": c.texto(item, "store"),
        "criado_em": c.instante(item, "created_at"),
        "id_clique": c.texto(item, "click_id", obrigatorio=False),
        "utm_source": c.texto(item, "utm_source", obrigatorio=False),
        "utm_campaign": c.texto(item, "utm_campaign", obrigatorio=False),
        "plataforma_formulario": c.texto(item, "form_platform", obrigatorio=False),
        "id_campanha_formulario": c.texto(item, "form_campaign_id", obrigatorio=False),
        "atualizado_na_origem": c.instante(item, "updated_at"),
    }


def _venda(item: dict, empresa: str) -> dict:
    return {
        "empresa": empresa,
        "id_origem": c.texto(item, "id"),
        "id_lead": c.texto(item, "lead_id", obrigatorio=False),
        "loja": c.texto(item, "store"),
        "valor": c.dinheiro(item, "amount"),
        "situacao": c.um_de(
            item, "status", {"open": "aberta", "won": "ganha", "lost": "perdida"}
        ),
        "fechada_em": c.instante(item, "closed_at", obrigatorio=False),
        "atualizado_na_origem": c.instante(item, "updated_at"),
    }


DIAS_DE_REVISAO_DE_ANUNCIOS = 7

PRODUTOS = Recurso(
    fonte="reservas",
    nome="produtos",
    tabela="core.produto",
    chave=("empresa", "id_origem"),
    paginas=por_alteracao("/reservas/v1/produtos"),
    converter=_produto,
    total_na_fonte=_total("/reservas/v1/produtos/total"),
)

CAMPANHAS = Recurso(
    fonte="anuncios",
    nome="campanhas",
    tabela="core.campanha_dia",
    chave=("empresa", "plataforma", "id_campanha", "dia"),
    paginas=por_janela("/ads/v1/insights", dias_de_revisao=DIAS_DE_REVISAO_DE_ANUNCIOS),
    converter=_campanha_dia,
    id_do_item=lambda i: f"{i.get('platform')}|{i.get('campaign_id')}|{i.get('date')}",
)

CLIQUES = Recurso(
    fonte="anuncios",
    nome="cliques",
    tabela="core.clique",
    chave=("empresa", "id_origem"),
    paginas=por_alteracao("/ads/v1/cliques", campo="clicked_at"),
    converter=_clique,
    total_na_fonte=_total("/ads/v1/cliques/total"),
)

LEADS = Recurso(
    fonte="crm",
    nome="leads",
    tabela="core.lead",
    chave=("empresa", "id_origem"),
    paginas=por_alteracao("/crm/v1/leads"),
    converter=_lead,
    total_na_fonte=_total("/crm/v1/leads/total"),
)

VENDAS = Recurso(
    fonte="crm",
    nome="vendas",
    tabela="core.venda",
    chave=("empresa", "id_origem"),
    paginas=por_alteracao("/crm/v1/vendas"),
    converter=_venda,
    total_na_fonte=_total("/crm/v1/vendas/total"),
)

RECURSOS: dict[str, Recurso] = {
    r.rotulo: r for r in (CAMPANHAS, CLIQUES, LEADS, VENDAS, PRODUTOS)
}
