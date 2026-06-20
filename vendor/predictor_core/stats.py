"""predictor-core.stats — estimadores estatísticos: ci_mean (iid) e block bootstrap."""
import math
import random
import logging
from typing import Callable

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
    interval: str = "percentile",
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

    interval='percentile' — [q2.5, q97.5] da distribuição bootstrap (clássico). CUIDADO:
                          medido empiricamente como LIBERAL (sub-cobre) no regime de poucos
                          blocos (n/L pequeno) — IC estreito demais, vereditos positivos fáceis.
    interval='t'        — IC-t por blocos: estimativa_pontual ± t(df)·sd_boot, df = nº de
                          blocos − 1. Alarga corretamente quando há poucos blocos. Cobertura
                          empírica ~95% (AR(1), phi até 0.8) com L ~ n/8. Ver `calibrated_ci`.

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
    alpha = (1 - confidence) / 2
    if interval == "t":
        # IC-t por blocos: centro na ESTIMATIVA PONTUAL (não na média bootstrap, que pode
        # ser viesada) ± t(df)·sd, com df = nº de blocos − 1. Corrige a sub-cobertura do
        # percentil quando há poucos blocos. Validado empiricamente (lens2_calibration_study).
        theta = statistic(series)
        if theta is None:
            return None, None, boot_stats
        mb = sum(boot_stats) / len(boot_stats)
        sd = (sum((x - mb) ** 2 for x in boot_stats) / len(boot_stats)) ** 0.5
        nblocks = max(3, n // block_length)         # df mínimo 2 (Cornish-Fisher estável)
        tq = _t_ppf(1 - alpha, nblocks - 1)
        return theta - tq * sd, theta + tq * sd, boot_stats
    boot_stats.sort()
    m = len(boot_stats)
    lo = boot_stats[max(0, int(alpha * m))]
    hi = boot_stats[min(m - 1, int((1 - alpha) * m))]
    return lo, hi, boot_stats


def calibrated_ci(series: list, statistic: Callable[[list], float], *,
                  block_length: int | None = None, n_boot: int = 10_000,
                  confidence: float = 0.95, seed: int = 42, method: str = "moving"):
    """LENTE 2 CALIBRADA — IC com cobertura ~95% validada empiricamente (DESIGN §M5a).

    A régua percentil clássica (`block_bootstrap_ci` default) sub-cobre no regime de poucos
    blocos: medida em 85-93% para um IC nominal de 95%, pior com autocorrelação. Esta variante
    usa o intervalo-t por blocos (estimativa pontual ± t(df)·sd_boot) que restaura a cobertura
    para ~94-97% em AR(1) com phi até 0.8 (estudo `lens2_calibration_study.py`).

    `block_length` default ~ n/8 (>=21): o regime validado (poucos blocos longos + correção t).
    Use esta função em validações que AFIRMAM significância (ex.: Spearman do cripto sobre
    horizontes sobrepostos), onde a liberalidade do percentil produziria falsos positivos.

    Retorna (lo, hi, distribuição bootstrap), igual a `block_bootstrap_ci`.
    """
    n = len(series)
    if block_length is None:
        block_length = max(21, n // 8)
    return block_bootstrap_ci(series, statistic, block_length=block_length, n_boot=n_boot,
                              confidence=confidence, seed=seed, method=method, interval="t")


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


# --- Quantis em stdlib puro (o core não depende de scipy) --------------------

def _normal_ppf(p: float) -> float:
    """Inversa da CDF normal padrão (aproximação racional de Acklam). p em (0,1)."""
    if not 0.0 < p < 1.0:
        raise ValueError("p deve estar em (0,1)")
    a = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00)
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def _t_ppf(p: float, df: float) -> float:
    """Inversa da CDF t de Student via expansão de Cornish-Fisher a partir do quantil
    normal. Precisa para df>=~4 (o regime de nº-de-blocos da LENTE 2)."""
    z = _normal_ppf(p)
    z2 = z * z
    g1 = (z2 * z + z) / 4.0
    g2 = (5 * z2 * z2 * z + 16 * z2 * z + 3 * z) / 96.0
    g3 = (3 * z2 * z2 * z2 * z + 19 * z2 * z2 * z + 17 * z2 * z - 15 * z) / 384.0
    return z + g1 / df + g2 / (df * df) + g3 / (df * df * df)


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
