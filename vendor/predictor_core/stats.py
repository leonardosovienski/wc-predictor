"""predictor-core.stats — estimadores estatísticos: ci_mean, block bootstrap, métricas de score."""
import math
import random
import logging
from typing import Callable

import numpy as np

logger = logging.getLogger(__name__)


def ci_mean(data: list[float], confidence: float = 0.95,
            n_boot: int = 10_000, seed: int = 42) -> tuple[float, float]:
    """IC bootstrap iid para a média. INVÁLIDO para séries autocorrelacionadas — use block_bootstrap."""
    rng = random.Random(seed)
    n = len(data)
    means = sorted(
        sum(rng.choices(data, k=n)) / n
        for _ in range(n_boot)
    )
    alpha = (1 - confidence) / 2
    lo = means[int(alpha * n_boot)]
    hi = means[int((1 - alpha) * n_boot)]
    return lo, hi


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
    """Correlação de Spearman = Pearson sobre os ranks. None se n<3 ou variância nula.
    Primitiva de validação da plataforma (promovida do previsao-cripto)."""
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


def block_bootstrap_ci(
    series: list,
    statistic: Callable[[list], float],
    block_length: int = 21,
    n_boot: int = 10_000,
    confidence: float = 0.95,
    seed: int = 42,
    method: str = "moving",
) -> tuple[float, float, list[float]]:
    """IC bootstrap em blocos para estatística arbitrária sobre série temporal.

    É a LENTE 2 do pedágio: não-paramétrica, assume o fardo da autocorrelação
    (blocos) e da dependência cross (reamostragem PAREADA) que o PSR ignora.

    `series` é uma lista ORDENADA NO TEMPO. Cada unidade pode ser um escalar
    (ex.: CLV por aposta) OU uma tupla pareada (ex.: (ret_estrategia, ret_benchmark)
    ou (score, retorno_fwd)) — `statistic` desempacota a unidade. Exemplos:
        block_bootstrap_ci(clv, mean)                                    # escalar
        block_bootstrap_ci(list(zip(a, b)),                              # pareado
            lambda u: sharpe([x[0] for x in u]) - sharpe([x[1] for x in u]))

    INVARIANTE DE CORREÇÃO: reamostra BLOCOS de UNIDADES (linhas no tempo), NUNCA
    colunas independentes. É isso que preserva a cross-correlação (dentro da
    unidade) E a autocorrelação (entre unidades do bloco). Reamostrar colunas
    separado infla o IC da diferença e fabrica "inconclusivo" falso.

    method='moving'    — Moving Block Bootstrap (blocos fixos de tamanho block_length)
    method='stationary' — Stationary Bootstrap (comprimentos ~ Geométrica(p=1/block_length),
                          índices circulares conforme Politis & Romano 1994)

    Retorna (lo, hi, distribuição bootstrap).
    """
    rng = random.Random(seed)
    n = len(series)
    if n < block_length:
        raise ValueError(f"series length {n} < block_length {block_length}")

    p = 1.0 / block_length  # parâmetro geométrica para stationary bootstrap

    boot_stats: list[float] = []
    for _ in range(n_boot):
        resampled: list = []
        while len(resampled) < n:
            start = rng.randrange(n)
            if method == "stationary":
                length = _geom_sample(rng, p)
            else:
                length = block_length
            for j in range(length):
                if len(resampled) >= n:
                    break
                resampled.append(series[(start + j) % n])
        stat = statistic(resampled[:n])
        if stat is not None:        # reamostra degenerada (ex.: Spearman sem variância) cai fora
            boot_stats.append(stat)

    if not boot_stats:
        return None, None, []
    boot_stats.sort()
    m = len(boot_stats)
    alpha = (1 - confidence) / 2
    lo = boot_stats[max(0, int(alpha * m))]
    hi = boot_stats[min(m - 1, int((1 - alpha) * m))]
    return lo, hi, boot_stats


