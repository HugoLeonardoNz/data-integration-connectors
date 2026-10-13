"""A tabela de resultado por campanha que o README mostra é a que o projeto produz.

Recalcula os números direto dos dados do simulador, por um caminho que não
passa pelo banco nem pelas visões, e compara com o que está escrito.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from simulador.dados import Mundo

README = Path(__file__).resolve().parent.parent / "README.md"
EMPRESA = "rota-sul"


def _plataforma_do_lead(mundo: Mundo) -> dict[str, str]:
    do_clique = {c["id"]: c["platform"] for c in mundo.cliques[EMPRESA]}
    plataformas = {}
    for lead in mundo.leads[EMPRESA]:
        plataformas[lead["id"]] = (
            do_clique.get(lead["click_id"])
            or lead["form_platform"]
            or lead["utm_source"]
            or "nao_identificada"
        )
    return plataformas


def test_tabela_do_readme_bate_com_os_dados_do_simulador():
    mundo = Mundo()  # o mesmo que `docker compose up` serve
    do_lead = _plataforma_do_lead(mundo)
    investimento, receita = defaultdict(Decimal), defaultdict(Decimal)
    leads, vendas = defaultdict(int), defaultdict(int)

    for insight in mundo.insights[EMPRESA]:
        investimento[insight["platform"]] += Decimal(str(insight["spend"]))
    for plataforma in do_lead.values():
        leads[plataforma] += 1
    for venda in mundo.vendas[EMPRESA]:
        if venda["status"] == "won":
            plataforma = do_lead.get(venda["lead_id"], "nao_identificada")
            vendas[plataforma] += 1
            receita[plataforma] += Decimal(str(venda["amount"]))

    texto = README.read_text(encoding="utf-8")
    for plataforma in sorted(leads):
        gasto = investimento[plataforma]
        linha = (
            f"| {plataforma} | {gasto if gasto else 0} | {leads[plataforma]} "
            f"| {vendas[plataforma]} | {receita[plataforma]} |"
        )
        assert linha in texto, linha
