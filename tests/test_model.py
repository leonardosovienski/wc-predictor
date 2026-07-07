"""Assíntota do motor: a Binomial Negativa com dispersão α→0 (e sem correção
Dixon-Coles, rho=0) tem que colapsar na Poisson clássica. É o teste que prova
que o embasamento estatístico está correto, não só calibrado."""
import numpy as np
from scipy.stats import poisson

from src.model import predict_match, predict_remaining


def test_nb_colapsa_em_poisson_quando_alpha_zero():
    # rho=0 desliga a correção nos cantos; α→0 zera a sobredispersão.
    # O grid bivariado tem que ser o produto externo de duas Poissons puras.
    a, b = 0.2, 1.0
    params = (a, b, 1e-9, 0.0)
    elo_a, elo_b, adv, mg = 1900.0, 1750.0, 0.0, 12
    r = predict_match(elo_a, elo_b, params, adv, mg)

    diff = (elo_a - elo_b) / 400.0
    lam_a = np.exp(a + b * diff)
    lam_b = np.exp(a - b * diff)
    k = np.arange(mg + 1)
    expected = np.outer(poisson.pmf(k, lam_a), poisson.pmf(k, lam_b))
    expected /= expected.sum()

    np.testing.assert_allclose(r["grid"], expected, atol=1e-6)


def test_probabilidades_1x2_somam_um():
    r = predict_match(1850.0, 1850.0, (0.2, 1.0, 0.1, 0.05), 0.0, 12)
    assert abs(r["p_win"] + r["p_draw"] + r["p_loss"] - 1.0) < 1e-9


def test_mando_favorece_o_mandante():
    # mesmo Elo, com vantagem de mando → p_win > p_loss.
    r = predict_match(1800.0, 1800.0, (0.2, 1.0, 0.1, 0.05), home_adv=80.0)
    assert r["p_win"] > r["p_loss"]


def test_predict_remaining_fraction_1_bate_com_predict_match():
    # fraction=1.0 (jogo inteiro) tem que reproduzir o predict_match original
    # (mesmos lambdas, mesmo grid) — é o mesmo link function, só escalado.
    params = (0.2, 1.0, 0.1, 0.05)
    full = predict_match(1850.0, 1750.0, params, home_adv=60.0)
    rem = predict_remaining(1850.0, 1750.0, params, home_adv=60.0, fraction=1.0)
    assert abs(rem["lambda_a"] - full["lambda_a"]) < 1e-9
    assert abs(rem["lambda_b"] - full["lambda_b"]) < 1e-9
    np.testing.assert_allclose(rem["grid"], full["grid"], atol=1e-9)


def test_predict_remaining_fraction_meio_escala_lambda_pela_metade():
    params = (0.2, 1.0, 0.1, 0.05)
    full = predict_match(1850.0, 1750.0, params, home_adv=0.0)
    metade = predict_remaining(1850.0, 1750.0, params, home_adv=0.0, fraction=0.5)
    assert abs(metade["lambda_a"] - full["lambda_a"] / 2.0) < 1e-9
    assert abs(metade["lambda_b"] - full["lambda_b"] / 2.0) < 1e-9


def test_predict_remaining_grid_soma_um():
    r = predict_remaining(1850.0, 1750.0, (0.2, 1.0, 0.1, 0.05), fraction=0.5)
    assert abs(r["grid"].sum() - 1.0) < 1e-9
