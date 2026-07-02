"""Backtest dos mercados estendidos SEM push (Fase 1, passo 4a): BTTS, DC, OU
meia-linha. Usa db :memory: real (schema+migração) e run_backtest de verdade.

Cobre: presença e liquidação correta dos novos mercados; exclusão de linha
inteira de OU (push → 4b) e de AH (4b); orientação (swap) do Double Chance.
"""
import pytest

from src import db
from src.backtest import run_backtest

CFG = {"elo": {"initial_rating": 1500, "home_advantage": 100,
               "k_factors": {"default": 30, "Friendly": 20}},
       "model": {"max_goals": 8},
       "backtest": {"min_edge": -1.0, "max_edge": 1.0, "over_under_line": 2.5}}


def _ss_row(event_id, home, away, date):
    # 20 colunas na ordem do SS_MATCH (mesma forma do test_backtest_odds)
    base = dict(
        event_id=event_id, competition="WC", season="2026", date=date,
        home_team=home, away_team=away, home_score=None, away_score=None,
        home_xg=None, away_xg=None,
        odds_home=2.80, odds_draw=3.40, odds_away=2.50,
        odds_over=1.90, odds_under=1.95,
        odds_home_open=2.90, odds_draw_open=3.30, odds_away_open=2.40,
        odds_over_open=1.85, odds_under_open=2.00)
    return tuple(base.values())


def _setup(conn, home="Brazil", away="Serbia", hs=2, as_=0, eid=1,
           dc=None, btts=None, ou_lines=None):
    conn.execute(
        "INSERT INTO matches (date, home_team, away_team, home_score, away_score,"
        " tournament, city, country, neutral) "
        "VALUES ('2026-06-20',?,?,?,?,'Friendly','','',0)", (home, away, hs, as_))
    conn.commit()
    db.upsert_ss_matches(conn, [_ss_row(eid, home, away, "2026-06-20")])
    parsed = {}
    if dc:
        parsed["dc"] = dc
    if btts:
        parsed["btts"] = btts
    if parsed:
        db.update_flat_markets(conn, eid, parsed, parsed)   # open == close para o teste
    if ou_lines:
        rows = [(eid, "ou", ln, o, u, o, u) for ln, (o, u) in ou_lines.items()]
        db.upsert_odds_lines(conn, rows)


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    yield c
    c.close()


# ------------------------------------------------------------------ #
# BTTS                                                                 #
# ------------------------------------------------------------------ #

def test_btts_settled_no_push(conn):
    # Brazil 2-0 Serbia → BTTS = No (Sérvia não marcou)
    _setup(conn, btts={"Yes": 2.0, "No": 1.7})
    _params, ledger = run_backtest(CFG, conn)
    btts = {b["selection"]: b for b in ledger if b["market"] == "btts"}
    assert set(btts) == {"yes", "no"}
    assert btts["no"]["won"] == 1
    assert btts["yes"]["won"] == 0
    assert btts["yes"]["offered_odd"] == 2.0     # abertura == fechamento aqui


# ------------------------------------------------------------------ #
# Double Chance + orientação                                          #
# ------------------------------------------------------------------ #

def test_double_chance_settled(conn):
    # Brazil mandante venceu → 1X ganha, X2 perde, 12 ganha
    _setup(conn, dc={"1X": 1.2, "X2": 1.9, "12": 1.4})
    _params, ledger = run_backtest(CFG, conn)
    dc = {b["selection"]: b for b in ledger if b["market"] == "dc"}
    assert set(dc) == {"1X", "X2", "12"}
    assert dc["1X"]["won"] == 1 and dc["1X"]["offered_odd"] == 1.2
    assert dc["X2"]["won"] == 0
    assert dc["12"]["won"] == 1 and dc["12"]["offered_odd"] == 1.4


def test_double_chance_swap_orientation(conn):
    # Sofascore gravou INVERTIDO: home=Serbia, away=Brazil. martj42 diz Brazil
    # mandante. A odd de DC "1X" (Brazil-ou-empate) tem que vir do dc_x2 do
    # Sofascore (Serbia-away-ou-empate = Brazil-ou-empate). dc_1x=9.9 distingue.
    _setup(conn, home="Serbia", away="Brazil", hs=0, as_=2,  # placar na orient. sofascore
           dc={"1X": 9.99, "X2": 1.23, "12": 1.4})
    # martj42: Brazil venceu (away no banco sofascore, home no matches)
    conn.execute("UPDATE matches SET home_team='Brazil', away_team='Serbia', "
                 "home_score=2, away_score=0 WHERE home_team='Serbia'")
    conn.commit()
    _params, ledger = run_backtest(CFG, conn)
    dc = {b["selection"]: b for b in ledger if b["market"] == "dc"}
    # 1X de Brazil = dc_x2 do Sofascore (1.23), NÃO o dc_1x (9.99)
    assert dc["1X"]["offered_odd"] == 1.23
    assert dc["1X"]["won"] == 1            # Brazil-ou-empate, Brazil venceu


# ------------------------------------------------------------------ #
# OU multi-linha: meia entra, inteira e AH são excluídas              #
# ------------------------------------------------------------------ #

def test_ou_half_lines_settled(conn):
    # total = 2 gols → over 1.5 ganha, under 3.5 ganha
    _setup(conn, ou_lines={1.5: (1.4, 3.0), 3.5: (4.3, 1.2)})
    _params, ledger = run_backtest(CFG, conn)
    mkts = {b["market"] for b in ledger}
    assert "ou1.5" in mkts and "ou3.5" in mkts
    ou15 = {b["selection"]: b for b in ledger if b["market"] == "ou1.5"}
    assert ou15["over"]["won"] == 1        # 2 > 1.5
    ou35 = {b["selection"]: b for b in ledger if b["market"] == "ou3.5"}
    assert ou35["under"]["won"] == 1       # 2 < 3.5


def test_integer_line_and_2_5_excluded(conn):
    # linha inteira 2.0 (push possível → 4b) e a 2.5 (bloco legado) NÃO entram
    # pelo caminho estendido
    _setup(conn, ou_lines={2.0: (1.9, 1.9), 2.5: (2.0, 1.8)})
    _params, ledger = run_backtest(CFG, conn)
    mkts = {b["market"] for b in ledger}
    assert "ou2.0" not in mkts             # inteira pulada
    assert "ou2" not in mkts


def test_ah_lines_excluded_in_phase_4a(conn):
    _setup(conn, ou_lines={1.5: (1.4, 3.0)})
    db.upsert_odds_lines(conn, [(1, "ah", -0.5, 2.0, 1.8, 2.0, 1.8)])
    _params, ledger = run_backtest(CFG, conn)
    assert not any(b["market"].startswith("ah") for b in ledger)


# ------------------------------------------------------------------ #
# Sem dados estendidos: caminho legado intacto                        #
# ------------------------------------------------------------------ #

def test_no_extended_data_only_legacy_markets(conn):
    _setup(conn)  # sem dc/btts/ou_lines
    _params, ledger = run_backtest(CFG, conn)
    mkts = {b["market"] for b in ledger}
    assert mkts <= {"1x2", "ou25"}         # só os legados
