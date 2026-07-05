"""Os invariantes do banco que blindam o CLV. Usa o db.connect real num
SQLite :memory: — exercita schema, migração e upsert de verdade, sem tocar disco."""
import pytest

from src import db


@pytest.fixture
def conn():
    c = db.connect(":memory:")     # schema + _migrate completos, em memória
    yield c
    c.close()


def _row(event_id, **over):
    """Linha de upsert de sofascore_matches na ordem do INSERT (20 colunas)."""
    base = dict(
        event_id=event_id, competition="WC", season="2026", date="2026-06-20",
        home_team="Brazil", away_team="Serbia", home_score=None, away_score=None,
        home_xg=None, away_xg=None,
        odds_home=2.10, odds_draw=3.30, odds_away=3.50, odds_over=1.90, odds_under=1.90,
        odds_home_open=2.10, odds_draw_open=3.30, odds_away_open=3.50,
        odds_over_open=1.90, odds_under_open=1.90)
    base.update(over)
    return tuple(base.values())


def test_coalesce_preserva_abertura(conn):
    # 1ª coleta (T-72h): open == close. 2ª coleta (apito): close move, open=None
    # (passada pós-jogo não conhece abertura). O COALESCE tem que manter o open.
    db.upsert_ss_matches(conn, [_row(1)])
    db.upsert_ss_matches(conn, [_row(
        1, home_score=2, away_score=0,
        odds_home=2.60, odds_draw=3.60, odds_away=2.80,    # fechamento mexeu
        odds_home_open=None, odds_draw_open=None, odds_away_open=None,
        odds_over_open=None, odds_under_open=None)])

    oh, oh_open = conn.execute(
        "SELECT odds_home, odds_home_open FROM sofascore_matches "
        "WHERE event_id=1").fetchone()
    assert oh == 2.60          # close: última leitura vence
    assert oh_open == 2.10     # open: write-once, primeira foto preservada


def test_close_sempre_sobrescreve(conn):
    db.upsert_ss_matches(conn, [_row(2, odds_under=1.80)])
    db.upsert_ss_matches(conn, [_row(2, odds_under=1.55, odds_under_open=None)])
    ou = conn.execute(
        "SELECT odds_under FROM sofascore_matches WHERE event_id=2").fetchone()[0]
    assert ou == 1.55


def test_upsert_resolve_placeholder_de_bracket_para_nome_real(conn):
    """Bug real: a 1ª coleta grava o evento com placeholder de bracket
    ('W83'/'W84', antes do Sofascore saber quem classificou); a 2ª coleta do
    MESMO event_id já traz o nome resolvido ('Mexico'/'England'). Sem
    home_team/away_team no ON CONFLICT DO UPDATE, o upsert mantinha o
    placeholder da 1ª coleta pra sempre — parecia atraso do Sofascore, era o
    upsert descartando o nome novo."""
    db.upsert_ss_matches(conn, [_row(20, home_team="W83", away_team="W84")])
    db.upsert_ss_matches(conn, [_row(20, home_team="Mexico", away_team="England",
                                     odds_home=2.05)])
    home, away = conn.execute(
        "SELECT home_team, away_team FROM sofascore_matches WHERE event_id=20").fetchone()
    assert (home, away) == ("Mexico", "England")


def test_snapshots_idempotentes(conn):
    snap = (10, "2026-06-17T10:00:00Z", "1x2", "home", 2.10, 1)
    n1 = db.insert_snapshots(conn, [snap])
    n2 = db.insert_snapshots(conn, [snap])      # mesma PK → ignorado
    assert n1 == 1
    assert n2 == 0
    total = conn.execute(
        "SELECT COUNT(*) FROM odds_snapshots WHERE event_id=10").fetchone()[0]
    assert total == 1


def test_snapshots_acumulam_no_tempo(conn):
    # captures distintos (timestamps diferentes) = série temporal, não duplicata.
    db.insert_snapshots(conn, [(11, "2026-06-17T10:00:00Z", "1x2", "home", 2.10, 1)])
    db.insert_snapshots(conn, [(11, "2026-06-19T10:00:00Z", "1x2", "home", 2.35, 1)])
    n = conn.execute(
        "SELECT COUNT(*) FROM odds_snapshots WHERE event_id=11").fetchone()[0]
    assert n == 2
