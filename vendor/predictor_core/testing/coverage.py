"""coverage — teste de cobertura de IC: a régua se valida por COMPORTAMENTO.

Gera N séries AR(1) com média verdadeira conhecida, calcula o IC de `confidence` via
`bootstrap_func` para cada uma, e mede a fração em que o IC cobre a verdade. Um IC 95%
correto cobre em 95%±tolerance. Um bootstrap com a geometria de blocos errada (ou
i.i.d. aplicado a dado autocorrelacionado) SUB-COBRE de forma detectável — é assim que
regressões silenciosas na Lente 2 são pegas, sem ler o código.
"""
from predictor_core.testing.synth import ar1_series


def _mean(u):
    return sum(u) / len(u)


def bootstrap_coverage(bootstrap_func, scheme, statistic_func=_mean, *,
                       n_series: int = 500, n_points: int = 200, phi: float = 0.0,
                       sigma: float = 1.0, mu: float = 0.0, block_length: int = 20,
                       n_boot: int = 300, confidence: float = 0.95,
                       seed: int = 0) -> float:
    """Fração das `n_series` cujo IC (via bootstrap_func/scheme) cobre a média verdadeira mu.

    Para scheme='cluster', cada observação vira um cluster singleton (unidade = (valor,
    índice); cluster_key = índice) — degenera no i.i.d., como esperado para dado sem
    estrutura de grupo. Determinístico dado `seed`. Retorna a cobertura observada."""
    covered = 0
    for s in range(n_series):
        series = ar1_series(n_points, phi, sigma, seed=seed * 1_000_003 + s, mu=mu)
        if scheme == "cluster":
            units = list(enumerate(series))   # (índice, valor)
            lo, hi, _ = bootstrap_func(
                units, lambda u: statistic_func([v for _i, v in u]),
                scheme="cluster", cluster_key=lambda t: t[0],
                n_boot=n_boot, confidence=confidence, seed=s + 1)
        else:
            lo, hi, _ = bootstrap_func(
                series, statistic_func, scheme=scheme, block_length=block_length,
                n_boot=n_boot, confidence=confidence, seed=s + 1)
        if lo is not None and lo <= mu <= hi:
            covered += 1
    return covered / n_series


def coverage_in_band(bootstrap_func, scheme, statistic_func=_mean, *,
                     n_series: int = 500, n_points: int = 200, phi: float = 0.0,
                     sigma: float = 1.0, mu: float = 0.0, block_length: int = 20,
                     n_boot: int = 300, confidence: float = 0.95,
                     tolerance: float = 0.02, seed: int = 0) -> bool:
    """True se a cobertura observada estiver em [confidence-tolerance, confidence+tolerance].

    NOTA DE NOME: NÃO se chama `test_*` de propósito — um nome com prefixo `test_` num
    módulo de biblioteca é coletado pelo pytest como teste (com erro por falta de args)
    em qualquer suíte que o importe. `coverage_in_band` é seguro para os domínios usarem.

    Wrapper de veredito sobre `bootstrap_coverage`. Use `phi=0` para validar o esquema
    i.i.d./cluster; `phi>0` para os esquemas de bloco (moving/stationary), que devem
    recuperar a variância inflada pela autocorrelação."""
    cov = bootstrap_coverage(
        bootstrap_func, scheme, statistic_func, n_series=n_series, n_points=n_points,
        phi=phi, sigma=sigma, mu=mu, block_length=block_length, n_boot=n_boot,
        confidence=confidence, seed=seed)
    return (confidence - tolerance) <= cov <= (confidence + tolerance)
