"""score_metrics — métricas de score probabilístico ESPECÍFICAS do domínio futebol.

Extraídas de `vendor/predictor_core/stats.py` no de-fork de 2026-06: estas funções
operam sobre tensores de placar (N, G, G) e são lógica de domínio do wc-predictor —
NÃO pertencem ao predictor_core (que é agnóstico a domínio). Viviam na cópia
vendorizada por um fork manual, quebrando a regra de escrita unidirecional do core.

`probabilistic_sharpe_ratio`, `block_bootstrap_ci` etc. continuam vindo do core.
"""
import numpy as np

# ---------------------------------------------------------------------------
# Métricas de Score Probabilístico (vetorizadas, zero loops Python)
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
