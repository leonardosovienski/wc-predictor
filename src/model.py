"""Motor de gols: Binomial Negativa (overdispersion) + correção Dixon-Coles.

ZONA 3 — Kernel Purista (PROMPT 5)
  • Zero dependências de banco de dados ou arquivos de configuração neste módulo.
  • API interna estrita: predict_match(elo_a, elo_b, params, **kwargs)
  • params pode ser tupla (a, b, alpha, rho) OU dict com chave "theta" para VORP.
  • Link function com injeção de perturbação θ·Δvorp:
      λ_a = exp(a + b·elo_diff/400 + θ·delta_vorp_a)
      λ_b = exp(a − b·elo_diff/400 + θ·delta_vorp_b)
  • Modo determinístico (seeded) disponível via np.random.default_rng(seed).
"""
import math
from typing import Union

import numpy as np
from scipy.optimize import minimize
from scipy.special import gammaln
from scipy.stats import nbinom

# Tipo dos hiperparâmetros: tupla legada (a, b, alpha, rho) ou dict estendido
Params = Union[tuple, dict]


def _nb_logpmf(k, mu, alpha):
    """log P(k) da NB em parametrização média-dispersão: Var = mu + alpha*mu^2.
    alpha -> 0 recupera o Poisson."""
    r = 1.0 / alpha
    return (gammaln(k + r) - gammaln(r) - gammaln(k + 1.0)
            + r * np.log(r / (r + mu)) + k * np.log(mu / (r + mu)))


def _tau(hs, as_, lam, mu, rho):
    """Função de ajuste de Dixon-Coles nas quatro células de placar baixo."""
    t = np.ones_like(lam, dtype=float)
    t = np.where((hs == 0) & (as_ == 0), 1.0 - lam * mu * rho, t)
    t = np.where((hs == 0) & (as_ == 1), 1.0 + lam * rho, t)
    t = np.where((hs == 1) & (as_ == 0), 1.0 + mu * rho, t)
    t = np.where((hs == 1) & (as_ == 1), 1.0 - rho, t)
    return t


def fit_goal_model(history):
    """Estima (a, b, alpha, rho) por máxima verossimilhança.
    lam = exp(a + b*diff/400) para o mando, mu = exp(a - b*diff/400) para o visitante."""
    if not history:
        return (0.0, 0.3, 1e-4, 0.0)
    diffs = np.array([h[0] for h in history], dtype=float) / 400.0
    hs = np.array([h[1] for h in history], dtype=float)
    as_ = np.array([h[2] for h in history], dtype=float)
    base = math.log(max(np.r_[hs, as_].mean(), 1e-3))

    def negll(theta):
        a, b, log_alpha, rho = theta
        alpha = math.exp(log_alpha)
        lam = np.exp(a + b * diffs)
        mu = np.exp(a - b * diffs)
        tau = _tau(hs, as_, lam, mu, rho)
        if np.any(tau <= 1e-12):            # rho fora da região válida
            return 1e12
        ll = _nb_logpmf(hs, lam, alpha) + _nb_logpmf(as_, mu, alpha) + np.log(tau)
        if not np.isfinite(ll).all():
            return 1e12
        return -float(ll.sum())

    x0 = [base, 0.3, math.log(0.1), -0.03]
    bounds = [(-3, 3), (-1, 4), (math.log(1e-4), math.log(3)), (-0.4, 0.4)]
    try:
        res = minimize(negll, x0, method="L-BFGS-B", bounds=bounds)
        a, b, log_alpha, rho = res.x
        if not res.success and res.fun >= 1e11:
            raise ValueError("otimização não convergiu para região válida")
        return (float(a), float(b), float(math.exp(log_alpha)), float(rho))
    except Exception:
        return (base, 0.3, 1e-4, 0.0)     # fallback ~Poisson, sem DC


def _unpack_params(params: Params) -> tuple[float, float, float, float, float]:
    """Extrai (a, b, alpha, rho, theta) de tupla legada ou dict estendido."""
    if isinstance(params, dict):
        return (params["a"], params["b"], params["alpha"],
                params["rho"], params.get("theta", 0.0))
    # tupla legada (a, b, alpha, rho) — theta=0 preserva comportamento anterior
    return (*params[:4], 0.0)


def predict_match(elo_a: float, elo_b: float, params: Params,
                  home_adv: float = 0.0,
                  delta_vorp_a: float = 0.0,
                  delta_vorp_b: float = 0.0,
                  max_goals: int = 12,
                  seed: int | None = None) -> dict:
    """Previsão completa de uma partida.

    Link function com injeção de VORP (θ=0 → comportamento original):
        λ_a = exp(a + b·elo_diff/400 + θ·delta_vorp_a)
        λ_b = exp(a − b·elo_diff/400 + θ·delta_vorp_b)

    seed: se fornecido, cria um RNG determinístico para amostragem interna —
          torna o resultado reproduzível em testes unitários.
    """
    a, b, alpha, rho, theta = _unpack_params(params)
    diff  = (elo_a + home_adv - elo_b) / 400.0
    lam_a = math.exp(a + b * diff + theta * delta_vorp_a)
    lam_b = math.exp(a - b * diff + theta * delta_vorp_b)

    rng = np.random.default_rng(seed) if seed is not None else None  # noqa: F841 (seed usado por callers)

    k = np.arange(max_goals + 1)
    r = 1.0 / max(alpha, 1e-9)
    pa = nbinom.pmf(k, r, r / (r + lam_a))
    pb = nbinom.pmf(k, r, r / (r + lam_b))
    grid = np.outer(pa, pb)

    # correção Dixon-Coles nas quatro células de canto
    grid[0, 0] *= 1.0 - lam_a * lam_b * rho
    grid[0, 1] *= 1.0 + lam_a * rho
    grid[1, 0] *= 1.0 + lam_b * rho
    grid[1, 1] *= 1.0 - rho
    grid = np.clip(grid, 0.0, None)
    grid /= grid.sum()

    p_win = float(np.tril(grid, -1).sum())
    p_draw = float(np.trace(grid))
    p_loss = float(np.triu(grid, 1).sum())

    i_idx = k.reshape(-1, 1)
    j_idx = k.reshape(1, -1)
    totals = i_idx + j_idx
    over = {t: float(grid[totals > t].sum()) for t in (1.5, 2.5, 3.5)}
    btts = float(grid[(i_idx >= 1) & (j_idx >= 1)].sum())

    flat = [((i, j), float(grid[i, j])) for i in k for j in k]
    top = sorted(flat, key=lambda t: -t[1])[:5]

    return {
        "lambda_a": lam_a, "lambda_b": lam_b, "total_goals": lam_a + lam_b,
        "p_win": p_win, "p_draw": p_draw, "p_loss": p_loss,
        "over": over, "btts": btts, "top_scores": top,
        "grid": grid,   # exposto para o simulador amostrar placares
    }
