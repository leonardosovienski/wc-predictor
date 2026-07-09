"""Contratos da camada de dados — os envelopes que atravessam a fronteira fonte→domínio.

`MarketDataPoint` (OHLCV) e `SignalPoint` (sinal de baixa frequência, macro/sentimento)
carregam `published_at` OBRIGATÓRIO — o instante em que o dado ficou publicamente
disponível, âncora do as-of join contra lookahead. Um conector concreto traduz o
formato nativo de uma API para estes envelopes; o domínio só enxerga os contratos.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from datetime import datetime


class DataUnavailableError(Exception):
    """Nenhuma fonte conseguiu entregar o dado — sinal terminal do Router após esgotar
    todos os provedores. O domínio decide como reagir (pular ativo, degradar, etc.)."""


@dataclass(frozen=True)
class MarketDataPoint:
    """Envelope imutável de um ponto de mercado (OHLCV + metadados de origem).

    `timestamp` = instante do candle (abertura do período). `published_at` = quando o
    dado ficou disponível (âncora anti-lookahead). Para preço de exchange coincidem;
    para fontes de baixa frequência, divergem. `high >= low` e `published_at >=
    timestamp` são invariantes checadas na construção (falha explícita)."""

    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str
    interval: str
    published_at: datetime

    def __post_init__(self) -> None:
        if self.high < self.low:
            raise ValueError(
                f"MarketDataPoint inválido para {self.symbol}: high={self.high} < low={self.low}")
        if self.published_at < self.timestamp:
            raise ValueError(
                f"MarketDataPoint inválido para {self.symbol}: published_at "
                f"({self.published_at.isoformat()}) anterior ao timestamp "
                f"({self.timestamp.isoformat()}) — violaria integridade temporal")


@dataclass(frozen=True)
class SignalPoint:
    """Envelope de um sinal de baixa frequência não-OHLCV (Fear&Greed, Selic, IPCA...).

    `published_at` para o as-of join, idêntico em papel ao do MarketDataPoint. Séries
    macro são REVISADAS: cada revisão é um SignalPoint separado, com seu `published_at`
    (quando ficou público) e `vintage` (quando foi coletado). O as-of por published_at
    escolhe o valor vigente em cada data — sem lookahead, sem lógica extra.
      timestamp      : instante do dado (grade do as-of e do max_staleness).
      reference_date : referência semântica (ex.: mês do IPCA); default = timestamp.
      vintage        : quando o dado foi coletado; distingue revisões na persistência."""

    name: str
    timestamp: datetime
    value: float
    source: str
    published_at: datetime
    reference_date: datetime | None = None
    vintage: datetime | None = None

    def __post_init__(self) -> None:
        if self.published_at < self.timestamp:
            raise ValueError(
                f"SignalPoint '{self.name}': published_at anterior ao timestamp "
                "— violaria integridade temporal")


class DataProvider(abc.ABC):
    """Contrato que todo conector de mercado concreto implementa.

    Implementações devem ser baratas de instanciar (sem rede no __init__) e fazer toda
    a I/O nos métodos async abaixo."""

    #: Nome curto e estável da fonte (ex.: "binance"). Vai no campo `source` e na telemetria.
    name: str = "abstract"

    @abc.abstractmethod
    async def fetch_ohlcv(self, symbol: str, interval: str = "1d",
                          limit: int = 1) -> list[MarketDataPoint]:
        """Últimos `limit` candles de `symbol` no `interval`. `symbol` é o ID canônico
        do domínio (ex.: "bitcoin"); o conector o traduz para o formato nativo. Deve
        levantar exceção (qualquer) em falha — o Router decide se tenta a próxima fonte."""

    @abc.abstractmethod
    async def health_check(self) -> bool:
        """True se a fonte parece saudável. Usado pelo Circuit Breaker."""


class SignalProvider(abc.ABC):
    """Contrato de uma fonte de sinal de baixa frequência (não-OHLCV)."""

    name: str = "abstract_signal"

    @abc.abstractmethod
    async def fetch(self, limit: int = 30) -> list[SignalPoint]:
        """Últimos `limit` pontos do sinal, com published_at."""
