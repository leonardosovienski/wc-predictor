"""Routers — orquestram tentativas entre provedores de dados.

FallbackRouter: fallback SEQUENCIAL com fail-fast (tenta o primeiro; em falha emite
`data.fallback` e passa ao próximo; se todos falharem, `data.unavailable` +
DataUnavailableError). Sequencial de propósito: ambiente com inspeção TLS penaliza
conexões concorrentes.

AggregationRouter: consolida o MESMO dado de várias fontes em PARALELO (imuniza contra
anomalia de uma corretora); tolera falhas parciais (funde sobre os sobreviventes; só
levanta se TODAS falharem).

Ambos consultam um CircuitBreaker opcional por provedor: fonte com circuito aberto é
pulada (fail-fast) sem gastar requisição. `domain` injetável — a camada é multi-domínio.
"""
from __future__ import annotations

import asyncio

from predictor_core.kernel.obs import emit_event
from predictor_core.data.aggregation import consensus_median, consensus_mean
from predictor_core.data.circuit_breaker import CircuitBreaker
from predictor_core.data.contracts import (
    DataProvider, DataUnavailableError, MarketDataPoint,
)

_DEFAULT_DOMAIN = "data"

_AGG_POLICIES = {
    "consensus_median": consensus_median,
    "consensus_mean": consensus_mean,
}


class FallbackRouter:
    def __init__(self, providers: list[DataProvider],
                 breakers: dict[str, CircuitBreaker] | None = None,
                 *, domain: str = _DEFAULT_DOMAIN):
        if not providers:
            raise ValueError("FallbackRouter exige ao menos um provedor")
        self._providers = providers
        self._breakers = breakers or {}
        self._domain = domain

    async def fetch_ohlcv(self, symbol: str, interval: str = "1d",
                          limit: int = 1) -> list[MarketDataPoint]:
        last_exc: Exception | None = None
        for idx, provider in enumerate(self._providers):
            breaker = self._breakers.get(provider.name)
            if breaker is not None and not breaker.allow():
                emit_event(self._domain, "circuit.skipped", metrics={"provider_index": idx},
                           metadata={"symbol": symbol, "provider": provider.name})
                continue
            try:
                points = await provider.fetch_ohlcv(symbol, interval=interval, limit=limit)
                if breaker is not None:
                    breaker.record_success()
                if idx > 0:
                    emit_event(self._domain, "data.fallback",
                               metrics={"provider_index": idx},
                               metadata={"symbol": symbol, "interval": interval,
                                         "used": provider.name})
                return points
            except Exception as exc:  # noqa: BLE001 — qualquer falha aciona o próximo
                last_exc = exc
                if breaker is not None:
                    breaker.record_failure()
                proximo = self._providers[idx + 1].name if idx + 1 < len(self._providers) else None
                emit_event(self._domain, "data.fallback" if proximo else "data.provider_failed",
                           metrics={"provider_index": idx},
                           metadata={"symbol": symbol, "interval": interval,
                                     "failed": provider.name, "next": proximo,
                                     "error": type(exc).__name__})
        emit_event(self._domain, "data.unavailable",
                   metrics={"n_providers": len(self._providers)},
                   metadata={"symbol": symbol, "interval": interval,
                             "last_error": type(last_exc).__name__ if last_exc else None})
        raise DataUnavailableError(
            f"nenhuma fonte entregou {symbol} ({interval}); último erro: {last_exc!r}"
        ) from last_exc


class AggregationRouter:
    def __init__(self, providers: list[DataProvider], policy: str = "consensus_median",
                 breakers: dict[str, CircuitBreaker] | None = None,
                 *, domain: str = _DEFAULT_DOMAIN):
        if len(providers) < 1:
            raise ValueError("AggregationRouter exige ao menos um provedor")
        if policy not in _AGG_POLICIES:
            raise ValueError(f"política de agregação desconhecida: '{policy}'")
        self._providers = providers
        self._policy = policy
        self._breakers = breakers or {}
        self._domain = domain

    async def _try(self, provider, symbol, interval, limit):
        breaker = self._breakers.get(provider.name)
        if breaker is not None and not breaker.allow():
            emit_event(self._domain, "circuit.skipped", metrics={},
                       metadata={"symbol": symbol, "provider": provider.name})
            return provider.name, None
        try:
            pts = await provider.fetch_ohlcv(symbol, interval=interval, limit=limit)
            if breaker is not None:
                breaker.record_success()
            return provider.name, pts
        except Exception as exc:  # noqa: BLE001
            if breaker is not None:
                breaker.record_failure()
            emit_event(self._domain, "data.provider_failed", metrics={},
                       metadata={"symbol": symbol, "provider": provider.name,
                                 "error": type(exc).__name__})
            return provider.name, None

    async def fetch_ohlcv(self, symbol: str, interval: str = "1d",
                          limit: int = 1) -> list[MarketDataPoint]:
        results = await asyncio.gather(*[
            self._try(p, symbol, interval, limit) for p in self._providers])
        survivors = [pts for _, pts in results if pts]
        used = [name for name, pts in results if pts]
        if not survivors:
            emit_event(self._domain, "data.unavailable",
                       metrics={"n_providers": len(self._providers)},
                       metadata={"symbol": symbol, "interval": interval, "agg": self._policy})
            raise DataUnavailableError(
                f"agregação: nenhuma fonte entregou {symbol} ({interval})")
        fused = _AGG_POLICIES[self._policy](survivors)
        emit_event(self._domain, "data.aggregated",
                   metrics={"n_sources": len(survivors), "n_points": len(fused)},
                   metadata={"symbol": symbol, "interval": interval,
                             "policy": self._policy, "used": used})
        return fused
