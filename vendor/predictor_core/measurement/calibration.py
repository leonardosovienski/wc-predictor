"""predictor-core.measurement.calibration — calibração Platt + Shin de-vig (Onda 2, v1.3.0).

Decoradores matemáticos PUROS: recebem probabilidades, devolvem probabilidades
ajustadas. O core NÃO os acopla ao PredictionPoint — o LoL refutou o Platt e o
CS o comprovou (trials registradas), então calibrar ou não é decisão de
domínio, tomada na última milha do consumidor (imediatamente antes de gravar no
SQLite dele). O core só garante a matemática.

  PlattCalibrator — regressão logística 1D (Platt 1999): aprende (a, b) tal que
                    p_cal = sigmoid(a·logit(p) + b) sobre pares (p_prevista,
                    resultado). Fit por gradiente (stdlib puro), determinístico.
  shin_devig      — remove a margem do bookmaker pelo método de Shin (1993):
                    modela a margem como proporção z de insider trading, resolve
                    z por bisseção e devolve probabilidades que somam 1. Superior
                    à normalização proporcional para favoritos-azarões (corrige o
                    favourite-longshot bias que a divisão simples ignora).
"""
from __future__ import annotations

import math

__all__ = ["PlattCalibrator", "shin_devig"]


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def _logit(p: float, eps: float = 1e-12) -> float:
    p = min(max(p, eps), 1.0 - eps)
    return math.log(p / (1.0 - p))


class PlattCalibrator:
    """Calibração de Platt: p_cal = sigmoid(a·logit(p) + b).

    cal = PlattCalibrator().fit(probs, outcomes)   # outcomes: 0/1
    cal.transform(novas_probs)                      # ou cal(novas_probs)

    Fit por gradiente descendente full-batch na log-loss (stdlib, determinístico
    — sem seed porque não há aleatoriedade). Identidade inicial (a=1, b=0):
    se os dados já são calibrados, o fit fica perto do neutro."""

    def __init__(self, lr: float = 0.1, iterations: int = 2000):
        self.lr = lr
        self.iterations = iterations
        self.a = 1.0
        self.b = 0.0
        self._fitted = False

    def fit(self, probs: list, outcomes: list) -> "PlattCalibrator":
        if len(probs) != len(outcomes) or not probs:
            raise ValueError("probs e outcomes devem ser não-vazios e do mesmo tamanho")
        xs = [_logit(p) for p in probs]
        n = len(xs)
        a, b = 1.0, 0.0
        for _ in range(self.iterations):
            ga = gb = 0.0
            for x, y in zip(xs, outcomes):
                err = _sigmoid(a * x + b) - y   # gradiente da log-loss
                ga += err * x
                gb += err
            a -= self.lr * ga / n
            b -= self.lr * gb / n
        self.a, self.b = a, b
        self._fitted = True
        return self

    def transform(self, probs: list) -> list:
        if not self._fitted:
            raise RuntimeError("PlattCalibrator não foi ajustado — chame fit() antes")
        return [_sigmoid(self.a * _logit(p) + self.b) for p in probs]

    def __call__(self, probs: list) -> list:
        return self.transform(probs)


def shin_devig(implied_probs: list, *, tol: float = 1e-10,
               max_iter: int = 200) -> list:
    """Remove a margem (vig) de probabilidades implícitas de odds pelo método
    de Shin (1993).

    `implied_probs`: 1/odds_decimais por resultado (soma > 1 pela margem).
    Modelo: booksum π_i = margem oriunda de proporção z de insiders;
    p_i = (sqrt(z² + 4(1-z)·π_i²/Σπ) - z) / (2(1-z)). Resolve z por bisseção
    até Σp = 1. Com Σπ <= 1 (sem margem), devolve normalização proporcional.
    Retorna probabilidades limpas somando 1, mesma ordem da entrada."""
    if len(implied_probs) < 2:
        raise ValueError("shin_devig exige >= 2 resultados")
    if any(p <= 0 for p in implied_probs):
        raise ValueError("probabilidades implícitas devem ser > 0")
    booksum = sum(implied_probs)
    if booksum <= 1.0 + tol:
        return [p / booksum for p in implied_probs]

    def total(z: float) -> float:
        return sum(
            (math.sqrt(z * z + 4.0 * (1.0 - z) * p * p / booksum) - z) / (2.0 * (1.0 - z))
            for p in implied_probs)

    lo, hi = 0.0, 1.0 - 1e-12   # total(0) = Σπ²... > pode ser <1; bisseção em z
    # total é decrescente em z; achar z com total(z) = 1
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        t = total(mid)
        if abs(t - 1.0) < tol:
            break
        if t > 1.0:
            lo = mid
        else:
            hi = mid
    z = (lo + hi) / 2.0
    probs = [(math.sqrt(z * z + 4.0 * (1.0 - z) * p * p / booksum) - z)
             / (2.0 * (1.0 - z)) for p in implied_probs]
    s = sum(probs)   # resíduo numérico da bisseção
    return [p / s for p in probs]
