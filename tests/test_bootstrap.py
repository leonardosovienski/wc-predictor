"""Gap #4 da auditoria: ci_mean — propriedades do IC percentílico que sustentam
a Hipótese #1 (o veredito CONFIRMADA/REFUTADA/INCONCLUSIVA é decidido por esta
função). Funções puras, sem I/O."""
import numpy as np
import pytest

from src.bootstrap import ci_mean


def test_ic_contem_a_media_amostral():
    rng = np.random.default_rng(13)
    mean, lo, hi = ci_mean([1.0, 2.0, 3.0, 4.0, 5.0], 1000, rng)
    assert mean == 3.0
    assert lo <= mean <= hi


def test_amostra_constante_colapsa_o_ic():
    # reamostrar constantes só produz constantes: IC degenera no ponto.
    rng = np.random.default_rng(13)
    mean, lo, hi = ci_mean([0.07] * 20, 1000, rng)
    assert mean == lo == hi == pytest.approx(0.07)


def test_n_igual_a_1_nao_estoura():
    rng = np.random.default_rng(13)
    mean, lo, hi = ci_mean([-0.04], 1000, rng)
    assert mean == lo == hi == pytest.approx(-0.04)


def test_determinismo_sob_seed_fixa():
    # mesma seed ⇒ mesmo IC, bit a bit — pré-registro reproduzível.
    a = ci_mean([0.1, -0.2, 0.3, 0.05], 1000, np.random.default_rng(13))
    b = ci_mean([0.1, -0.2, 0.3, 0.05], 1000, np.random.default_rng(13))
    assert a == b


def test_seeds_diferentes_divergem():
    # contraprova do determinismo: o IC depende mesmo da seed (a média não).
    # Amostra grande: com n=4 o espaço de reamostragem é discreto demais e os
    # percentis de seeds diferentes coincidem (visto na primeira rodada).
    pop = np.random.default_rng(7).normal(0.05, 0.10, size=60).tolist()
    a = ci_mean(pop, 1000, np.random.default_rng(13))
    b = ci_mean(pop, 1000, np.random.default_rng(99))
    assert a[0] == b[0]
    assert (a[1], a[2]) != (b[1], b[2])


def test_amostra_vazia_estoura_em_voz_alta():
    # achado da auditoria: ci_mean([]) devolvia (nan, nan, nan) calado —
    # size=(it, 0) fazia o numpy pular a validação de low<high. NaN silencioso
    # no veredito da Hipótese #1 é pior que exceção; agora a entrada vazia
    # estoura explicitamente e o chamador guarda (como _row já faz com n<2).
    with pytest.raises(ValueError):
        ci_mean([], 1000, np.random.default_rng(13))


def test_ic_ordenado_e_estreita_com_n():
    # lo <= hi sempre; e o IC de uma amostra grande da mesma população é mais
    # estreito que o de uma amostra pequena (consistência básica do bootstrap).
    rng = np.random.default_rng(13)
    pop = np.random.default_rng(7).normal(0.05, 0.10, size=200).tolist()
    _, lo_s, hi_s = ci_mean(pop[:10], 1000, rng)
    _, lo_l, hi_l = ci_mean(pop, 1000, rng)
    assert lo_s <= hi_s and lo_l <= hi_l
    assert (hi_l - lo_l) < (hi_s - lo_s)
