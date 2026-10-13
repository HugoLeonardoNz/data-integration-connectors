"""Os dados que o simulador serve. Gerados com semente fixa: toda execução
produz o mesmo grupo, as mesmas campanhas e os mesmos leads.

Os nomes dos campos estão em inglês de propósito, como numa API real. A
tradução para o modelo do banco é trabalho do conector.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

EMPRESAS = ("rota-sul", "rota-nordeste", "rota-serra")
PLATAFORMAS = ("google", "meta", "tiktok")
LOJAS = ("loja-centro", "loja-aeroporto", "loja-online")
CATEGORIAS = ("passeio", "hospedagem", "traslado", "pacote")

# Como o lead chegou. Um quarto chega sem origem nenhuma.
ORIGENS = (("clique", 45), ("formulario", 15), ("utm", 15), ("nenhuma", 25))


@dataclass(frozen=True)
class Tamanho:
    produtos: int = 400
    campanhas_por_plataforma: int = 4
    dias: int = 60
    cliques: int = 2000
    leads: int = 800


def _iso(instante: datetime) -> str:
    return instante.strftime("%Y-%m-%dT%H:%M:%SZ")


class Mundo:
    def __init__(
        self,
        semente: int = 7,
        tamanho: Tamanho | None = None,
        hoje: date = date(2026, 10, 1),
    ) -> None:
        self.tamanho = tamanho or Tamanho()
        self.hoje = hoje
        self._sorteio = random.Random(semente)
        # Relógio das alterações feitas depois da carga: anda 1s por mudança.
        self._relogio = datetime(hoje.year, hoje.month, hoje.day, tzinfo=UTC)
        self.produtos: dict[str, list[dict]] = {}
        self.insights: dict[str, list[dict]] = {}
        self.cliques: dict[str, list[dict]] = {}
        self.leads: dict[str, list[dict]] = {}
        self.vendas: dict[str, list[dict]] = {}
        for empresa in EMPRESAS:
            self._gerar(empresa)

    def _passado(self) -> datetime:
        segundos = self._sorteio.randrange(self.tamanho.dias * 86400)
        return self._relogio - timedelta(seconds=segundos + 1)

    def _gerar(self, empresa: str) -> None:
        s, t = self._sorteio, self.tamanho
        sigla = empresa.split("-")[1][:3]

        self.produtos[empresa] = [
            {
                "id": f"{sigla}-p{n:04d}",
                "name": f"{s.choice(CATEGORIAS).title()} {sigla.upper()} {n}",
                "category": s.choice(CATEGORIAS),
                "price": round(s.uniform(60, 4800), 2),
                "currency": "BRL",
                "availability": s.randrange(0, 40),
                "active": s.random() > 0.08,
                "updated_at": _iso(self._passado()),
            }
            for n in range(1, t.produtos + 1)
        ]
        # Vários produtos alterados no mesmo segundo, como numa carga em massa
        # na origem. É o caso que quebra o "maior que o marcador".
        for produto in self.produtos[empresa][: min(8, t.produtos)]:
            produto["updated_at"] = _iso(self._relogio - timedelta(days=3))

        campanhas = [
            (plataforma, f"{plataforma[:2]}-{sigla}-{n}", f"{sigla}-{plataforma}-campanha-{n}")
            for plataforma in PLATAFORMAS
            for n in range(1, t.campanhas_por_plataforma + 1)
        ]
        self.insights[empresa] = []
        for atras in range(t.dias - 1, -1, -1):
            self._gerar_dia(empresa, campanhas, self.hoje - timedelta(days=atras))

        self.cliques[empresa] = []
        for n in range(1, t.cliques + 1):
            plataforma, id_campanha, _ = s.choice(campanhas)
            self.cliques[empresa].append(
                {
                    "id": f"{sigla}-clk-{n:06d}",
                    "platform": plataforma,
                    "campaign_id": id_campanha,
                    "clicked_at": _iso(self._passado()),
                }
            )

        self.leads[empresa], self.vendas[empresa] = [], []
        tipos, pesos = zip(*ORIGENS, strict=True)
        for n in range(1, t.leads + 1):
            criado = self._passado()
            lead = {
                "id": f"{sigla}-lead-{n:05d}",
                "store": s.choice(LOJAS),
                "created_at": _iso(criado),
                "updated_at": _iso(criado),
                "click_id": None,
                "utm_source": None,
                "utm_campaign": None,
                "form_platform": None,
                "form_campaign_id": None,
                "_origem": s.choices(tipos, pesos)[0],
            }
            plataforma, id_campanha, nome = s.choice(campanhas)
            if lead["_origem"] == "clique":
                lead["click_id"] = s.choice(self.cliques[empresa])["id"]
            elif lead["_origem"] == "formulario":
                lead["form_platform"], lead["form_campaign_id"] = plataforma, id_campanha
            elif lead["_origem"] == "utm":
                lead["utm_source"], lead["utm_campaign"] = plataforma, nome
            self.leads[empresa].append(lead)

            if s.random() < 0.3:
                self._gerar_venda(empresa, sigla, lead["id"], lead["store"], criado)

        # Venda de balcão: existe no CRM sem lead nenhum por trás.
        for _ in range(max(4, t.leads // 10)):
            self._gerar_venda(empresa, sigla, None, s.choice(LOJAS), self._passado())

    def _gerar_dia(self, empresa: str, campanhas: list[tuple], dia: date) -> None:
        s = self._sorteio
        for plataforma, id_campanha, nome in campanhas:
            cliques = s.randrange(20, 400)
            self.insights[empresa].append(
                {
                    "date": dia.isoformat(),
                    "platform": plataforma,
                    "campaign_id": id_campanha,
                    "campaign_name": nome,
                    "spend": round(cliques * s.uniform(0.4, 2.5), 2),
                    "impressions": cliques * s.randrange(15, 60),
                    "clicks": cliques,
                }
            )

    def _gerar_venda(self, empresa, sigla, id_lead, loja, a_partir_de: datetime) -> None:
        s = self._sorteio
        situacao = s.choices(("won", "lost", "open"), (55, 30, 15))[0]
        fechada = min(a_partir_de + timedelta(hours=s.randrange(1, 200)), self._relogio)
        self.vendas[empresa].append(
            {
                "id": f"{sigla}-venda-{len(self.vendas[empresa]) + 1:05d}",
                "lead_id": id_lead,
                "store": loja,
                "amount": round(s.uniform(150, 9000), 2),
                "status": situacao,
                "closed_at": None if situacao == "open" else _iso(fechada),
                "updated_at": _iso(fechada),
            }
        )

    # --- o que os testes usam para fazer a fonte mudar ---------------------

    def _agora(self) -> str:
        self._relogio += timedelta(seconds=1)
        return _iso(self._relogio)

    def alterar_produto(self, empresa: str, indice: int, **campos) -> dict:
        produto = self.produtos[empresa][indice]
        produto.update(campos, updated_at=self._agora())
        return produto

    def novo_dia(self, empresa: str) -> None:
        """Vira o dia nos anúncios: entra um dia novo para cada campanha."""
        self.hoje += timedelta(days=1)
        campanhas = sorted(
            {(i["platform"], i["campaign_id"], i["campaign_name"]) for i in self.insights[empresa]}
        )
        self._gerar_dia(empresa, campanhas, self.hoje)

    def rever_ultimos_dias(self, empresa: str, dias: int) -> int:
        """A plataforma corrige o investimento dos últimos dias, como fazem as reais."""
        corte = (self.hoje - timedelta(days=dias - 1)).isoformat()
        revistos = [i for i in self.insights[empresa] if i["date"] >= corte]
        for insight in revistos:
            insight["spend"] = round(insight["spend"] * 1.1 + 1, 2)
        return len(revistos)
