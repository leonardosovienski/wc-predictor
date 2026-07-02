import pytest
import numpy as np
from src.model import fit_goal_model, predict_match


# AUDITORIA P1: o fixture antigo usava [elo_home, elo_away, hs, as] — formato
# ERRADO que este teste canonizou e a Fase 2 copiou (o MLE tratava o Elo do
# visitante como gols do mandante). O contrato real de fit_goal_model é
# (elo_diff, home_goals, away_goals) — ver ratings.compute_ratings.
_HISTORY = [
    (200, 2, 1),
    (100, 3, 0),
    (-100, 1, 2),
    (-200, 0, 1),
    (300, 4, 0),
]


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
def test_fit_without_xg():
    """Backward compatibility: sem delta_xg, retorna 4 parametros.
    (n=5 e' fixture-brinquedo: rho pode cravar no bound e o warning P10
    dispara legitimamente — aqui so interessa a forma do retorno.)"""
    params = fit_goal_model(_HISTORY)
    assert len(params) == 4
    a, b, alpha, rho = params
    assert alpha > 0
    assert -0.4 <= rho <= 0.4


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
def test_fit_with_xg():
    """Com delta_xg, retorna 5 parametros e theta_xg != 0."""
    history = list(_HISTORY)
    delta_xg = [1.5, 2.0, -1.5, -2.0, 2.5]
    params = fit_goal_model(history, delta_xg=delta_xg)
    assert len(params) == 5
    a, b, alpha, rho, theta_xg = params
    assert alpha > 0
    assert theta_xg != 0.0  # deve capturar o sinal do delta_xg


def test_predict_with_xg():
    """predict_match com delta_xg altera as probabilidades."""
    params = (0.2, 0.8, 0.15, -0.03, 0.5)  # a, b, alpha, rho, theta
    pred_flat = predict_match(1800, 1600, params, delta_xg=0.0)
    pred_xg = predict_match(1800, 1600, params, delta_xg=2.0)
    # Com delta_xg positivo, o time da casa deve ter mais chances
    assert pred_xg['p_win'] > pred_flat['p_win']


def test_predict_without_xg():
    """predict_match sem delta_xg mantem comportamento original."""
    params = (0.2, 0.8, 0.15, -0.03)
    pred = predict_match(1800, 1600, params)
    assert 0 < pred['p_win'] < 1
    assert abs(pred['p_win'] + pred['p_draw'] + pred['p_loss'] - 1.0) < 0.001