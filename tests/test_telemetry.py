"""Telemetria JSONL integrada ao backtest (Shadow v2): emite backtest_completed
com ROI/CLV — testado com ledger sintético, sem precisar de odds reais."""
from src import backtest
from predictor_core import obs


def test_backtest_emits_structured_event(tmp_path, monkeypatch):
    monkeypatch.setenv("PREDICTOR_EVENTS_PATH", str(tmp_path / "ev.jsonl"))
    ledger = [
        {"stake": 1.0, "pnl": 0.25, "bet_at": "open", "clv": 0.05},
        {"stake": 1.0, "pnl": -1.0, "bet_at": "open", "clv": -0.02},
        {"stake": 1.0, "pnl": 0.40, "bet_at": "close", "clv": -0.01},
    ]
    backtest._emit_telemetry(ledger)
    events = obs.read_events(tmp_path / "ev.jsonl")
    assert len(events) == 1
    e = events[0]
    assert e["domain"] == "wc" and e["event"] == "backtest_completed"
    assert e["metrics"]["n_bets"] == 3
    assert "roi" in e["metrics"] and "clv_open_mean" in e["metrics"]
    assert e["metadata"]["shadow"] == "v2"
