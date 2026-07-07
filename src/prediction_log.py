"""Registro append-only das predições do sistema (JSONL).

Toda predição servida (`predict.show`) é gravada AQUI, no momento em que é feita —
congelando o que o modelo dizia ANTES do jogo. Sem isto a avaliação vs. resultado
real é impossível (ou vaza: reconstruir a posteriori usa um Elo que já viu o placar).

JSONL append-only por decisão de projeto: imune à trava read-only do Shadow (a
produção monta em mode=ro, não aceitaria uma tabela nova), auditável linha a linha
e versionável. Destino: $PREDICTIONS_LOG_PATH ou data/predictions.jsonl.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

ENV_PATH = "PREDICTIONS_LOG_PATH"
ENV_PERIOD_PATH = "PERIOD_LOG_PATH"
ROOT = Path(__file__).resolve().parent.parent
_DEFAULT = ROOT / "data" / "predictions.jsonl"
_PERIOD_DEFAULT = ROOT / "data" / "period_predictions.jsonl"


def _resolve(path=None) -> Path:
    return Path(path or os.environ.get(ENV_PATH) or _DEFAULT)


def _resolve_period(path=None) -> Path:
    return Path(path or os.environ.get(ENV_PERIOD_PATH) or _PERIOD_DEFAULT)


def log_prediction(home, away, neutral, elo_home, elo_away, params, pred,
                   match_date=None, path=None, logged_at=None, market=None) -> dict:
    """Serializa UMA predição como uma linha JSONL — o PACOTE COMPLETO que o motor
    gera para o confronto. `pred` é o dict de model.predict_match. `market` (opcional)
    = dict de predict._market_probs (odds cruas + Shin de 1X2 e O/U) quando há odds.
    `logged_at`/`path` injetáveis para teste. Retorna o registro gravado."""
    a, b, alpha, rho = params
    over = {str(k): round(v, 4) for k, v in pred["over"].items()}
    record = {
        "logged_at": logged_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "match_date": match_date,
        "home": home, "away": away, "neutral": bool(neutral),
        "elo_home": round(float(elo_home), 1), "elo_away": round(float(elo_away), 1),
        "lambda_home": round(pred["lambda_a"], 4), "lambda_away": round(pred["lambda_b"], 4),
        "total_goals": round(pred["total_goals"], 4),
        "p_home": round(pred["p_win"], 4), "p_draw": round(pred["p_draw"], 4),
        "p_away": round(pred["p_loss"], 4),
        "over": over, "under": {k: round(1.0 - v, 4) for k, v in over.items()},
        "btts_yes": round(pred["btts"], 4), "btts_no": round(1.0 - pred["btts"], 4),
        # placares vêm como numpy.int64 (np.arange no motor) — coage a int nativo
        "top_scores": [[[int(sc[0]), int(sc[1])], round(p, 4)] for sc, p in pred["top_scores"]],
        "params": {"a": round(a, 4), "b": round(b, 4),
                   "alpha": round(alpha, 4), "rho": round(rho, 4)},
    }
    if market is not None:                       # comparação vs mercado, se houver odds
        # edge vs PREÇO ofertado (1/odd) de CADA seleção — o gatilho validado no
        # backtest, não o Shin (só mede CLV depois do fato) e não inferido
        # invertendo o sinal de outra seleção (o vig não se reparte igual entre
        # as pontas; cada lado tem sua própria conta, igual ao backtest real).
        record["market"] = {
            "odds_home": market["odds_home"], "odds_draw": market["odds_draw"],
            "odds_away": market["odds_away"],
            "p_home": round(market["p_home"], 4), "p_draw": round(market["p_draw"], 4),
            "p_away": round(market["p_away"], 4),
            "overround_1x2": round(market["overround_1x2"], 4),
            "edge_home_vs_price": round(pred["p_win"] - (1.0 / market["odds_home"]), 4),
            "edge_draw_vs_price": round(pred["p_draw"] - (1.0 / market["odds_draw"]), 4),
            "edge_away_vs_price": round(pred["p_loss"] - (1.0 / market["odds_away"]), 4),
        }
        if market.get("odds_over") and market.get("odds_under"):
            p_over = pred["over"][2.5]
            record["market"].update({
                "odds_over": market["odds_over"], "odds_under": market["odds_under"],
                "p_over": round(market["p_over"], 4), "p_under": round(market["p_under"], 4),
                "overround_ou25": round(market["overround_ou25"], 4),
                "edge_over_vs_price": round(p_over - (1.0 / market["odds_over"]), 4),
                "edge_under_vs_price": round((1.0 - p_over) - (1.0 / market["odds_under"]), 4),
            })
    dest = _resolve(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def log_period_prediction(home, away, neutral, period, fraction, live,
                          calibration=None, match_date=None, path=None,
                          logged_at=None) -> dict:
    """Congela uma predição de PERÍODO (1º ou 2º tempo) — arquivo separado
    (data/period_predictions.jsonl) de propósito: o schema do log pré-jogo
    assume previsão do jogo inteiro feita ANTES do apito; uma projeção
    condicional a placar de intervalo não cabe nele sem ambiguidade.
    `live` é o dict de display.compute_live; `period` é '1T' ou '2T';
    `calibration` é o dict de display.ht_goal_fraction (ou None = 0.5 cru)."""
    per, fin, meta = live["period"], live["final"], live["meta"]
    record = {
        "logged_at": logged_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kind": "period", "period": period,
        "match_date": match_date,
        "home": home, "away": away, "neutral": bool(neutral),
        "current_score": list(meta["current_score"]),
        "fraction": round(float(fraction), 4),
        "calibration": None if calibration is None else
            {"frac1": round(calibration["frac1"], 4), "n": calibration["n"]},
        "period_pred": {
            "lambda_home": round(per["lambda_a"], 4), "lambda_away": round(per["lambda_b"], 4),
            "p_home": round(per["p_win"], 4), "p_draw": round(per["p_draw"], 4),
            "p_away": round(per["p_loss"], 4),
            "over": {str(k): round(v, 4) for k, v in per["over"].items()},
        },
        "final_pred": {
            "p_home": round(fin["p_win"], 4), "p_draw": round(fin["p_draw"], 4),
            "p_away": round(fin["p_loss"], 4),
            "over": {str(k): round(v, 4) for k, v in fin["over"].items()},
            "top_scores": [[[int(sc[0]), int(sc[1])], round(p, 4)]
                           for sc, p in fin["top_scores"]],
        },
    }
    dest = _resolve_period(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record
