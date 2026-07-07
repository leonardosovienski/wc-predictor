"""predictor-core.measurement.metrics — régua PROBABILÍSTICA (genérica, stdlib pura).

A régua financeira (stats) mede retorno/risco; esta mede a QUALIDADE de previsões
probabilísticas — o que NBA, Eleições, Clima e o 1X2 do futebol precisam. É
domínio-agnóstica: opera sobre vetores de probabilidade + índice do resultado, não
sobre tensores de placar (esses são ontologia e ficam no wc-predictor).

  brier            — erro quadrático multiclasse (0 = perfeito; até 2).
  log_loss         — cross-entropy (pune confiança errada com severidade log).
  rps              — Ranked Probability Score: para resultados ORDINAIS (vitória >
                     empate > derrota; faixas de voto), pune erro de ORDENAÇÃO, não só
                     de acerto. É a métrica canônica quando as classes têm ordem.
  calibration_table — confiabilidade de um previsor binário (previsto vs observado por faixa).
  diebold_mariano  — compara dois previsores pela diferença de perda, com correção
                     Harvey-Leybourne-Newbold para amostra pequena e p-valor t-Student.

Convenção de entrada: `probs` é lista de vetores de probabilidade (cada um soma ~1);
`outcomes` é lista de índices inteiros da classe realizada. Zero dependências externas.
"""
import math

__all__ = ["brier", "log_loss", "rps", "calibration_table", "diebold_mariano"]


def _check(probs, outcomes):
    if len(probs) != len(outcomes):
        raise ValueError("probs e outcomes devem ter o mesmo tamanho")
    if not probs:
        raise ValueError("amostra vazia — nada a medir")


def brier(probs: list, outcomes: list) -> float:
    """Brier multiclasse: média_n Σ_j (p_{n,j} - onehot_j)². Varia em [0, 2]."""
    _check(probs, outcomes)
    total = 0.0
    for p, y in zip(probs, outcomes):
        s = 0.0
        for j, pj in enumerate(p):
            yj = 1.0 if j == y else 0.0
            s += (pj - yj) ** 2
        total += s
    return total / len(probs)


def log_loss(probs: list, outcomes: list, eps: float = 1e-12) -> float:
    """Log-loss (cross-entropy): média_n [-log p_{n, y_n}], com clip por eps."""
    _check(probs, outcomes)
    total = 0.0
    for p, y in zip(probs, outcomes):
        py = min(max(p[y], eps), 1.0)
        total += -math.log(py)
    return total / len(probs)


def rps(probs: list, outcomes: list) -> float:
    """Ranked Probability Score para classes ORDINAIS (ordem = índice 0,1,...,K-1).

    Por observação: (1/(K-1)) Σ_{k=0}^{K-2} (CDF_prev_k - CDF_obs_k)². Média sobre n.
    0 = perfeito. Sensível à DISTÂNCIA do erro na ordem (prever 'derrota' quando foi
    'vitória' pune mais que prever 'empate'). Exige K>=2 e mesmo K em todas as obs."""
    _check(probs, outcomes)
    k = len(probs[0])
    if k < 2:
        raise ValueError("rps exige K>=2 classes ordinais")
    total = 0.0
    for p, y in zip(probs, outcomes):
        if len(p) != k:
            raise ValueError("todas as previsões devem ter o mesmo número de classes")
        cum_p = 0.0
        acc = 0.0
        for i in range(k - 1):
            cum_p += p[i]                      # CDF prevista até a classe i
            obs_cdf = 1.0 if i >= y else 0.0   # CDF observada = degrau em y (não acumula)
            acc += (cum_p - obs_cdf) ** 2
        total += acc / (k - 1)
    return total / len(probs)


def calibration_table(probs: list, outcomes: list, bins: int = 10) -> list:
    """Tabela de confiabilidade de um previsor BINÁRIO.

    `probs`: lista de p (probabilidade da classe 1). `outcomes`: 0/1.
    Retorna lista de dicts por faixa não-vazia:
      {bin_lo, bin_hi, n, mean_pred, obs_freq} — mean_pred≈obs_freq = bem calibrado."""
    if len(probs) != len(outcomes):
        raise ValueError("probs e outcomes devem ter o mesmo tamanho")
    edges = [i / bins for i in range(bins + 1)]
    out = []
    for b in range(bins):
        lo, hi = edges[b], edges[b + 1]
        # última faixa inclui 1.0; demais são [lo, hi)
        sel = [(pp, yy) for pp, yy in zip(probs, outcomes)
               if (lo <= pp < hi) or (b == bins - 1 and pp == 1.0)]
        if not sel:
            continue
        n = len(sel)
        mean_pred = sum(pp for pp, _ in sel) / n
        obs_freq = sum(yy for _, yy in sel) / n
        out.append({"bin_lo": lo, "bin_hi": hi, "n": n,
                    "mean_pred": mean_pred, "obs_freq": obs_freq})
    return out


# --- Diebold-Mariano (comparação de previsores) ----------------------------

def _betacf(a: float, b: float, x: float) -> float:
    """Fração contínua de Lentz para a beta incompleta regularizada (Numerical Recipes)."""
    MAXIT, EPS, FPMIN = 300, 3e-14, 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < FPMIN:
        d = FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, MAXIT + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < EPS:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    """Beta incompleta regularizada I_x(a, b) ∈ [0, 1]."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(lbeta + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def _t_two_sided_p(t: float, df: float) -> float:
    """p-valor BILATERAL da t de Student: P(|T| > |t|) = I_{df/(df+t²)}(df/2, 1/2)."""
    if df <= 0:
        return float("nan")
    x = df / (df + t * t)
    return _betai(df / 2.0, 0.5, x)


def diebold_mariano(loss_a: list, loss_b: list, h: int = 1) -> tuple:
    """Teste Diebold-Mariano com correção Harvey-Leybourne-Newbold (HLN 1997).

    `loss_a`, `loss_b`: perdas POR OBSERVAÇÃO de dois previsores (ex.: Brier ou erro
    quadrático por ponto), pareadas no tempo. Diferencial d = loss_a - loss_b.
    h: horizonte (>1 inclui h-1 autocovariâncias — séries de previsão sobrepostas).

    H0: perdas iguais (E[d]=0). dm < 0 sugere A melhor (perda menor). A correção HLN
    ajusta a variância para amostra finita e usa t(n-1) em vez da normal — crítico
    para n<30. Retorna (dm_hln, p_valor_bilateral). (nan, nan) se variância nula."""
    if len(loss_a) != len(loss_b):
        raise ValueError("loss_a e loss_b devem ter o mesmo tamanho")
    n = len(loss_a)
    if n < 2:
        return float("nan"), float("nan")
    d = [a - b for a, b in zip(loss_a, loss_b)]
    d_bar = sum(d) / n
    dc = [x - d_bar for x in d]

    # autocovariâncias γ_0..γ_{h-1} (estimador populacional /n)
    def gamma(k: int) -> float:
        return sum(dc[t] * dc[t - k] for t in range(k, n)) / n

    hh = max(h, 1)
    s2 = (gamma(0) + 2.0 * sum(gamma(k) for k in range(1, hh))) / n
    if s2 <= 0.0:
        return float("nan"), float("nan")

    dm = d_bar / math.sqrt(s2)
    hln = math.sqrt((n + 1.0 - 2.0 * hh + hh * (hh - 1.0) / n) / n)
    dm_hln = dm * hln
    return dm_hln, _t_two_sided_p(dm_hln, n - 1)
