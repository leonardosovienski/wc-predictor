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
import warnings
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


def fit_goal_model(history, delta_xg=None):
    """Estima (a, b, alpha, rho, [theta_xg]) por maxima verossimilhanca.
    Se delta_xg for fornecido (lista com um valor por jogo), theta_xg e'
    estimado como 5o parametro.
    Retorna tupla de 4 (sem delta_xg) ou 5 (com delta_xg).
    """
    if not history:
        return (0.0, 0.3, 1e-4, 0.0)

    diffs = np.array([h[0] for h in history], dtype=float) / 400.0
    hs = np.array([h[1] for h in history], dtype=float)
    as_ = np.array([h[2] for h in history], dtype=float)
    base = math.log(max(np.r_[hs, as_].mean(), 1e-3))

    has_xg = delta_xg is not None and len(delta_xg) == len(diffs)
    if has_xg:
        dxg = np.array(delta_xg, dtype=float)
    else:
        dxg = np.zeros(len(diffs), dtype=float)

    def negll(theta):
        if len(theta) == 5:
            a, b, log_alpha, rho, theta_xg = theta
        else:
            a, b, log_alpha, rho = theta
            theta_xg = 0.0

        alpha = math.exp(log_alpha)
        lam = np.exp(a + b * diffs)
        mu = np.exp(a - b * diffs)

        lam = lam * np.exp(theta_xg * dxg)
        mu = mu * np.exp(-theta_xg * dxg)

        tau = _tau(hs, as_, lam, mu, rho)
        if np.any(tau <= 1e-12):
            return 1e12
        ll = _nb_logpmf(hs, lam, alpha) + _nb_logpmf(as_, mu, alpha) + np.log(tau)
        if not np.isfinite(ll).all():
            return 1e12
        return -float(ll.sum())

    if has_xg:
        x0 = [base, 0.3, math.log(0.1), -0.03, 0.5]
        bounds = [(-3, 3), (-1, 4), (math.log(1e-4), math.log(3)),
                  (-0.4, 0.4), (-5, 5)]
    else:
        x0 = [base, 0.3, math.log(0.1), -0.03]
        bounds = [(-3, 3), (-1, 4), (math.log(1e-4), math.log(3)), (-0.4, 0.4)]

    try:
        res = minimize(negll, x0, method="L-BFGS-B", bounds=bounds)
        if len(res.x) == 5:
            a, b, log_alpha, rho, theta_xg = res.x
        else:
            a, b, log_alpha, rho = res.x
            theta_xg = 0.0
        if not res.success and res.fun >= 1e11:
            raise ValueError("otimizacao nao convergiu para regiao valida")
        # Auditoria P10: falha de convergência ou parâmetro cravado num bound
        # indicam dado mal-formado (ex.: history no formato errado) ou modelo
        # mal-especificado. Antes isso passava calado — foi exatamente o que
        # escondeu o bug do history da Fase 2 (a=3.0 no limite, λ≈23 gols).
        if not res.success:
            warnings.warn(f"fit_goal_model: otimizacao nao convergiu ({res.message})",
                          RuntimeWarning, stacklevel=2)
        _names = ("a", "b", "log_alpha", "rho", "theta_xg")
        for name, val, (lo, hi) in zip(_names, res.x, bounds):
            if min(abs(val - lo), abs(val - hi)) < 1e-6:
                # log_alpha no bound INFERIOR e' legitimo: alpha→0 = Poisson
                # (sem overdispersao). Os demais bounds sao patologia.
                if name == "log_alpha" and abs(val - lo) < 1e-6:
                    continue
                warnings.warn(
                    f"fit_goal_model: parametro {name}={val:.4f} cravado no bound "
                    f"[{lo}, {hi}] — verifique o formato do history (diff, hs, as)",
                    RuntimeWarning, stacklevel=2)
        if has_xg:
            return (float(a), float(b), float(math.exp(log_alpha)), float(rho),
                    float(theta_xg))
        else:
            return (float(a), float(b), float(math.exp(log_alpha)), float(rho))
    except Exception:
        if has_xg:
            return (base, 0.3, 1e-4, 0.0, 0.0)
        return (base, 0.3, 1e-4, 0.0)


def _unpack_params(params: Params) -> tuple[float, float, float, float, float]:
    """Extrai (a, b, alpha, rho, theta) de tupla legada ou dict estendido.
    Aceita tupla de 4 (theta=0) ou tupla de 5 (theta no 5o elemento)."""
    if isinstance(params, dict):
        return (params["a"], params["b"], params["alpha"],
                params["rho"], params.get("theta", 0.0))
    if len(params) >= 5:
        return (params[0], params[1], params[2], params[3], params[4])
    return (params[0], params[1], params[2], params[3], 0.0)


