import json

import numpy as np

from src.prediction_log import log_prediction

_PRED = {
    "lambda_a": 1.23, "lambda_b": 0.98, "total_goals": 2.21,
    "p_win": 0.45, "p_draw": 0.28, "p_loss": 0.27,
    "over": {1.5: 0.68, 2.5: 0.44, 3.5: 0.24}, "btts": 0.47,
    # numpy.int64 como o motor real devolve — guarda contra regressão de serialização
    "top_scores": [((np.int64(1), np.int64(0)), 0.11), ((np.int64(1), np.int64(1)), 0.10)],
}
_MARKET = (0.42, 0.29, 0.29, 0.06)
_PARAMS = (0.22, 1.06, 0.153, -0.039)


def test_log_appends_one_jsonl_line(tmp_path):
    p = tmp_path / "predictions.jsonl"
    log_prediction("Brazil", "Norway", True, 1806, 1767, _PARAMS, _PRED,
                   match_date="2026-07-05", path=p)
    log_prediction("Portugal", "Spain", True, 1778, 1875, _PARAMS, _PRED,
                   match_date="2026-07-06", path=p)
    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2                       # append-only, uma linha por predição
    rec = json.loads(lines[0])
    assert rec["home"] == "Brazil" and rec["away"] == "Norway"
    assert rec["neutral"] is True
    assert rec["match_date"] == "2026-07-05"
    assert rec["p_home"] == 0.45 and rec["p_draw"] == 0.28
    assert rec["over"]["2.5"] == 0.44 and rec["under"]["2.5"] == round(1 - 0.44, 4)
    assert rec["total_goals"] == 2.21
    assert rec["btts_yes"] == 0.47 and rec["btts_no"] == round(1 - 0.47, 4)
    assert rec["params"]["rho"] == -0.039
    assert "market" not in rec                     # sem odds passadas ⇒ sem bloco de mercado
    assert "logged_at" in rec                     # carimbo de quando foi congelada


def test_log_records_market_block_when_odds_present(tmp_path):
    p = tmp_path / "predictions.jsonl"
    log_prediction("A", "B", True, 1600, 1500, _PARAMS, _PRED,
                   market=_MARKET, path=p)
    rec = json.loads(p.read_text(encoding="utf-8").splitlines()[0])
    assert rec["market"]["p_home"] == 0.42 and rec["market"]["overround"] == 0.06
    assert rec["market"]["edge_home"] == round(0.45 - 0.42, 4)


def test_log_respects_env_path(tmp_path, monkeypatch):
    p = tmp_path / "sub" / "preds.jsonl"          # diretório ainda não existe
    monkeypatch.setenv("PREDICTIONS_LOG_PATH", str(p))
    log_prediction("A", "B", False, 1500, 1500, _PARAMS, _PRED)
    assert p.exists() and len(p.read_text().splitlines()) == 1
