"""Testes do schema estendido (Fase 1): odds_lines, colunas flat, migração.

Tudo em SQLite :memory: — sem rede, sem arquivo. Cobre:
  - migração aditiva (banco antigo ganha as colunas/tabela novas, dados intactos)
  - backfill da linha OU 2.5 legada → odds_lines
  - write-once das *_open (flat e odds_lines) via COALESCE
  - helper puro lines_rows_from_parsed
"""
import sqlite3

import pytest

from src import db


def _fresh():
    conn = sqlite3.connect(":memory:")
    conn.executescript(db.SCHEMA)
    db._migrate(conn)
    return conn


# ------------------------------------------------------------------ #
# Migração a partir de um banco "antigo"                             #
# ------------------------------------------------------------------ #

def test_migration_adds_flat_columns_to_old_db():
    conn = sqlite3.connect(":memory:")
    # schema ANTIGO: sofascore_matches só com as colunas originais
    conn.execute("""CREATE TABLE sofascore_matches (
        event_id INTEGER PRIMARY KEY, competition TEXT, season TEXT, date TEXT,
        home_team TEXT, away_team TEXT, home_score INTEGER, away_score INTEGER,
        home_xg REAL, away_xg REAL, odds_home REAL, odds_draw REAL, odds_away REAL,
        odds_over REAL, odds_under REAL)""")
    conn.execute("INSERT INTO sofascore_matches (event_id, odds_over, odds_under) "
                 "VALUES (1, 1.9, 1.95)")
    # precisa do resto do schema (odds_lines) para a migração rodar o backfill
    conn.executescript(db.SCHEMA)
    db._migrate(conn)

    cols = {r[1] for r in conn.execute("PRAGMA table_info(sofascore_matches)")}
    for c in db._FLAT_MARKET_COLS:
        assert c in cols, f"coluna {c} não foi adicionada"
    # dado antigo intacto
    assert conn.execute("SELECT odds_over FROM sofascore_matches WHERE event_id=1"
                        ).fetchone()[0] == 1.9


