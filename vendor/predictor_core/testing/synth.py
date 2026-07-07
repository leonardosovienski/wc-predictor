"""synth — geradores de séries sintéticas com verdade conhecida (stdlib puro).

Nota stdlib-first: a spec da Onda 2 sugeriu np.ndarray/np.random.default_rng, mas o
core não pode carregar dependência externa obrigatória (o stocks é stdlib-first). Estas
funções retornam list[float] e usam random.Random(seed) — mesma semântica, sem numpy.
"""
import random


def ar1_series(n: int, phi: float, sigma: float, seed: int, mu: float = 0.0) -> list:
    """Série AR(1): x_t = mu + phi·(x_{t-1} - mu) + eps, eps ~ N(0, sigma).

    A média do PROCESSO é mu (o valor verdadeiro que um IC do estimador da média deve
    cobrir). phi controla a autocorrelação: phi=0 → ruído i.i.d.; phi→1 → forte memória
    (o caso em que o bootstrap i.i.d. subestima a variância e sub-cobre)."""
    if n <= 0:
        return []
    rng = random.Random(seed)
    x = mu + rng.gauss(0.0, sigma)          # estacionário: inicia perto da média
    out = [x]
    for _ in range(1, n):
        x = mu + phi * (x - mu) + rng.gauss(0.0, sigma)
        out.append(x)
    return out


def edge_injected(base_series: list, edge_magnitude: float,
                  positions=None, seed: int | None = None) -> list:
    """Copia `base_series` somando `edge_magnitude` nas `positions` (default: todas).

    Produz uma série cuja média verdadeira desloca de forma CONHECIDA — o sinal que um
    pipeline com poder deve detectar. `seed` reservado para variações estocásticas
    futuras do edge; hoje a injeção é determinística."""
    out = list(base_series)
    idx = range(len(out)) if positions is None else positions
    for i in idx:
        if 0 <= i < len(out):
            out[i] += edge_magnitude
    return out


def probabilistic_predictor(n: int, skill_level: float, seed: int,
                            n_classes: int = 3) -> tuple:
    """Previsor probabilístico sintético com skill CALIBRÁVEL em [0, 1].

    skill_level=0 → previsões uniformes (1/K, sem informação); skill_level=1 → one-hot
    na classe verdadeira (perfeito). Interpola linearmente: a massa na classe correta é
    1/K + skill·(1 - 1/K), o resto dividido igualmente. Resultados sorteados uniformes.
    Retorna (probs, outcomes): probs = lista de vetores (soma 1); outcomes = índices."""
    if not (0.0 <= skill_level <= 1.0):
        raise ValueError("skill_level deve estar em [0, 1]")
    if n_classes < 2:
        raise ValueError("n_classes >= 2")
    rng = random.Random(seed)
    base = 1.0 / n_classes
    p_true = base + skill_level * (1.0 - base)
    p_other = (1.0 - p_true) / (n_classes - 1)
    probs, outcomes = [], []
    for _ in range(n):
        y = rng.randrange(n_classes)
        vec = [p_other] * n_classes
        vec[y] = p_true
        probs.append(vec)
        outcomes.append(y)
    return probs, outcomes
