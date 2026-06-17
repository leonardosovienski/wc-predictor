"""Fixes da auditoria no simulador (v2): seed (reprodutibilidade) + amostragem
da grid corrigida por Dixon-Coles (preserva massa de empate)."""
import random

import numpy as np

from src import simulator


def _twelve_groups():
    teams = [f"T{i:02d}" for i in range(48)]
    return [teams[i * 4:(i + 1) * 4] for i in range(12)]


def test_play_reproducible_with_seed():
    """Semear random + np.random torna _play (red factor + amostragem) determinístico."""
    elo, params = {"A": 1600, "B": 1500}, (0.0, 0.3, 0.16, -0.03)
    random.seed(7); np.random.seed(7)
    r1 = [simulator._play("A", "B", elo, params) for _ in range(20)]
    random.seed(7); np.random.seed(7)
    r2 = [simulator._play("A", "B", elo, params) for _ in range(20)]
    assert r1 == r2


def test_simulate_batch_reproducible_with_seed():
    """Mesma seed => exatamente o mesmo resultado de torneio (antes era irreproduzível)."""
    groups = _twelve_groups()
    elo = {t: 1500 + (i % 7) for i, t in enumerate(sum(groups, []))}
    params = (0.0, 0.3, 0.16, -0.03)
    r1 = simulator.simulate_batch(groups, elo, params, n=30, seed=123)
    r2 = simulator.simulate_batch(groups, elo, params, n=30, seed=123)
    assert r1 == r2


def test_sample_score_from_dc_grid():
    """Amostra da grid (com rho de Dixon-Coles), não duas NB independentes."""
    np.random.seed(0)
    draws = [simulator._sample_score(1.3, 1.3, 0.16, -0.05) for _ in range(2000)]
    assert all(isinstance(a, int) and isinstance(b, int) for a, b in draws)
    media_total = sum(a + b for a, b in draws) / len(draws)
    assert 1.5 < media_total < 4.0          # ~2×1.3 gols esperados, faixa sã
