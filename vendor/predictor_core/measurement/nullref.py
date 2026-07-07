"""nullref — distribuição de referência NULA (a 3ª lente do pedágio).

Pergunta: "seu seletor está na cauda da distribuição de seletores ALEATÓRIOS de mesmo
tamanho e turnover?" Se um stock-picker (ou apostador, ou modelo) não bate carteiras
sorteadas com as MESMAS restrições, o desempenho é sorte, não skill. Complementa o PSR
(Lente 1) e o bootstrap (Lente 2): elas medem significância da série; esta mede se a
SELEÇÃO em si carrega informação além do acaso.

Especificado no DESIGN do predictor-stocks (§10 M5): "carteiras aleatórias com o MESMO
turnover e MESMO número de posições do modelo — o modelo precisa estar na cauda dela".
Funções puras, determinísticas por seed, stdlib.
"""
import math
import random


def random_portfolio_sequence(universe, n_positions: int, n_periods: int,
                              turnover: float, seed: int) -> list[list]:
    """Sequência de `n_periods` carteiras aleatórias com turnover CONTROLADO.

    Cada carteira mantém round((1-turnover)·n_positions) nomes da anterior e substitui o
    resto por sorteio do resto do universo — reproduzindo o turnover do modelo (uma
    carteira que gira 100% ao mês não se compara a uma buy-and-hold aleatória). Retorna
    lista de listas ordenadas (determinística). turnover em [0, 1]."""
    universe = list(universe)
    if not (0.0 <= turnover <= 1.0):
        raise ValueError("turnover deve estar em [0, 1]")
    if not (0 < n_positions <= len(universe)):
        raise ValueError(f"n_positions ({n_positions}) deve estar em (0, |universe|={len(universe)}]")
    rng = random.Random(seed)
    n_keep = round((1.0 - turnover) * n_positions)
    n_replace = n_positions - n_keep
    # Garantia EXATA de turnover: os novos nomes vêm de (universo − carteira atual), não
    # de (universo − mantidos) — senão um sorteado poderia coincidir com um descartado e
    # o turnover realizado seria MENOR que o pedido. Isso exige universo grande o bastante.
    if n_replace > len(universe) - n_positions:
        raise ValueError(
            f"universo pequeno demais para turnover exato: precisa de "
            f"{n_positions + n_replace} nomes, tem {len(universe)} — reduza turnover ou n_positions")
    seqs: list[list] = []
    current = rng.sample(universe, n_positions)
    seqs.append(sorted(current))
    for _ in range(1, n_periods):
        kept = rng.sample(current, n_keep) if n_keep else []
        held = set(current)
        pool = [u for u in universe if u not in held]      # nomes NÃO detidos
        new = rng.sample(pool, n_replace) if n_replace else []
        current = kept + new
        seqs.append(sorted(current))
    return seqs


def null_distribution(statistic, universe, n_positions: int, *,
                      n_samples: int = 1000, seed: int = 0) -> list[float]:
    """Distribuição nula ORDENADA de `statistic` sobre seleções aleatórias.

    Sorteia `n_samples` subconjuntos de `n_positions` itens de `universe` e aplica
    `statistic(selection) -> float`. Reamostras com stat None/não-finita são descartadas
    (mesma disciplina do bootstrap). É o denominador de `tail_probability`."""
    universe = list(universe)
    if not (0 < n_positions <= len(universe)):
        raise ValueError(f"n_positions ({n_positions}) deve estar em (0, |universe|={len(universe)}]")
    rng = random.Random(seed)
    out = []
    for _ in range(n_samples):
        sel = rng.sample(universe, n_positions)
        s = statistic(sel)
        if s is not None and math.isfinite(s):
            out.append(s)
    out.sort()
    return out


def tail_probability(observed: float, null_dist: list[float], side: str = "upper") -> float:
    """p-valor empírico: fração da distribuição nula tão ou mais extrema que `observed`.

    side='upper' → P(nula >= observed) (o seletor está na cauda SUPERIOR? p pequeno = skill).
    side='lower' → P(nula <= observed). nan se a distribuição nula estiver vazia."""
    n = len(null_dist)
    if n == 0:
        return float("nan")
    if side == "upper":
        k = sum(1 for x in null_dist if x >= observed)
    elif side == "lower":
        k = sum(1 for x in null_dist if x <= observed)
    else:
        raise ValueError("side deve ser 'upper' ou 'lower'")
    return k / n


def percentile_of(observed: float, null_dist: list[float]) -> float:
    """Percentil (0..1) de `observed` na distribuição nula: fração <= observed."""
    n = len(null_dist)
    if n == 0:
        return float("nan")
    return sum(1 for x in null_dist if x <= observed) / n