def test_migration_is_idempotent():
    conn = _fresh()
    db._migrate(conn)   # rodar de novo não deve quebrar
    db._migrate(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(sofascore_matches)")}
    assert "odds_btts_yes" in cols


def test_backfill_ou_2_5_into_odds_lines():
    conn = _fresh()
    conn.execute("INSERT INTO sofascore_matches (event_id, odds_over, odds_under, "
                 "odds_over_open, odds_under_open) VALUES (7, 2.1, 1.8, 2.2, 1.75)")
    db._migrate(conn)   # backfill roda aqui
    row = conn.execute("SELECT odd_a, odd_b, odd_a_open, odd_b_open FROM odds_lines "
                       "WHERE event_id=7 AND market='ou' AND line=2.5").fetchone()
    assert row == (2.1, 1.8, 2.2, 1.75)


def test_backfill_skips_when_no_legacy_ou():
    conn = _fresh()
    conn.execute("INSERT INTO sofascore_matches (event_id) VALUES (9)")
    db._migrate(conn)
    n = conn.execute("SELECT COUNT(*) FROM odds_lines WHERE event_id=9").fetchone()[0]
    assert n == 0


# ------------------------------------------------------------------ #
# Colunas flat: fechamento sobrescreve, abertura write-once          #
# ------------------------------------------------------------------ #

def _insert_event(conn, eid=100):
    conn.execute("INSERT INTO sofascore_matches (event_id, home_team, away_team) "
                 "VALUES (?, 'A', 'B')", (eid,))
    conn.commit()


def test_update_flat_markets_close_and_open():
    conn = _fresh()
    _insert_event(conn)
    close = {"dc": {"1X": 1.2, "X2": 1.9, "12": 1.4},
             "dnb": {"1": 1.25, "2": 3.75},
             "btts": {"Yes": 2.0, "No": 1.7}}
    open_ = {"dc": {"1X": 1.25, "X2": 1.85, "12": 1.45},
             "dnb": {"1": 1.30, "2": 3.50},
             "btts": {"Yes": 2.1, "No": 1.65}}
    db.update_flat_markets(conn, 100, close, open_)
    r = conn.execute("SELECT odds_dc_1x, odds_dnb_home, odds_btts_yes, "
                     "odds_dc_1x_open, odds_btts_yes_open FROM sofascore_matches "
                     "WHERE event_id=100").fetchone()
    assert r == (1.2, 1.25, 2.0, 1.25, 2.1)   # close do parsed_close, open do parsed_open


def test_flat_open_is_write_once():
    conn = _fresh()
    _insert_event(conn)
    # 1ª leitura: abertura (initialFractionalValue) gravada
    db.update_flat_markets(conn, 100, {"btts": {"Yes": 2.0, "No": 1.7}},
                           {"btts": {"Yes": 2.0, "No": 1.7}})
    # 2ª leitura: fechamento muda; abertura ausente (open vazio) → COALESCE preserva
    db.update_flat_markets(conn, 100, {"btts": {"Yes": 1.6, "No": 2.3}}, {})
    r = conn.execute("SELECT odds_btts_yes, odds_btts_yes_open FROM sofascore_matches "
                     "WHERE event_id=100").fetchone()
    assert r[0] == 1.6     # fechamento atualizado
    assert r[1] == 2.0     # abertura preservada (write-once)


def test_flat_open_null_when_absent():
    conn = _fresh()
    _insert_event(conn)
    # abertura ausente (initialFractionalValue não veio) → open fica NULL
    db.update_flat_markets(conn, 100, {"btts": {"Yes": 1.6, "No": 2.3}}, {})
    r = conn.execute("SELECT odds_btts_yes, odds_btts_yes_open FROM sofascore_matches "
                     "WHERE event_id=100").fetchone()
    assert r[0] == 1.6
    assert r[1] is None


# ------------------------------------------------------------------ #
# odds_lines: helper puro + upsert com write-once                    #
# ------------------------------------------------------------------ #

def test_lines_rows_from_parsed_pure():
    close = {"ou": {1.5: {"Over": 1.4, "Under": 3.0},
                    2.5: {"Over": 2.0, "Under": 1.8}},
             "ah": {-0.75: {"home": 2.0, "away": 1.8}}}
    open_ = {"ou": {1.5: {"Over": 1.45, "Under": 2.9},
                    2.5: {"Over": 2.05, "Under": 1.75}},
             "ah": {-0.75: {"home": 2.02, "away": 1.78}}}
    rows = db.lines_rows_from_parsed(42, close, open_)
    assert (42, "ou", 1.5, 1.4, 3.0, 1.45, 2.9) in rows
    assert (42, "ah", -0.75, 2.0, 1.8, 2.02, 1.78) in rows
    assert len(rows) == 3


def test_lines_rows_open_null_when_absent():
    close = {"ou": {2.5: {"Over": 2.0, "Under": 1.8}}}
    rows = db.lines_rows_from_parsed(42, close, {})
    assert rows[0] == (42, "ou", 2.5, 2.0, 1.8, None, None)


def test_upsert_odds_lines_close_overwrites_open_write_once():
    conn = _fresh()
    # abertura (initialFractionalValue)
    db.upsert_odds_lines(conn, db.lines_rows_from_parsed(
        5, {"ou": {2.5: {"Over": 2.0, "Under": 1.8}}},
        {"ou": {2.5: {"Over": 2.0, "Under": 1.8}}}))
    # fechamento depois: odd_a/b mudam, *_open preservados (open ausente)
    db.upsert_odds_lines(conn, db.lines_rows_from_parsed(
        5, {"ou": {2.5: {"Over": 1.7, "Under": 2.1}}}, {}))
    row = conn.execute("SELECT odd_a, odd_b, odd_a_open, odd_b_open FROM odds_lines "
                       "WHERE event_id=5 AND market='ou' AND line=2.5").fetchone()
    assert row == (1.7, 2.1, 2.0, 1.8)   # close novo, open write-once


def test_odds_lines_multiple_lines_coexist():
    conn = _fresh()
    parsed = {"ou": {0.5: {"Over": 1.1, "Under": 7.0},
                     2.5: {"Over": 2.0, "Under": 1.8},
                     6.5: {"Over": 41.0, "Under": 1.0}}}
    db.upsert_odds_lines(conn, db.lines_rows_from_parsed(5, parsed, parsed))
    n = conn.execute("SELECT COUNT(*) FROM odds_lines WHERE event_id=5 AND market='ou'"
                     ).fetchone()[0]
    assert n == 3
