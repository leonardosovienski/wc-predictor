"""Testes do parse_all_odds — payloads no formato REAL do Sofascore.

Estrutura espelha sofascore_probe_15186624.json: choices com fractionalValue
('4/5'), OU com a linha em choiceGroup, AH com '(-0.75) Time' no nome do choice.
Odds em fração: '4/5' → 1 + 4/5 = 1.8; '1/1' → 2.0; '6/5' → 2.2.
"""
import pytest

from src.ingest_sofascore import parse_all_odds


def _choice(name, frac):
    return {"name": name, "fractionalValue": frac,
            "initialFractionalValue": frac, "change": 0}


RAW = {
    "markets": [
        {"marketId": 1, "marketName": "Full time", "choiceGroup": None,
         "choices": [_choice("1", "4/5"), _choice("X", "1/1"), _choice("2", "6/5")]},
        {"marketId": 2, "marketName": "Double chance", "choiceGroup": None,
         "choices": [_choice("1X", "1/5"), _choice("X2", "1/1"), _choice("12", "1/2")]},
        {"marketId": 4, "marketName": "Draw no bet", "choiceGroup": None,
         "choices": [_choice("1", "1/4"), _choice("2", "11/4")]},
        {"marketId": 5, "marketName": "Both teams to score", "choiceGroup": None,
         "choices": [_choice("Yes", "1/1"), _choice("No", "7/10")]},
        {"marketId": 9, "marketName": "Match goals", "choiceGroup": "1.5",
         "choices": [_choice("Over", "2/5"), _choice("Under", "2/1")]},
        {"marketId": 9, "marketName": "Match goals", "choiceGroup": "2.5",
         "choices": [_choice("Over", "1/1"), _choice("Under", "4/5")]},
        {"marketId": 17, "marketName": "Asian handicap", "choiceGroup": None,
         "choices": [_choice("(-0.75) Croatia", "1/1"), _choice("(0.75) Ghana", "4/5")]},
        # mercados fora do escopo da Fase 1 — devem ser ignorados
        {"marketId": 3, "marketName": "1st half", "choiceGroup": None,
         "choices": [_choice("1", "7/5")]},
        {"marketId": 20, "marketName": "Cards in match", "choiceGroup": "2.5",
         "choices": [_choice("Over", "4/5")]},
    ]
}


def test_1x2():
    out = parse_all_odds(RAW)
    assert out["1x2"]["1"] == pytest.approx(1.8)
    assert out["1x2"]["X"] == pytest.approx(2.0)
    assert out["1x2"]["2"] == pytest.approx(2.2)


def test_double_chance():
    out = parse_all_odds(RAW)
    assert out["dc"]["1X"] == pytest.approx(1.2)
    assert out["dc"]["12"] == pytest.approx(1.5)


def test_draw_no_bet():
    out = parse_all_odds(RAW)
    assert out["dnb"]["1"] == pytest.approx(1.25)
    assert out["dnb"]["2"] == pytest.approx(3.75)


def test_btts():
    out = parse_all_odds(RAW)
    assert out["btts"]["Yes"] == pytest.approx(2.0)
    assert out["btts"]["No"] == pytest.approx(1.7)


def test_ou_multi_line():
    out = parse_all_odds(RAW)
    assert set(out["ou"].keys()) == {1.5, 2.5}
    assert out["ou"][1.5]["Over"] == pytest.approx(1.4)
    assert out["ou"][2.5]["Over"] == pytest.approx(2.0)
    assert out["ou"][2.5]["Under"] == pytest.approx(1.8)


def test_asian_handicap_oriented_to_home():
    # Croatia é a casa → home_line = -0.75; Ghana (fora) recebe +0.75
    out = parse_all_odds(RAW, home_name="Croatia", away_name="Ghana")
    assert -0.75 in out["ah"]
    assert out["ah"][-0.75]["home"] == pytest.approx(2.0)   # (-0.75) Croatia = 1/1
    assert out["ah"][-0.75]["away"] == pytest.approx(1.8)   # (0.75) Ghana = 4/5


def test_asian_handicap_orientation_flips_with_home():
    # se Ghana for a casa, a linha do mando passa a ser +0.75
    out = parse_all_odds(RAW, home_name="Ghana", away_name="Croatia")
    assert 0.75 in out["ah"]
    assert out["ah"][0.75]["home"] == pytest.approx(1.8)    # (0.75) Ghana
    assert out["ah"][0.75]["away"] == pytest.approx(2.0)    # (-0.75) Croatia


def test_out_of_scope_markets_ignored():
    # cards (20) e corners (21) viraram mercados SUPORTADOS na extensão de
    # eventos — o teste antigo (que os proibia) ficou obsoleto e falhava.
    out = parse_all_odds(RAW)
    # 1st half (3) e afins continuam fora; só as chaves conhecidas existem
    assert all(k in ("1x2", "dc", "dnb", "btts", "ou", "ah", "cards", "corners")
               for k in out)
    # nada de cards/1st-half vazou para ou/1x2
    assert 2.5 in out["ou"]  # essa é a linha de gols, não de cartões


def test_none_and_empty_safe():
    assert parse_all_odds(None)["1x2"] == {}
    assert parse_all_odds({})["ou"] == {}
    assert parse_all_odds({"markets": []})["ah"] == {}


def test_ah_without_team_names_is_skipped():
    # sem home/away, não dá para orientar o AH → fica vazio (não quebra)
    out = parse_all_odds(RAW)
    assert out["ah"] == {}


def test_initial_reads_opening_odds():
    # abertura (initialFractionalValue) distinta do fechamento (fractionalValue)
    raw = {"markets": [
        {"marketId": 1, "choices": [
            {"name": "1", "fractionalValue": "4/5", "initialFractionalValue": "73/100"},
            {"name": "X", "fractionalValue": "1/1", "initialFractionalValue": "11/10"},
            {"name": "2", "fractionalValue": "6/5", "initialFractionalValue": "5/4"}]},
        {"marketId": 9, "choiceGroup": "2.5", "choices": [
            {"name": "Over", "fractionalValue": "1/1", "initialFractionalValue": "9/10"},
            {"name": "Under", "fractionalValue": "4/5", "initialFractionalValue": "17/20"}]},
    ]}
    close = parse_all_odds(raw)
    op = parse_all_odds(raw, initial=True)
    assert close["1x2"]["1"] == pytest.approx(1.8)     # 4/5 (fechamento)
    assert op["1x2"]["1"] == pytest.approx(1.73)       # 73/100 (abertura)
    assert op["ou"][2.5]["Over"] == pytest.approx(1.9)  # 9/10 (abertura)
