"""Utilidades matemáticas externas ao motor (aqui scipy é aceitável).

Método de Shin (1992/93): remove o overround das odds estimando z, a fração de
dinheiro informado. Corrige o favorite-longshot bias melhor que a normalização
proporcional — a casa carrega margem desigual entre favorito e azarão.
"""
import numpy as np
from scipy.optimize import brentq


def implied_probabilities(odds):
    return np.array([1.0 / o for o in odds], dtype=float)


def shin_probabilities(odds):
    """Probabilidades reais de mercado por Shin. Retorna (probs, z, overround)."""
    pi = implied_probabilities(odds)
    booksum = float(pi.sum())
    if booksum <= 1.0:                       # sem margem detectável
        return pi / booksum, 0.0, booksum - 1.0

    def p_of_z(z):
        return (np.sqrt(z * z + 4 * (1 - z) * pi * pi / booksum) - z) / (2 * (1 - z))

    try:
        z = brentq(lambda z: p_of_z(z).sum() - 1.0, 1e-9, 1 - 1e-9, xtol=1e-12)
    except ValueError:
        z = 0.0
    p = p_of_z(z) if z > 0 else pi / booksum
    p = p / p.sum()
    return p, float(z), float(booksum - 1.0)