def spearman_block_ci(pairs, *, block_length: int = 5, n_boot: int = 10_000,
                      confidence: float = 0.95, seed: int = 42):
    """(rho_pontual, lo, hi) do Spearman entre pares (x, y) ORDENADOS NO TEMPO.

    Reamostra os pares em blocos (preserva a dependência serial de horizontes
    sobrepostos). (None, None, None) se n<4. Adapta block_length a amostras pequenas.
    Promovido do previsao-cripto: agora é primitiva canônica de significância."""
    n = len(pairs)
    if n < 4:
        return None, None, None
    bl = max(1, min(block_length, n // 3))
    rho = spearman([p[0] for p in pairs], [p[1] for p in pairs])
    lo, hi, _ = block_bootstrap_ci(
        pairs, lambda u: spearman([p[0] for p in u], [p[1] for p in u]),
        block_length=bl, n_boot=n_boot, confidence=confidence, seed=seed)
    return rho, lo, hi


def _geom_sample(rng: random.Random, p: float) -> int:
    """Amostra de distribuição Geométrica(p) — mínimo 1."""
    k = 1
    while rng.random() > p:
        k += 1
    return k


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


def max_drawdown(cum_returns: list[float]) -> float:
    """Max drawdown sobre série de retornos acumulados (equity curve)."""
    peak = float("-inf")
    mdd = 0.0
    for v in cum_returns:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
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


# ---------------------------------------------------------------------------
# ZONA 0 — Métricas de Score Probabilístico (vetorizadas, zero loops Python)
# Entrada: tensores NumPy P e Y de shape (N, G, G) onde G = max_goals+1 (tipicamente 12).
# Y é one-hot encoded (exatamente uma célula 1 por partida).
# ---------------------------------------------------------------------------

def log_loss_matrix(P: np.ndarray, Y: np.ndarray, eps: float = 1e-12) -> float:
    """Log-Loss (Cross-Entropy) vetorizado para matrizes de placar (N, G, G).
    P: probabilidades previstas; Y: one-hot. Sem loops Python nativos."""
    return float(-np.sum(Y * np.log(np.clip(P, eps, 1.0))) / P.shape[0])


def brier_score_multiclass(P: np.ndarray, Y: np.ndarray) -> float:
    """Brier Score Multi-Class vetorizado. BS = mean_n Σ_{i,j} (P_{n,i,j} - Y_{n,i,j})².
    P, Y: (N, G, G). Varia em [0, 2] para k classes (aqui k=G²)."""
    return float(np.mean(np.sum((P - Y) ** 2, axis=(1, 2))))


def brier_skill_score(P_model: np.ndarray, P_base: np.ndarray, Y: np.ndarray) -> float:
    """BSS = 1 - BS_model / BS_base.
    >0 = melhora; 0 = igual ao base; <0 = piora. nan se BS_base=0."""
    bs_model = brier_score_multiclass(P_model, Y)
    bs_base = brier_score_multiclass(P_base, Y)
    return float("nan") if bs_base == 0.0 else 1.0 - bs_model / bs_base


def _autocovariances_fft(d_c: np.ndarray, max_lag: int) -> np.ndarray:
    """Autocovarâncias γ̂_0…γ̂_{max_lag-1} via FFT. Sem loops Python."""
    n = d_c.shape[0]
    fft_len = 1 << int(np.ceil(np.log2(2 * n)))   # próxima pot. de 2 evita aliasing
    D = np.fft.rfft(d_c, n=fft_len)
    acf_raw = np.fft.irfft(D * np.conj(D)).real[:max_lag]
    lags = np.arange(max_lag, dtype=float)
    return acf_raw / np.maximum(n - lags, 1.0)     # normalização não-viesada por lag


def diebold_mariano_hln(
    e1: np.ndarray, e2: np.ndarray, h: int = 1
) -> tuple[float, float]:
    """Teste Diebold-Mariano com correção Harvey-Leybourne-Newbold (1997).

    e1, e2: vetores de erros de previsão (N,) — diferencial de perda = e1²-e2².
    h: horizonte de previsão (padrão 1). Para h>1 a variância espectral inclui
    as h-1 autocovarâncias (heteroskedasticidade de séries sobrepostas).

    A correção HLN ajusta o numerador pelo fator √((n+1-2h+h(h-1)/n)/n) e usa
    distribuição t(n-1) em vez da normal — crítico para n<30 (amostras pequenas
    de temporadas esportivas). Sem loops Python nativos.

    Retorna (dm_hln, p_valor_bilateral). nan se variância nula."""
    from scipy.stats import t as t_dist

    n = e1.shape[0]
    d = e1 ** 2 - e2 ** 2          # diferencial de perda quadrática
    d_bar = d.mean()
    d_c = d - d_bar

    gamma = _autocovariances_fft(d_c, max(h, 1))
    # Variância espectral na frequência zero: S² = (γ₀ + 2·Σγ_k) / n
    s2 = (gamma[0] + 2.0 * gamma[1:].sum()) / n

    if s2 <= 0.0:
        return float("nan"), float("nan")

    dm = d_bar / np.sqrt(s2)

    # Fator de correção HLN para amostras finitas
    hln = np.sqrt((n + 1.0 - 2.0 * h + h * (h - 1.0) / n) / n)
    dm_hln = float(dm * hln)

    p_value = float(2.0 * t_dist.sf(abs(dm_hln), df=n - 1))
    return dm_hln, p_value


# ---------------------------------------------------------------------------

def probabilistic_sharpe_ratio(returns: list, benchmark_sharpe: float = 0.0) -> float:
    """PSR — Probabilistic Sharpe Ratio (Bailey & López de Prado, 2012).

    Devolve P(Sharpe verdadeiro > benchmark_sharpe), corrigindo por assimetria,
    curtose e tamanho da amostra — pune estratégias que inflam o Sharpe com cauda
    gorda (risco de ruína). LENTE 1 do pedágio: fórmula fechada, custo ~zero,
    primeira barreira ANTES do block bootstrap pesado.

    `benchmark_sharpe` está em unidades POR-PERÍODO (o mesmo Sharpe não-anualizado
    que esta função observa internamente). Default 0.0 = nulo "sem skill".

    LIMITE: assume i.i.d. — NÃO corrige autocorrelação. Por isso existe a LENTE 2
    (block_bootstrap_ci pareado), que assume esse fardo. As duas são complementares.
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
