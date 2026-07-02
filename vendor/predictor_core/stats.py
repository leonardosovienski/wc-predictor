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

    method='moving'    — Circular Block Bootstrap (blocos fixos block_length, com
                          wrap circular (start+j)%n — costura o fim ao início da série)
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
        # Descarta reamostra inválida: None (Spearman sem variância) OU não-finita
        # (Sharpe/Sortino de bloco constante → ±inf/nan). nan quebra o sort() abaixo
        # (comparações com nan são False → ordem indefinida → percentil lê posição
        # arbitrária); ±inf desloca o percentil. Ambos corromperiam o IC em silêncio.
        if stat is not None and math.isfinite(stat):
            boot_stats.append(stat)

    n_valid = len(boot_stats)
    if n_valid and n_valid < 0.9 * n_boot:
        # >10% das reamostras inválidas: a distribuição ficou condicionada a um
        # subconjunto enviesado (IC mais estreito → significância fabricada). Não
        # silencie — quem consome o veredito precisa saber que ele é suspeito.
        logger.warning(
            "block_bootstrap_ci: %d/%d reamostras inválidas descartadas — "
            "IC calculado sobre subconjunto condicionado, trate como suspeito",
            n_boot - n_valid, n_boot)

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
