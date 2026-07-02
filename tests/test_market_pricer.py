"""Testes do MarketPricer — grade sintética 3x3 com valores calculáveis à mão.

grid[i][j] = P(casa=i, fora=j). Soma = 1.0. Margem m = i - j.

Distribuição de margem (verificada à mão):
  m=-2: 0.05 | m=-1: 0.15 | m=0: 0.45 | m=1: 0.25 | m=2: 0.10
Distribuição de total:
  t=0: 0.10 | t=1: 0.25 | t=2: 0.35 | t=3: 0.15 | t=4: 0.15
"""
import pytest

from src.market_pricer import (
    result_1x2,
    double_chance,
    both_teams_to_score,
    over_under,
    exact_score,
    draw_no_bet,
    asian_handicap,
)

# casa nas linhas, fora nas colunas
GRID = [
    [0.10, 0.10, 0.05],   # casa=0
    [0.15, 0.20, 0.05],   # casa=1
    [0.10, 0.10, 0.15],   # casa=2
]


def test_grid_sums_to_one():
    assert sum(sum(r) for r in GRID) == pytest.approx(1.0)


def test_result_1x2():
    o = result_1x2(GRID)
    assert o["1"] == pytest.approx(0.35)   # i>j
    assert o["X"] == pytest.approx(0.45)   # i==j
    assert o["2"] == pytest.approx(0.20)   # i<j
    assert o["1"] + o["X"] + o["2"] == pytest.approx(1.0)


def test_double_chance():
    dc = double_chance(GRID)
    assert dc["1X"] == pytest.approx(0.80)
    assert dc["X2"] == pytest.approx(0.65)
    assert dc["12"] == pytest.approx(0.55)


def test_btts():
    b = both_teams_to_score(GRID)
    assert b["Yes"] == pytest.approx(0.50)
    assert b["No"] == pytest.approx(0.50)


def test_over_under_half_line_no_push():
    ou = over_under(GRID, 2.5)
    assert ou["Over"] == pytest.approx(0.30)
    assert ou["Under"] == pytest.approx(0.70)
    assert ou["Push"] == pytest.approx(0.0)


def test_over_under_other_half_line():
    ou = over_under(GRID, 1.5)
    assert ou["Over"] == pytest.approx(0.65)
    assert ou["Under"] == pytest.approx(0.35)


def test_over_under_integer_line_has_push():
    ou = over_under(GRID, 2)
    assert ou["Over"] == pytest.approx(0.30)   # totais 3,4
    assert ou["Under"] == pytest.approx(0.35)  # totais 0,1
    assert ou["Push"] == pytest.approx(0.35)   # total == 2
    assert ou["Over"] + ou["Under"] + ou["Push"] == pytest.approx(1.0)


def test_exact_score():
    assert exact_score(GRID, 1, 1) == pytest.approx(0.20)
    assert exact_score(GRID, 0, 2) == pytest.approx(0.05)
    assert exact_score(GRID, 2, 0) == pytest.approx(0.10)


def test_exact_score_out_of_range():
    assert exact_score(GRID, 3, 0) == 0.0
    assert exact_score(GRID, -1, 0) == 0.0


def test_draw_no_bet_push_is_draw():
    dnb = draw_no_bet(GRID)
    assert dnb["1"]["win"] == pytest.approx(0.35)
    assert dnb["1"]["push"] == pytest.approx(0.45)
    assert dnb["1"]["lose"] == pytest.approx(0.20)
    assert dnb["2"]["win"] == pytest.approx(0.20)
    assert dnb["2"]["push"] == pytest.approx(0.45)
    # cada lado soma 1.0
    for side in ("1", "2"):
        s = dnb[side]
        assert s["win"] + s["push"] + s["lose"] == pytest.approx(1.0)


def test_asian_handicap_level():
    ah = asian_handicap(GRID, 0.0)
    assert ah["win"] == pytest.approx(0.35)   # m>0
    assert ah["push"] == pytest.approx(0.45)  # m==0
    assert ah["lose"] == pytest.approx(0.20)  # m<0


def test_asian_handicap_minus_one_integer_push():
    ah = asian_handicap(GRID, -1.0)
    assert ah["win"] == pytest.approx(0.10)   # m>1 → m=2
    assert ah["push"] == pytest.approx(0.25)  # m==1
    assert ah["lose"] == pytest.approx(0.65)  # m<=0
    assert ah["win"] + ah["push"] + ah["lose"] == pytest.approx(1.0)


def test_asian_handicap_half_line_no_push():
    ah = asian_handicap(GRID, -0.5)
    assert ah["win"] == pytest.approx(0.35)   # m>=1
    assert ah["push"] == pytest.approx(0.0)
    assert ah["lose"] == pytest.approx(0.65)  # m<=0


def test_asian_handicap_plus_half():
    ah = asian_handicap(GRID, 0.5)
    assert ah["win"] == pytest.approx(0.80)   # m>=0
    assert ah["lose"] == pytest.approx(0.20)  # m<=-1
    assert ah["push"] == pytest.approx(0.0)


def test_asian_handicap_quarter_line_splits():
    # -0.75 = média de -0.5 e -1.0
    ah = asian_handicap(GRID, -0.75)
    assert ah["win"] == pytest.approx((0.35 + 0.10) / 2)    # 0.225
    assert ah["push"] == pytest.approx((0.0 + 0.25) / 2)    # 0.125
    assert ah["lose"] == pytest.approx((0.65 + 0.65) / 2)   # 0.65
    assert ah["win"] + ah["push"] + ah["lose"] == pytest.approx(1.0)


def test_non_square_grid_raises():
    with pytest.raises(ValueError):
        result_1x2([[0.5, 0.5]])
