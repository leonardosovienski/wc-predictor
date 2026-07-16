"""predictor-core.kernel.timeindex — controle ISO/UTC canônico (Onda 1 da v1.3.0).

Todo timestamp que cruza uma fronteira do core (telemetria, trials.json,
PredictionPoint, JSONL store) deve ser UTC timezone-aware e serializar como
ISO-8601 com 'Z'. Antes cada módulo fazia sua conversão ad hoc
(`strftime("%Y-%m-%dT%H:%M:%SZ")` no trials, `isoformat()` no harness) — este
módulo é o ponto único de verdade para as três operações:

  utcnow()        — agora, timezone-aware UTC (nunca use datetime.utcnow(), naive).
  to_utc(dt)      — normaliza: aware → converte; naive → ERRO (adivinhar fuso é bug).
  iso_z(dt)       — serializa como 'YYYY-MM-DDTHH:MM:SSZ' (o formato do trials.json).
  parse_iso(s)    — parse tolerante a 'Z' e offset, retorna aware UTC.
"""
from __future__ import annotations

from datetime import datetime, timezone

__all__ = ["utcnow", "to_utc", "iso_z", "parse_iso", "NaiveDatetimeError"]


class NaiveDatetimeError(ValueError):
    """Datetime sem timezone cruzou uma fronteira do core — o fuso é ambíguo e
    adivinhar (assumir local? assumir UTC?) é a raiz clássica de lookahead de
    horas. Anexe tzinfo explicitamente na origem do dado."""


def utcnow() -> datetime:
    """Agora em UTC, timezone-aware."""
    return datetime.now(timezone.utc)


def to_utc(dt: datetime) -> datetime:
    """Normaliza `dt` para UTC. Naive → NaiveDatetimeError (nunca adivinha fuso)."""
    if dt.tzinfo is None:
        raise NaiveDatetimeError(
            f"datetime naive ({dt.isoformat()}) na fronteira do core — "
            "anexe tzinfo na origem (ex.: dt.replace(tzinfo=timezone.utc) "
            "se você SABE que é UTC).")
    return dt.astimezone(timezone.utc)


def iso_z(dt: datetime) -> str:
    """Serialização canônica: ISO-8601 UTC com sufixo 'Z', precisão de segundos —
    o formato que `validate_trials` exige em registered_at."""
    return to_utc(dt).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str) -> datetime:
    """Parse de ISO-8601 ('Z' ou offset explícito) → aware UTC.
    String sem offset nenhum → NaiveDatetimeError (mesma regra do to_utc)."""
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return to_utc(dt)
