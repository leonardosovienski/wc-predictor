"""predictor-core.measurement.bootstrap — família unificada de IC não-paramétrico.

É a LENTE 2 do pedágio: assume o fardo da autocorrelação (blocos) e da dependência
cross (reamostragem PAREADA) que o PSR (Lente 1) ignora. Uma única porta —
`bootstrap_ci(series, statistic, scheme=...)` — com quatro esquemas:

    iid        — reamostra UNIDADES independentes com reposição (o clássico; INVÁLIDO
                 para série autocorrelacionada — use os blocos abaixo).
    moving     — Circular Block Bootstrap: blocos FIXOS de `block_length`, wrap circular.
    stationary — Stationary Bootstrap (Politis & Romano 1994): comprimentos de bloco
                 ~ Geométrica(p=1/block_length), índices circulares.
    cluster    — reamostra CLUSTERS inteiros (via `cluster_key`) com reposição — as
                 unidades de um cluster viajam juntas (ex.: as 3 pernas do 1X2 do mesmo
                 jogo compartilham o choque do resultado). Com 1 unidade por cluster,
                 degenera exatamente no iid.

`series` é uma lista ORDENADA NO TEMPO. Cada unidade pode ser um escalar (ex.: CLV por
aposta) OU uma tupla PAREADA (ex.: (ret_estrategia, ret_benchmark)) — `statistic`
desempacota a unidade. Exemplos:
    bootstrap_ci(clv, mean, scheme="iid")
    bootstrap_ci(list(zip(a, b)), lambda u: sharpe([x[0] for x in u]) - sharpe([x[1] for x in u]),
                 scheme="moving", block_length=21)
    bootstrap_ci(bets, mean, scheme="cluster", cluster_key=lambda b: b["game_id"])

INVARIANTE DE CORREÇÃO: reamostra BLOCOS/CLUSTERS de UNIDADES (linhas no tempo), NUNCA
colunas independentes. É isso que preserva a cross-correlação (dentro da unidade) E a
autocorrelação (entre unidades). Reamostrar colunas separado infla o IC da diferença e
fabrica "inconclusivo" falso.

Retorna (lo, hi, distribuição bootstrap). Reamostras inválidas (statistic None ou
não-finita) são descartadas; > 10% de descarte emite warning (IC condicionado, suspeito).
"""
import logging
import math
import random
from typing import Callable

logger = logging.getLogger(__name__)

_SCHEMES = ("iid", "moving", "stationary", "cluster")


def _geom_sample(rng: random.Random, p: float) -> int:
    """Amostra de distribuição Geométrica(p) — mínimo 1."""
    k = 1
    while rng.random() > p:
        k += 1
    return k


def _resample_blocks(series, rng, n, block_length, stationary):
    """Uma reamostra por blocos circulares (moving ou stationary)."""
    p = 1.0 / block_length
    out = []
    while len(out) < n:
        start = rng.randrange(n)
        length = _geom_sample(rng, p) if stationary else block_length
        for j in range(length):
            if len(out) >= n:
                break
            out.append(series[(start + j) % n])
    return out[:n]


def _resample_clusters(clusters, rng):
    """Uma reamostra por cluster: sorteia G clusters com reposição, concatena as unidades."""
    g = len(clusters)
    out = []
    for _ in range(g):
        out.extend(clusters[rng.randrange(g)])
    return out


def bootstrap_ci(
    series: list,
    statistic: Callable[[list], float],
    *,
    scheme: str = "moving",
    block_length: int = 21,
    n_boot: int = 10_000,
    confidence: float = 0.95,
    seed: int = 42,
    cluster_key: Callable | None = None,
) -> tuple:
    """IC bootstrap para uma estatística arbitrária sobre série temporal.

    scheme: 'iid' | 'moving' | 'stationary' | 'cluster' (ver docstring do módulo).
    block_length: tamanho do bloco (moving/stationary); ignorado em iid/cluster.
    cluster_key: OBRIGATÓRIO em scheme='cluster' — callable(unidade) -> id do cluster.
    Levanta ValueError se: scheme desconhecido; cluster sem cluster_key; ou, em
    moving/stationary, n < block_length.
    """
    if scheme not in _SCHEMES:
        raise ValueError(f"scheme desconhecido: {scheme!r} — use um de {_SCHEMES}")
    rng = random.Random(seed)
    n = len(series)
    if n == 0:
        raise ValueError("bootstrap_ci: série vazia — nada a reamostrar")

    if scheme == "cluster":
        if cluster_key is None:
            raise ValueError("scheme='cluster' exige cluster_key=callable(unidade)->id")
        groups: dict = {}
        for u in series:
            groups.setdefault(cluster_key(u), []).append(u)
        clusters = list(groups.values())
    elif scheme in ("moving", "stationary"):
        if n < block_length:
            raise ValueError(f"series length {n} < block_length {block_length}")

    boot_stats: list[float] = []
    for _ in range(n_boot):
        if scheme == "iid":
            resampled = [series[rng.randrange(n)] for _ in range(n)]
        elif scheme == "cluster":
            resampled = _resample_clusters(clusters, rng)
        else:
            resampled = _resample_blocks(series, rng, n, block_length,
                                         stationary=(scheme == "stationary"))
        stat = statistic(resampled)
        # Descarta reamostra inválida: None (Spearman sem variância) OU não-finita
        # (Sharpe/Sortino de bloco constante → ±inf/nan). nan quebra o sort() abaixo
        # (comparações com nan são False → ordem indefinida → percentil arbitrário);
        # ±inf desloca o percentil. Ambos corromperiam o IC em silêncio.
        if stat is not None and math.isfinite(stat):
            boot_stats.append(stat)

    n_valid = len(boot_stats)
    if n_valid and n_valid < 0.9 * n_boot:
        # >10% das reamostras inválidas: a distribuição ficou condicionada a um
        # subconjunto enviesado (IC mais estreito → significância fabricada). Não
        # silencie — quem consome o veredito precisa saber que ele é suspeito.
        logger.warning(
            "bootstrap_ci: %d/%d reamostras inválidas descartadas — "
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