def predict_match(elo_a: float, elo_b: float, params: Params,
                  home_adv: float = 0.0,
                  delta_vorp_a: float = 0.0,
                  delta_vorp_b: float = 0.0,
                  delta_xg: float = 0.0,
                  max_goals: int = 12,
                  seed: int | None = None) -> dict:
    """Previsão completa de uma partida.

    Link function com injeção de VORP e delta_xg (θ=0 → comportamento original):
        λ_a = exp(a + b·elo_diff/400 + θ·(delta_vorp_a + delta_xg))
        λ_b = exp(a − b·elo_diff/400 + θ·(delta_vorp_b − delta_xg))

    seed: se fornecido, cria um RNG determinístico para amostragem interna —
          torna o resultado reproduzível em testes unitários.
    """
    a, b, alpha, rho, theta = _unpack_params(params)
    diff  = (elo_a + home_adv - elo_b) / 400.0
    lam_a = math.exp(a + b * diff + theta * (delta_vorp_a + delta_xg))
    lam_b = math.exp(a - b * diff + theta * (delta_vorp_b - delta_xg))

    grid = _score_grid(lam_a, lam_b, alpha, rho, max_goals)
    return {"lambda_a": lam_a, "lambda_b": lam_b, "total_goals": lam_a + lam_b,
            **_grid_stats(grid, max_goals)}


def _score_grid(lam_a, lam_b, alpha, rho, max_goals):
    """Grid de probabilidade P(gols_a=i, gols_b=j) — NB + correção Dixon-Coles
    nas quatro células de placar baixo. Fatorado de `predict_match` pra ser
    reaproveitado por `predict_remaining` com lambdas escalados."""
    k = np.arange(max_goals + 1)
    r = 1.0 / max(alpha, 1e-9)
    pa = nbinom.pmf(k, r, r / (r + lam_a))
    pb = nbinom.pmf(k, r, r / (r + lam_b))
    grid = np.outer(pa, pb)

    grid[0, 0] *= 1.0 - lam_a * lam_b * rho
    grid[0, 1] *= 1.0 + lam_a * rho
    grid[1, 0] *= 1.0 + lam_b * rho
    grid[1, 1] *= 1.0 - rho
    grid = np.clip(grid, 0.0, None)
    grid /= grid.sum()
    return grid


def _grid_stats(grid, max_goals):
    """p_win/draw/loss, over/btts e top-5 placares a partir de um grid já
    pronto — mesma leitura pra `predict_match` (placar final) e
    `predict_remaining` (gols do tempo restante, não placar final)."""
    k = np.arange(max_goals + 1)
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
        "p_win": p_win, "p_draw": p_draw, "p_loss": p_loss,
        "over": over, "btts": btts, "top_scores": top,
        "grid": grid,   # exposto para o simulador amostrar placares
    }


def predict_remaining(elo_a: float, elo_b: float, params: Params,
                      home_adv: float = 0.0, fraction: float = 0.5,
                      max_goals: int = 12) -> dict:
    """Distribuição de gols só do tempo RESTANTE de um jogo em andamento —
    mesma link function do `predict_match`, com os λ pré-jogo escalados por
    `fraction` (0.5 = um tempo inteiro de 45min).

    HIPÓTESE NÃO CALIBRADA: assume taxa de gol constante ao longo dos 90min
    (mesma simplificação que Dixon-Coles original usa). Sem dado de minuto
    de gol no projeto, não dá pra checar se o 2o tempo tem taxa maior — na
    prática, times cansam e fazem mais gol depois dos 60min, então isto
    provavelmente subestima o tempo restante. Sem CLV validado (não existe
    mercado ao vivo no backtest) — ver docs/HYPERPARAMETERS.md.

    Os p_win/p_draw/p_loss e top_scores devolvidos são do TEMPO RESTANTE,
    não do placar final — some ao placar atual pra projetar o jogo inteiro."""
    a, b, alpha, rho, _theta = _unpack_params(params)
    diff = (elo_a + home_adv - elo_b) / 400.0
    lam_a = math.exp(a + b * diff) * fraction
    lam_b = math.exp(a - b * diff) * fraction

    grid = _score_grid(lam_a, lam_b, alpha, rho, max_goals)
    return {"lambda_a": lam_a, "lambda_b": lam_b, "total_goals": lam_a + lam_b,
            **_grid_stats(grid, max_goals)}