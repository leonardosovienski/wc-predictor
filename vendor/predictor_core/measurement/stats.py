"""predictor-core.measurement.stats — régua financeira + Spearman.

Sharpe/Sortino/max_drawdown/PSR (Lente 1) + Spearman e seu IC em blocos. A família de
bootstrap (Lente 2) mudou-se para `measurement.bootstrap`; `block_bootstrap_ci` e
`ci_mean` permanecem AQUI como wrappers DEPRECIADOS (emitem DeprecationWarning e
delegam a `bootstrap_ci`) para não quebrar consumidores durante o ciclo de migração.
"""
import math
import warnings
from typing import Callable

from predictor_core.measurement.bootstrap import bootstrap_ci


# --- Spearman ---------------------------------------------------------------

def _ranks(values: list[float]) -> list[float]:
    """Ranks médios (1-based), empates pela média."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(values):
        j = i
        while j + 1 < len(values) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    return ranks


def spearman(x: list[float], y: list[float]) -> float | None:
    """Correlação de Spearman = Pearson sobre os ranks. None se n<3 ou variância nula."""
    n = len(x)
    if n < 3:
        return None
    rx, ry = _ranks(x), _ranks(y)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    if vx == 0 or vy == 0:
        return None
    return cov / ((vx * vy) ** 0.5)


def spearman_block_ci(pairs, *, block_length: int = 5, n_boot: int = 10_000,
                      confidence: float = 0.95, seed: int = 42):
    """(rho_pontual, lo, hi) do Spearman entre pares (x, y) ORDENADOS NO TEMPO.

    Reamostra os pares em blocos (preserva a dependência serial de horizontes
    sobrepostos). (None, None, None) se n<4. Adapta block_length a amostras pequenas."""
    n = len(pairs)
    if n < 4:
        return None, None, None
    bl = max(1, min(block_length, n // 3))
    rho = spearman([p[0] for p in pairs], [p[1] for p in pairs])
    lo, hi, _ = bootstrap_ci(
        pairs, lambda u: spearman([p[0] for p in u], [p[1] for p in u]),
        scheme="moving", block_length=bl, n_boot=n_boot, confidence=confidence, seed=seed)
    return rho, lo, hi


# --- Sharpe / Sortino / Drawdown -------------------------------------------

def sharpe(returns: list[float], periods_per_year: int = 252) -> float:
    """Sharpe anualizado (assume risk-free=0). Série constante ≠ 0 → sinal do retorno."""
    if len(returns) < 2:
        return float("nan")
    n = len(returns)
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / (n - 1)
    if var == 0:
        # série constante: retorno positivo → +inf, negativo → -inf, zero → nan
        if mean > 0:
            return float("inf")
        if mean < 0:
            return float("-inf")
        return float("nan")
    std = math.sqrt(var)
    return (mean / std) * math.sqrt(periods_per_year)


def sortino(returns: list[float], periods_per_year: int = 252) -> float:
    """Sortino anualizado (assume MAR=0)."""
    if len(returns) < 2:
        return float("nan")
    n = len(returns)
    mean = sum(returns) / n
    downside_sq = sum(r ** 2 for r in returns if r < 0)
    downside_std = math.sqrt(downside_sq / n)
    if downside_std == 0:
        return float("nan")
    return (mean / downside_std) * math.sqrt(periods_per_year)


def max_drawdown(equity: list[float]) -> float:
    """Max drawdown sobre uma EQUITY CURVE (nível acumulado, não retornos crus).

    CONTRATO: `equity` é o nível de capital/preço (ex.: 100, 103, 99...), NÃO uma
    lista de retornos. Passar retornos crus (que oscilam perto de 0) faz `peak`
    nunca passar de ~0 e o drawdown colapsar para ~0 silenciosamente — bug medido
    no previsao-cripto/v3. Para equity que cruza zero ou fica negativa (log-equity,
    conta alavancada), o drawdown relativo perde sentido; aqui levantamos em vez de
    devolver 0 enganoso."""
    peak = float("-inf")
    mdd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        if peak <= 0:
            raise ValueError(
                "max_drawdown: equity <= 0 — recebeu retornos crus em vez de "
                "equity curve? (drawdown relativo indefinido para nível <= 0)")
        dd = (peak - v) / peak
        if dd > mdd:
            mdd = dd
    return mdd


# --- LENTE 1 do pedágio: Probabilistic Sharpe Ratio (closed-form, não-normalidade) ---

def _standardized_moments(data: list) -> tuple:
    """(n, média, desvio populacional, assimetria, curtose NÃO-excesso).

    Curtose normal -> 3 (convenção de Bailey & López de Prado, não a de excesso).
    """
    n = len(data)
    mean = sum(data) / n
    m2 = sum((x - mean) ** 2 for x in data) / n
    if m2 == 0:
        return n, mean, 0.0, 0.0, 3.0
    m3 = sum((x - mean) ** 3 for x in data) / n
    m4 = sum((x - mean) ** 4 for x in data) / n
    return n, mean, m2 ** 0.5, m3 / m2 ** 1.5, m4 / m2 ** 2


def _normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def probabilistic_sharpe_ratio(returns: list, benchmark_sharpe: float = 0.0) -> float:
    """PSR — Probabilistic Sharpe Ratio (Bailey & López de Prado, 2012).

    Devolve P(Sharpe verdadeiro > benchmark_sharpe), corrigindo por assimetria,
    curtose e tamanho da amostra — pune estratégias que inflam o Sharpe com cauda
    gorda (risco de ruína). LENTE 1 do pedágio: fórmula fechada, custo ~zero,
    primeira barreira ANTES do block bootstrap pesado.

    `benchmark_sharpe` está em unidades POR-PERÍODO (o mesmo Sharpe não-anualizado
    que esta função observa internamente). Default 0.0 = nulo "sem skill".

    LIMITE: assume i.i.d. — NÃO corrige autocorrelação. Por isso existe a LENTE 2
    (bootstrap_ci pareado), que assume esse fardo. As duas são complementares.
    Verificado contra a implementação do QuantConnect/LEAN (Common/Statistics/Statistics.cs).
    """
    if len(returns) < 3:
        return float("nan")
    n, mean, std, skew, kurt = _standardized_moments(returns)
    if std == 0:
        return float("nan")
    sr = mean / std  # Sharpe observado por período (não anualizado)
    variance = (1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr * sr) / (n - 1)
    if variance <= 0:
        return float("nan")
    return _normal_cdf((sr - benchmark_sharpe) / variance ** 0.5)


# --- Wrappers DEPRECIADOS (migração) ---------------------------------------
# A família de bootstrap agora vive em measurement.bootstrap. Estes wrappers mantêm
# a API 0.8.0 viva durante um ciclo de deprecação — consumidores migram no seu ritmo.

def block_bootstrap_ci(series: list, statistic: Callable, block_length: int = 21,
                       n_boot: int = 10_000, confidence: float = 0.95, seed: int = 42,
                       method: str = "moving") -> tuple:
    """DEPRECIADO: use `predictor_core.measurement.bootstrap.bootstrap_ci(..., scheme=)`.
    `method` mapeia para `scheme` ('moving'/'stationary')."""
    warnings.warn(
        "block_bootstrap_ci está depreciado; use measurement.bootstrap.bootstrap_ci"
        "(..., scheme='moving'|'stationary'|'cluster').",
        DeprecationWarning, stacklevel=2)
    return bootstrap_ci(series, statistic, scheme=method, block_length=block_length,
                        n_boot=n_boot, confidence=confidence, seed=seed)


def ci_mean(data: list[float], confidence: float = 0.95,
            n_boot: int = 10_000, seed: int = 42) -> tuple[float, float]:
    """DEPRECIADO: use `bootstrap_ci(data, mean, scheme='iid')`. IC iid para a média —
    INVÁLIDO para séries autocorrelacionadas."""
    warnings.warn(
        "ci_mean está depreciado; use measurement.bootstrap.bootstrap_ci"
        "(data, lambda u: sum(u)/len(u), scheme='iid').",
        DeprecationWarning, stacklevel=2)
    lo, hi, _ = bootstrap_ci(data, lambda u: sum(u) / len(u), scheme="iid",
                             n_boot=n_boot, confidence=confidence, seed=seed)
    return lo, hi
