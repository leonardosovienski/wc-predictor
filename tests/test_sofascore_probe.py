"""Testes dos helpers PUROS da sonda de diagnóstico do Sofascore.

Sem rede: validam que summarize_* extraem a estrutura certa de respostas
sintéticas que espelham o formato real (markets→choices; statistics→groups→items;
lineups→players→statistics). Documentam o shape esperado da API.
"""
from src.research.sofascore_probe import (
    summarize_odds,
    summarize_statistics,
    summarize_lineups,
)


# ------------------------------------------------------------------ #
# summarize_odds                                                      #
# ------------------------------------------------------------------ #

def test_summarize_odds_extracts_markets_and_choices():
    raw = {
        "markets": [
            {"marketId": 1, "marketName": "Full time", "choiceGroup": None,
             "choices": [{"name": "1"}, {"name": "X"}, {"name": "2"}]},
            {"marketId": 12, "marketName": "Both teams to score",
             "choices": [{"name": "Yes"}, {"name": "No"}]},
        ]
    }
    s = summarize_odds(raw)
    assert s["n_markets"] == 2
    assert s["markets"][0]["marketName"] == "Full time"
    assert s["markets"][0]["choices"] == ["1", "X", "2"]
    assert s["markets"][1]["choices"] == ["Yes", "No"]


def test_summarize_odds_none_safe():
    assert summarize_odds(None) == {"n_markets": 0, "markets": []}
    assert summarize_odds({}) == {"n_markets": 0, "markets": []}


def test_summarize_odds_missing_choices_is_empty_list():
    raw = {"markets": [{"marketId": 5, "marketName": "X"}]}
    s = summarize_odds(raw)
    assert s["markets"][0]["choices"] == []


# ------------------------------------------------------------------ #
# summarize_statistics                                                #
# ------------------------------------------------------------------ #

def test_summarize_statistics_collects_item_names():
    raw = {
        "statistics": [
            {"period": "ALL", "groups": [
                {"groupName": "Shots", "statisticsItems": [
                    {"name": "Total shots", "home": "10", "away": "8"},
                    {"name": "Shots on target", "home": "4", "away": "3"},
                ]},
                {"groupName": "TVData", "statisticsItems": [
                    {"name": "Corner kicks", "home": "5", "away": "2"},
                    {"name": "Fouls", "home": "12", "away": "9"},
                ]},
            ]},
        ]
    }
    s = summarize_statistics(raw)
    assert s["n_periods"] == 1
    assert s["periods"][0]["period"] == "ALL"
    assert "Total shots" in s["periods"][0]["items"]
    assert "Corner kicks" in s["periods"][0]["items"]
    assert "Fouls" in s["periods"][0]["items"]


def test_summarize_statistics_none_safe():
    assert summarize_statistics(None) == {"n_periods": 0, "periods": []}


# ------------------------------------------------------------------ #
# summarize_lineups                                                   #
# ------------------------------------------------------------------ #

def test_summarize_lineups_collects_stat_keys():
    raw = {
        "home": {"players": [
            {"player": {"name": "A"}, "statistics": {"rating": 7.1, "minutesPlayed": 90}},
            {"player": {"name": "B"}, "statistics": {"rating": 6.5, "totalShots": 2}},
        ]},
        "away": {"players": [
            {"player": {"name": "C"}, "statistics": {"rating": 6.9, "minutesPlayed": 80}},
        ]},
    }
    s = summarize_lineups(raw)
    assert s["n_players"] == 3
    assert "rating" in s["player_stat_keys"]
    assert "minutesPlayed" in s["player_stat_keys"]
    assert "totalShots" in s["player_stat_keys"]


def test_summarize_lineups_none_safe():
    assert summarize_lineups(None) == {"n_players": 0, "player_stat_keys": []}
