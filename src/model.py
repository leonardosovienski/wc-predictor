"""Motor de gols: Binomial Negativa (overdispersion) + correção Dixon-Coles.

A base é Negative Binomial em vez de Poisson: gols de seleção têm variância > média
(goleadas de Copa), e o parâmetro de dispersão alpha engorda a cauda sem distorcer
os placares comuns. Sobre ela, a correção de Dixon-Coles (rho) ajusta as quatro
células de placar baixo, devolvendo a massa de empate que a independência subestima.

Calibração por MLE dos quatro parâmetros (a, b, alpha, rho) via scipy. O Newton
manual de 2 parâmetros não escala para isso — a verossimilhança da NB carrega
termos gamma e o rho tem região de validade (tau > 0). A resiliência vem de:
otimizador robusto, região inválida penalizada na própria objetivo, e fallback.
"""
import math

import numpy as np
from scipy.optimize import minimize
from scipy.special import gammaln
from scipy.stats import nbinom


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


def predict_match(elo_a: float, elo_b: float, params, home_adv: float = 0.0,
                  max_goals: int = 12) -> dict:
    a, b, alpha, rho = params
    diff = (elo_a + home_adv - elo_b) / 400.0
    lam_a = math.exp(a + b * diff)
    lam_b = math.exp(a - b * diff)

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
