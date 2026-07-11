"""W2 (auditoria 2026-07-09): bet_id único, schema aditivo, legado intacto."""
import json

from src.bet_log import add_bet, list_bets, settle_bet


def test_bet_id_unico_e_presente(tmp_path):
    p = tmp_path / "bets.jsonl"
    r1 = add_bet("Spain", "France", "ou25", "under", 1.9, path=p)
    r2 = add_bet("Spain", "France", "ou15", "over", 2.4, path=p)
    assert r1["bet_id"] and r2["bet_id"]
    assert r1["bet_id"] != r2["bet_id"]
    assert len(r1["bet_id"]) == 36              # uuid4 canônico


def test_bet_id_injetavel_e_carimbado_no_settlement(tmp_path):
    p = tmp_path / "bets.jsonl"
    add_bet("Spain", "France", "ou25", "under", 1.9, path=p,
            bet_id="teste-0001")
    recs = settle_bet("Spain", "France", 1, 0, path=p)
    assert len(recs) == 1
    assert recs[0]["bet_id"] == "teste-0001"
    # e o list casa aposta+resultado normalmente (vínculo legado intacto)
    bets = list_bets(path=p)
    assert bets[0]["bet_id"] == "teste-0001"
    assert bets[0]["result"]["bet_id"] == "teste-0001"


def test_aposta_legada_sem_bet_id_liquida_normal(tmp_path):
    """Linha PRÉ-W2 no livro (sem a chave): settle funciona e o settlement
    carimba bet_id=None — o schema é aditivo, o passado não é reescrito."""
    p = tmp_path / "bets.jsonl"
    legado = {"logged_at": "2026-07-08T00:00:00+00:00", "kind": "bet",
              "status": "open", "home": "Norway", "away": "England",
              "match_date": None, "kickoff": None, "late": None,
              "market": "ou25", "line": 2.5, "period": "FT",
              "selection": "under", "odds": 2.1, "book": None, "stake": 1.0,
              "model_prob": None, "edge": None, "note": None,
              "validated": True, "duplicate_of_open": False}
    p.write_text(json.dumps(legado) + "\n", encoding="utf-8")
    recs = settle_bet("Norway", "England", 0, 1, path=p)
    assert len(recs) == 1
    assert recs[0]["bet_id"] is None
    assert recs[0]["won"] is True               # under 2.5, total 1
