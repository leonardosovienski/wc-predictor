"""Livro-caixa de apostas: registro, settle com lucro/push e ROI acumulado.
Tudo em tmp_path — nunca toca data/bets.jsonl real."""
import json

import pytest

from src.bet_log import (add_bet, bank_flow, bank_init, bank_state,
                         settle_bet, summary)


def test_add_grava_linha_aberta(tmp_path):
    p = tmp_path / "bets.jsonl"
    rec = add_bet("Norway", "England", "ou25", "under", 2.21, book="BetOnline",
                  edge=0.095, model_prob=0.548, match_date="2026-07-11", path=p)
    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    r = json.loads(lines[0])
    assert r["kind"] == "bet" and r["status"] == "open"
    assert r["selection"] == "under" and r["line"] == 2.5 and r["odds"] == 2.21
    assert r["stake"] == 1.0                      # stake fixo default
    assert rec["book"] == "BetOnline"


def test_add_rejeita_mercado_e_odd_invalidos(tmp_path):
    p = tmp_path / "bets.jsonl"
    with pytest.raises(ValueError):
        add_bet("A", "B", "1x2", "home", 2.0, path=p)     # mercado sem CLV
    with pytest.raises(ValueError):
        add_bet("A", "B", "ou25", "over", 0.9, path=p)    # odd <= 1


def test_settle_ganha_perde_e_nao_duplica(tmp_path):
    p = tmp_path / "bets.jsonl"
    add_bet("Norway", "England", "ou25", "under", 2.21, path=p)
    add_bet("Norway", "England", "ou25", "over", 2.30, path=p)
    recs = settle_bet("Norway", "England", 0, 1, path=p)    # total 1 -> under ganha
    assert len(recs) == 2
    by_sel = {r["selection"]: r for r in recs}
    assert by_sel["under"]["won"] is True
    assert by_sel["under"]["profit"] == pytest.approx(1.21)
    assert by_sel["over"]["won"] is False
    assert by_sel["over"]["profit"] == -1.0
    # settle repetido nao re-fecha (append-only, idempotente)
    assert settle_bet("Norway", "England", 0, 1, path=p) == []


def test_settle_casa_por_conjunto_de_times(tmp_path):
    # resultado informado na ordem invertida ainda fecha a aposta
    p = tmp_path / "bets.jsonl"
    add_bet("Norway", "England", "ou25", "under", 2.0, path=p)
    recs = settle_bet("England", "Norway", 3, 1, path=p)    # total 4 -> under perde
    assert len(recs) == 1 and recs[0]["won"] is False


def test_settle_periodo_exige_ht_e_fecha_com_ht(tmp_path):
    # 1T/2T: sem --ht a aposta de período segue aberta; com HT fecha certo.
    p = tmp_path / "bets.jsonl"
    add_bet("A", "B", "ou05_1t", "over", 2.4, path=p)     # >=1 gol no 1o tempo
    add_bet("A", "B", "ou15_2t", "under", 1.8, path=p)    # <2 gols no 2o tempo
    add_bet("A", "B", "ou25", "under", 2.0, path=p)       # jogo inteiro
    recs = settle_bet("A", "B", 2, 1, path=p)             # sem ht
    assert [r["market"] for r in recs] == ["ou25"]        # só o FT fechou
    recs = settle_bet("A", "B", 2, 1, ht="0-1", path=p)   # 1T=1 gol, 2T=2 gols
    by = {r["market"]: r for r in recs}
    assert by["ou05_1t"]["won"] is True                   # 1 > 0.5
    assert by["ou15_2t"]["won"] is False                  # 2 > 1.5 -> under perde
    assert by["ou05_1t"]["validated"] is False            # marcado sem CLV
    # nada re-fecha
    assert settle_bet("A", "B", 2, 1, ht="0-1", path=p) == []


def test_summary_separa_validado_de_informativo(tmp_path):
    p = tmp_path / "bets.jsonl"
    add_bet("A", "B", "ou25", "under", 2.0, path=p)
    add_bet("A", "B", "ou05_1t", "over", 2.0, path=p)
    settle_bet("A", "B", 1, 0, ht="1-0", path=p)
    t = summary(path=p)
    assert t["ou25"]["validated"] is True
    assert t["ou05_1t"]["validated"] is False


def test_summary_roi(tmp_path):
    p = tmp_path / "bets.jsonl"
    add_bet("A1", "B1", "ou25", "under", 2.0, path=p)
    add_bet("A2", "B2", "ou25", "over", 2.0, path=p)
    settle_bet("A1", "B1", 1, 0, path=p)     # under ganha: +1.0
    settle_bet("A2", "B2", 1, 0, path=p)     # over perde: -1.0
    t = summary(path=p)["ou25"]
    assert t["n"] == 2 and t["staked"] == 2.0
    assert t["profit"] == pytest.approx(0.0)
    assert t["roi"] == pytest.approx(0.0)


def test_banca_saldo_exposicao_e_drawdown(tmp_path):
    bank = tmp_path / "bankroll.jsonl"
    bets = tmp_path / "bets.jsonl"
    bank_init(1000.0, 20.0, path=bank)                 # unidade = 2% da banca
    add_bet("A1", "B1", "ou25", "under", 2.0, path=bets)
    add_bet("A2", "B2", "ou25", "over", 2.5, path=bets)
    st = bank_state(bank_path=bank, bets_path=bets)
    assert st["balance"] == 1000.0                     # nada fechado ainda
    assert st["open_units"] == 2.0 and st["open_money"] == 40.0
    settle_bet("A1", "B1", 3, 1, path=bets)            # under 2.5 perde: -1u
    settle_bet("A2", "B2", 2, 1, path=bets)            # over 2.5 ganha: +1.5u
    st = bank_state(bank_path=bank, bets_path=bets)
    assert st["profit_units"] == pytest.approx(0.5)
    assert st["balance"] == pytest.approx(1000.0 + 0.5 * 20.0)
    assert st["open_units"] == 0.0
    # drawdown: perdeu 1u (20) antes de ganhar — pico 1000, vale 980
    assert st["max_drawdown_money"] == pytest.approx(20.0)


def test_banca_deposito_saque_e_reinit(tmp_path):
    bank = tmp_path / "bankroll.jsonl"
    bets = tmp_path / "bets.jsonl"
    bank_init(500.0, 10.0, path=bank)
    bank_flow("deposit", 200.0, path=bank)
    bank_flow("withdraw", 100.0, path=bank)
    st = bank_state(bank_path=bank, bets_path=bets)
    assert st["balance"] == 600.0 and st["flows"] == 100.0
    bank_init(1000.0, 20.0, path=bank)                 # reinit zera fluxos
    st = bank_state(bank_path=bank, bets_path=bets)
    assert st["balance"] == 1000.0 and st["flows"] == 0.0


def test_banca_none_sem_init(tmp_path):
    assert bank_state(bank_path=tmp_path / "nada.jsonl",
                      bets_path=tmp_path / "bets.jsonl") is None
    with pytest.raises(ValueError):
        bank_init(-5, 1, path=tmp_path / "bankroll.jsonl")
    with pytest.raises(ValueError):
        bank_flow("roubo", 10, path=tmp_path / "bankroll.jsonl")
