"""Gap #5 da auditoria: propriedades do Elo — SÓ verificação de propriedade.
Conservação na troca, zebra move mais que favorito, decay regride à média.
NOTA (do HANDOFF): o viés continental do ranking NÃO é bug — é a Hipótese
pré-registrada #1; nenhum blend é proposto aqui."""
from datetime import date

import pytest

from src.ratings import compute_ratings, k_factor, margin_multiplier

CFG = {"initial_rating": 1500, "home_advantage": 100,
       "k_factors": {"default": 30, "FIFA World Cup": 60, "Friendly": 20}}


def _m(d, home, away, hs, as_, tournament="Friendly", neutral=1):
    return (d, home, away, hs, as_, tournament, neutral)


# ------------------------------------------------------------- conservação
def test_troca_conserva_pontos():
    # sem decay: o delta sai de um e entra no outro — soma do sistema invariante.
    ratings, _ = compute_ratings([_m("2026-06-01", "A", "B", 2, 0)], CFG)
    assert ratings["A"] + ratings["B"] == pytest.approx(2 * 1500)
    assert ratings["A"] > 1500 > ratings["B"]


def test_conservacao_em_serie_longa():
    ms = [_m(f"2026-06-{d:02d}", h, a, hs, as_)
          for d, (h, a, hs, as_) in enumerate(
              [("A", "B", 3, 1), ("B", "C", 0, 0), ("C", "A", 2, 2),
               ("A", "C", 1, 0), ("B", "A", 4, 2)], start=1)]
    ratings, _ = compute_ratings(ms, CFG)
    assert sum(ratings.values()) == pytest.approx(3 * 1500)


# ------------------------------------------------------------- zebra vs favorito
def test_zebra_move_mais_que_favorito():
    # A chega ao 2º jogo mais forte que B. Vitória de B (zebra) tem que mover
    # mais pontos que vitória de A (esperada), mesmo K e mesma margem.
    prep = _m("2026-06-01", "A", "C", 3, 0)

    r_zebra, _ = compute_ratings([prep, _m("2026-06-10", "B", "A", 1, 0)], CFG)
    r_favo, _ = compute_ratings([prep, _m("2026-06-10", "B", "A", 0, 1)], CFG)

    move_zebra = abs(r_zebra["B"] - 1500)
    move_favorito = abs(r_favo["B"] - 1500)
    assert move_zebra > move_favorito


# ------------------------------------------------------------- decay
def test_decay_regride_a_media():
    # A ganha pontos em 2010 e some por 10 anos. No jogo seguinte, o rating
    # PRÉ-jogo (history) tem que ter regredido a 1500 pelo fator 0.5^(anos/HL).
    cfg = dict(CFG, form_half_life_years=4.0)
    ms = [_m("2010-06-01", "A", "B", 3, 0, "FIFA World Cup"),
          _m("2020-06-01", "A", "C", 0, 0)]

    _, hist_decay = compute_ratings(ms, cfg)
    _, hist_sem = compute_ratings(ms, CFG)

    ganho_2010 = hist_sem[1][0]            # diff pré-jogo vs C (1500), sem decay
    years = (date(2020, 6, 1) - date(2010, 6, 1)).days / 365.25
    esperado = ganho_2010 * 0.5 ** (years / 4.0)
    assert hist_decay[1][0] == pytest.approx(esperado)
    assert 0 < hist_decay[1][0] < ganho_2010     # regrediu, não cruzou a média


def test_decay_nulo_e_identidade():
    cfg = dict(CFG, form_half_life_years=None)
    ms = [_m("2010-06-01", "A", "B", 3, 0), _m("2020-06-01", "A", "C", 1, 1)]
    _, h1 = compute_ratings(ms, cfg)
    _, h2 = compute_ratings(ms, CFG)
    assert h1 == h2


# ------------------------------------------------------------- K e margem
def test_k_fallback_de_eliminatoria():
    # torneio desconhecido com "qualification" no nome cai no K de eliminatória.
    assert k_factor("AFC Asian Cup qualification", CFG["k_factors"]) == 40


def test_k_de_torneio_nulo_nao_estoura():
    assert k_factor(None, CFG["k_factors"]) == 30


def test_margem_cresce_monotonicamente():
    mults = [margin_multiplier(d) for d in range(6)]
    assert mults == sorted(mults)
    assert mults[0] == mults[1] == 1.0
