"""Cliente HTTP das fontes: autenticação, nova tentativa e limite de requisições.

Três respostas pedem tratamentos diferentes, e misturá-las é o erro comum:

- 401: o token venceu. Pede outro e repete, uma vez.
- 429: a fonte mandou esperar. Espera o que ela disse em `Retry-After`.
- 5xx, falha de rede ou resposta que não é JSON: pode ser passageiro. Repete
  com espera crescente.

Qualquer outro 4xx é erro de quem chamou. Repetir não muda a resposta, então
sobe na hora.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable

import httpx

# Pede token novo um pouco antes de o atual vencer, para não gastar uma
# requisição só para descobrir que ele venceu.
FOLGA_DO_TOKEN = 60.0


class ErroDeApi(Exception):
    """A fonte recusou a requisição (4xx). Repetir não resolve."""


class FonteIndisponivel(Exception):
    """A fonte não respondeu depois de todas as tentativas."""


class _Passageiro(Exception):
    """Falha que vale repetir. `espera` vem preenchida se a fonte disse quanto esperar."""

    def __init__(self, motivo: str, espera: float | None = None) -> None:
        super().__init__(motivo)
        self.espera = espera


class ClienteApi:
    def __init__(
        self,
        http: httpx.Client,
        client_id: str,
        client_secret: str,
        *,
        tentativas: int = 5,
        espera_base: float = 0.5,
        espera_maxima: float = 30.0,
        dormir: Callable[[float], None] = time.sleep,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self.http = http
        self.client_id = client_id
        self.client_secret = client_secret
        self.tentativas = tentativas
        self.espera_base = espera_base
        self.espera_maxima = espera_maxima
        self.dormir = dormir
        self.relogio = relogio
        self._token: str | None = None
        self._token_vence_em = 0.0

    def get(self, caminho: str, **parametros) -> dict:
        parametros = {k: v for k, v in parametros.items() if v is not None}
        renovou = False
        tentativa = 0
        while True:
            tentativa += 1
            try:
                resposta = self._conferida(
                    self.http.get(
                        caminho,
                        params=parametros,
                        headers={"Authorization": f"Bearer {self._obter_token()}"},
                    )
                )
                if resposta.status_code == 401 and not renovou:
                    self._token = None
                    renovou = True
                    tentativa -= 1  # renovar o token não gasta tentativa
                    continue
                if resposta.is_error:
                    raise ErroDeApi(f"{resposta.status_code} em {caminho}: {resposta.text[:200]}")
                try:
                    return resposta.json()
                except ValueError:
                    # Página de erro de um proxy no caminho, com status 200.
                    raise _Passageiro("resposta que não é JSON") from None
            except httpx.TransportError as erro:
                motivo, espera = f"falha de rede: {erro}", None
            except _Passageiro as erro:
                motivo, espera = str(erro), erro.espera

            if tentativa >= self.tentativas:
                raise FonteIndisponivel(f"{caminho}: {motivo}, após {tentativa} tentativas")
            self.dormir(self._espera_crescente(tentativa) if espera is None else espera)

    def _conferida(self, resposta: httpx.Response) -> httpx.Response:
        """Transforma 429 e 5xx em falha passageira. Vale para os dados e para o token."""
        if resposta.status_code == 429:
            try:
                espera = min(self.espera_maxima, float(resposta.headers["Retry-After"]))
            except (KeyError, ValueError):
                espera = None
            raise _Passageiro("limite de requisições (429)", espera)
        if resposta.status_code >= 500:
            raise _Passageiro(f"erro {resposta.status_code} na fonte")
        return resposta

    def _obter_token(self) -> str:
        if self._token is None or self.relogio() >= self._token_vence_em:
            resposta = self._conferida(
                self.http.post(
                    "/oauth/token",
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                    },
                )
            )
            if resposta.is_error:
                raise ErroDeApi(f"autenticação recusada: {resposta.status_code}")
            corpo = resposta.json()
            self._token = corpo["access_token"]
            validade = float(corpo.get("expires_in", 3600))
            self._token_vence_em = self.relogio() + max(0.0, validade - FOLGA_DO_TOKEN)
        return self._token

    def _espera_crescente(self, tentativa: int) -> float:
        """0,5s, 1s, 2s, 4s... até o teto, com sorteio para não bater em bloco."""
        teto = min(self.espera_maxima, self.espera_base * 2 ** (tentativa - 1))
        return teto * (0.5 + random.random() / 2)
