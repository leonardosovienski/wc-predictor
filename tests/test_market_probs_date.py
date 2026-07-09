"""Regressão W1 (auditoria 2026-07-09): _market_probs devolvia o PRIMEIRO
confronto que casasse por nomes, sem olhar a data — e a base real contém pares
repetidos (Argentina x Canada e Mexico x Ecuador, edições 2024 e 2026). O CLV
do settle de dinheiro real podia ser computado contra o fechamento de OUTRO
jogo. Agora: com match_date exige |Δ| <= 3 dias (mesma defesa do
backtest._find_odds); sem data, fica com o de data mais recente.
"""
import sqlite3

import pytest

from src.predict import _market_probs


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.execute("""CREATE TABLE sofascore_matches (
        date TEXT, home_team TEXT, away_team TEXT,
        odds_home REAL, odds_draw REAL, odds_away REAL,
        odds_over REAL, odds_under REAL)""")
    # mesmo par, duas edições com odds bem diferentes (cenário real da base)
    c.executemany(
        "INSERT INTO sofascore_matches VALUES (?,?,?,?,?,?,?,?)",
        [("2024-06-20", "Argentina", "Canada", 1.30, 5.00, 9.00, 1.70, 2.10),
         ("2026-07-15", "Argentina", "Canada", 2.00, 3.20, 3.80, 1.95, 1.85),
         ("2026-07-09", "France", "Morocco", 1.60, 4.00, 6.00, 2.00, 1.80)])
    return c


def test_com_data_escolhe_a_edicao_certa(conn):
    mk_2026 = _market_probs(conn, "Argentina", "Canada", match_date="2026-07-15")
    assert mk_2026["odds_home"] == 2.00
    mk_2024 = _market_probs(conn, "Argentina", "Canada", match_date="2024-06-20")
    assert mk_2024["odds_home"] == 1.30


def test_tolerancia_de_3_dias(conn):
    # timezone/adiamento: 2 dias de distância ainda casa
    mk = _market_probs(conn, "Argentina", "Canada", match_date="2026-07-13")
    assert mk["odds_home"] == 2.00
    # fora da janela: melhor devolver None que o jogo errado
    assert _market_probs(conn, "Argentina", "Canada", match_date="2026-01-01") is None


def test_sem_data_fica_com_o_mais_recente(conn):
    """Antes era ordem arbitrária do SQL; agora é determinístico (edição atual)."""
    mk = _market_probs(conn, "Argentina", "Canada")
    assert mk["odds_home"] == 2.00


def test_orientacao_preservada(conn):
    """Pedir na ordem invertida reorienta as odds de mando."""
    mk = _market_probs(conn, "Canada", "Argentina", match_date="2026-07-15")
    assert mk["odds_home"] == 3.80 and mk["odds_away"] == 2.00


def test_data_ilegivel_nao_trava(conn):
    mk = _market_probs(conn, "France", "Morocco", match_date="quarta-feira")
    assert mk is not None and mk["odds_home"] == 1.60


def test_confronto_inexistente(conn):
    assert _market_probs(conn, "Brazil", "Germany") is None
