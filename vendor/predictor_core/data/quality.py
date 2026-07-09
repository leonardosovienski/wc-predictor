"""quality — detecção de saltos e inferência de split (funções puras, genéricas).

Promovido do padrão do predictor-stocks (src/adjust.py). Um salto overnight grande sem
ajuste registrado é um evento corporativo (split/grupamento) OU erro de fonte — nunca
se "conserta" o preço na mão: registra-se a trilha e, se a proporção não for redonda,
quarentena. Aqui vivem só as funções PURAS (sem banco); a integração com o schema de
cada domínio (tabelas raw/adjustments/quarantine) fica no domínio.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_SPLIT_RATIOS = (2, 3, 4, 5, 6, 8, 10)
_FACTOR_MIN, _FACTOR_MAX = 0.05, 20.0  # limites de sanidade para fator de ajuste


def overnight_returns(dates, closes):
    """Retornos close-a-close consecutivos: [(date, ret)] a partir do 2º ponto."""
    out = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0:
            out.append((dates[i], closes[i] / closes[i - 1] - 1.0))
    return out


def detect_jumps(dates, closes, threshold):
    """Datas onde |retorno overnight| > threshold (candidatas a split ou erro)."""
    return [(d, r) for d, r in overnight_returns(dates, closes) if abs(r) > threshold]


def infer_split_factor(close_before, close_after, tol=0.08):
    """Fator a MULTIPLICAR os preços ANTES do evento para a série ficar contínua.
    Split 1:r (preço cai ~r×) → 1/r. Grupamento r:1 (preço sobe ~r×) → r. None se não
    há proporção redonda plausível (→ quarentena, decisão do domínio)."""
    if close_before <= 0 or close_after <= 0:
        return None
    ratio = close_before / close_after
    for r in _SPLIT_RATIOS:
        if abs(ratio - r) / r < tol:                 # split: preço caiu ~r×
            return round(1.0 / r, 6)
        if abs(ratio - 1.0 / r) / (1.0 / r) < tol:   # grupamento: preço subiu ~r×
            return float(r)
    return None


def adjusted_closes(dates, closes, adjustments):
    """adjustments: [(ex_date, factor)]. Multiplica os closes ANTES de cada ex_date pelo
    fator — torna a série contínua. Fator <= 0 é rejeitado com ValueError (dado inválido
    não entra em silêncio); fator fora de [_FACTOR_MIN, _FACTOR_MAX] emite warning."""
    out = list(closes)
    for ex_date, factor in adjustments:
        if not (factor > 0):
            raise ValueError(f"fator de ajuste inválido em {ex_date}: {factor!r} (deve ser > 0)")
        if not (_FACTOR_MIN <= factor <= _FACTOR_MAX):
            logger.warning("fator de ajuste suspeito em %s: %.4f (fora de [%.2f, %.0f])",
                           ex_date, factor, _FACTOR_MIN, _FACTOR_MAX)
        out = [c * factor if d < ex_date else c for d, c in zip(dates, out)]
    return out
