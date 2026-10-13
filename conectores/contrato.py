"""Leitura tipada dos campos que a fonte manda.

Cada conector declara o que espera de um item usando estas funções. Quando um
campo obrigatório não vem, o erro leva o nome do campo: é assim que o motor
separa "um item ruim" de "a fonte mudou o formato".
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation


class ItemInvalido(Exception):
    """O item não pode ser gravado. `campo_ausente` vem preenchido se faltou um campo."""

    def __init__(self, motivo: str, campo_ausente: str | None = None) -> None:
        super().__init__(motivo)
        self.campo_ausente = campo_ausente


class ContratoQuebrado(Exception):
    """A resposta inteira saiu do formato combinado. A execução para."""


def _bruto(item: dict, campo: str, obrigatorio: bool):
    valor = item.get(campo)
    if valor is None or valor == "":
        if obrigatorio:
            raise ItemInvalido(f"campo '{campo}' ausente", campo_ausente=campo)
        return None
    return valor


def texto(item: dict, campo: str, *, obrigatorio: bool = True) -> str | None:
    valor = _bruto(item, campo, obrigatorio)
    return None if valor is None else str(valor)


def inteiro(item: dict, campo: str, *, minimo: int | None = 0) -> int:
    valor = _bruto(item, campo, True)
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        raise ItemInvalido(f"campo '{campo}' não é inteiro: {valor!r}") from None
    if minimo is not None and numero < minimo:
        raise ItemInvalido(f"campo '{campo}' abaixo de {minimo}: {numero}")
    return numero


def dinheiro(item: dict, campo: str) -> Decimal:
    valor = _bruto(item, campo, True)
    try:
        # Passa por str para não herdar o erro de arredondamento do float do JSON.
        numero = Decimal(str(valor))
    except InvalidOperation:
        raise ItemInvalido(f"campo '{campo}' não é número: {valor!r}") from None
    if numero < 0:
        raise ItemInvalido(f"campo '{campo}' negativo: {numero}")
    return numero.quantize(Decimal("0.01"))


def booleano(item: dict, campo: str) -> bool:
    valor = _bruto(item, campo, True)
    if not isinstance(valor, bool):
        raise ItemInvalido(f"campo '{campo}' não é verdadeiro/falso: {valor!r}")
    return valor


def instante(item: dict, campo: str, *, obrigatorio: bool = True) -> datetime | None:
    valor = _bruto(item, campo, obrigatorio)
    if valor is None:
        return None
    try:
        lido = datetime.fromisoformat(str(valor))
    except ValueError:
        raise ItemInvalido(f"campo '{campo}' não é data e hora: {valor!r}") from None
    if lido.tzinfo is None:
        raise ItemInvalido(f"campo '{campo}' veio sem fuso: {valor!r}")
    return lido


def dia(item: dict, campo: str) -> date:
    valor = _bruto(item, campo, True)
    try:
        return date.fromisoformat(str(valor))
    except ValueError:
        raise ItemInvalido(f"campo '{campo}' não é data: {valor!r}") from None


def um_de(item: dict, campo: str, opcoes: dict[str, str]) -> str:
    """Traduz um valor fechado da fonte. Valor novo que a fonte inventar é recusado."""
    valor = _bruto(item, campo, True)
    if valor not in opcoes:
        raise ItemInvalido(f"campo '{campo}' com valor desconhecido: {valor!r}")
    return opcoes[valor]
