import pytest
from src.ingest_sofascore import _safe_float, parse_statistics, parse_statistics_flat


MOCK_EVENT_STATS = {
    "statistics": [
        {
            "period": "ALL",
            "groups": [
                {
                    "statisticsItems": [
                        {"name": "Ball possession", "home": "53%", "away": "47%"},
                        {"name": "Expected goals", "home": "1.63", "away": "0.69"},
                        {"name": "Big chances", "home": "3", "away": "1"},
                        {"name": "Total shots", "home": "15", "away": "8"},
                    ]
                }
            ]
        },
        {
            "period": "1ST",
            "groups": [
                {
                    "statisticsItems": [
                        {"name": "Ball possession", "home": "55%", "away": "45%"},
                        {"name": "Expected goals", "home": "0.80", "away": "0.30"},
                    ]
                }
            ]
        }
    ]
}


def test_safe_float():
    assert _safe_float("53%") == 53.0
    assert _safe_float("1.63") == 1.63
    assert _safe_float(None) is None
    assert _safe_float(5) == 5.0
    assert _safe_float("abc") is None
    assert _safe_float("7.5km") == 7.5


def test_parse_statistics():
    result = parse_statistics(MOCK_EVENT_STATS)
    assert 'ALL' in result
    assert '1ST' in result
    assert result['ALL']['Ball possession']['home'] == 53.0
    assert result['ALL']['Ball possession']['away'] == 47.0
    assert result['ALL']['Expected goals']['home'] == 1.63
    assert result['ALL']['Expected goals']['away'] == 0.69
    assert result['ALL']['Big chances']['home'] == 3.0
    assert result['1ST']['Expected goals']['home'] == 0.80


def test_parse_statistics_flat():
    rows = parse_statistics_flat(MOCK_EVENT_STATS, event_id=123)
    assert len(rows) == 12  # 4 stats * 2 teams (ALL) + 2 stats * 2 teams (1ST)
    home_xg_all = [r for r in rows
                   if r['team'] == 'home'
                   and r['stat_name'] == 'Expected goals'
                   and r['period'] == 'ALL']
    assert len(home_xg_all) == 1
    assert home_xg_all[0]['value'] == 1.63
    assert home_xg_all[0]['event_id'] == 123


def test_parse_empty():
    assert parse_statistics({}) == {}
    assert parse_statistics(None) == {}
    assert parse_statistics_flat({}, 1) == []
    assert parse_statistics_flat(None, 1) == []