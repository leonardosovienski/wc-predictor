"""Agregação multi-fonte — fusão ponto-a-ponto e TWAP (funções puras, sem rede).

Consolidar o mesmo dado de várias exchanges imuniza o sinal contra a anomalia de uma
única corretora. `published_at` do consolidado = max entre as fontes (o dado fundido só
fica disponível quando a última fonte publicou) → preserva o anti-lookahead.
"""
from __future__ import annotations

import statistics

from predictor_core.data.contracts import MarketDataPoint

_FIELDS = ("open", "high", "low", "close", "volume")


def _fuse_per_timestamp(series_by_source: list[list[MarketDataPoint]],
                        reducer, source_label: str) -> list[MarketDataPoint]:
    """Agrupa candles de várias fontes por timestamp e funde cada campo com `reducer`."""
    buckets: dict = {}
    for series in series_by_source:
        for p in series:
            buckets.setdefault(p.timestamp, []).append(p)
    out = []
    for ts in sorted(buckets):
        pts = buckets[ts]
        fused = {f: reducer([getattr(p, f) for p in pts]) for f in _FIELDS}
        out.append(MarketDataPoint(
            symbol=pts[0].symbol, timestamp=ts,
            open=fused["open"], high=fused["high"], low=fused["low"],
            close=fused["close"], volume=fused["volume"],
            source=source_label, interval=pts[0].interval,
            published_at=max(p.published_at for p in pts)))
    return out


def consensus_median(series_by_source: list[list[MarketDataPoint]]) -> list[MarketDataPoint]:
    """Mediana ponto-a-ponto entre fontes (robusta a outlier de uma exchange)."""
    return _fuse_per_timestamp(series_by_source, statistics.median, "consensus_median")


def consensus_mean(series_by_source: list[list[MarketDataPoint]]) -> list[MarketDataPoint]:
    """Média ponto-a-ponto entre fontes."""
    return _fuse_per_timestamp(series_by_source, statistics.fmean, "consensus_mean")


def twap(points: list[MarketDataPoint]) -> float:
    """Time-Weighted Average Price: média dos closes ponderada pelo Δt de cada candle
    (Σ close·Δt / Σ Δt). Em grade uniforme = média simples; com lacunas, candles que
    cobrem mais tempo pesam mais. Levanta em série vazia."""
    if not points:
        raise ValueError("twap: série vazia")
    ordered = sorted(points, key=lambda p: p.timestamp)
    if len(ordered) == 1:
        return ordered[0].close
    num = den = 0.0
    for i, p in enumerate(ordered):
        if i < len(ordered) - 1:
            dt = (ordered[i + 1].timestamp - p.timestamp).total_seconds()
        else:
            dt = (ordered[i].timestamp - ordered[i - 1].timestamp).total_seconds()
        num += p.close * dt
        den += dt
    return num / den if den else ordered[-1].close
