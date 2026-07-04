import json

from src.settle import grade, record_result, summary

_PRED = {
    "home": "France", "away": "Paraguay",
    "p_home": 0.745, "p_draw": 0.168, "p_away": 0.087,
    "lambda_home": 2.52, "lambda_away": 0.62,
    "over": {"1.5": 0.78, "2.5": 0.573, "3.5": 0.38},
    "btts_yes": 0.397, "btts_no": 0.603,
    "top_scores": [[[2, 0], 0.125]], "logged_at": "2026-07-03T00:00:00+00:00",
}


def test_grade_marks_each_market():
    g = grade(_PRED, 1, 0)                          # França 1-0
    assert g["winner"]["pick"] == "France" and g["winner"]["correct"] is True
    assert g["over_under_2.5"]["pick"] == "Over"    # 0.573 >= 0.5
    assert g["over_under_2.5"]["actual"] == "Under" and g["over_under_2.5"]["correct"] is False
    assert g["btts"]["pick"] == "Não" and g["btts"]["correct"] is True  # 1-0, visitante não marcou
    assert g["exact_score"]["pick"] == "2x0" and g["exact_score"]["correct"] is False


def test_record_and_summary_roundtrip(tmp_path):
    pred_p = tmp_path / "predictions.jsonl"
    pred_p.write_text(json.dumps(_PRED) + "\n", encoding="utf-8")
    res_p = tmp_path / "results.jsonl"
    rec = record_result("France", "Paraguay", 1, 0, match_date=None,
                         stats={"corners": [12, 2], "yellow": [3, 0]},
                         path=res_p, pred_path=pred_p)
    assert rec["actual"]["stats"]["corners"] == [12, 2]   # stat cru guardado
    assert rec["grades"]["winner"]["correct"] is True
    tally = summary(path=res_p)
    assert tally["winner"] == [1, 1]


def test_record_without_prediction_warns(tmp_path):
    res_p = tmp_path / "results.jsonl"
    rec = record_result("Xland", "Yland", 2, 2, path=res_p,
                        pred_path=tmp_path / "nope.jsonl")
    assert rec["prediction"] is None and "warning" in rec
    assert rec["actual"]["result"] == "draw"
