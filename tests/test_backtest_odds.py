"""Gap #1 da auditoria: _find_odds/_canon — o casamento odds↔jogo e o SWAP de
orientação 1X2 quando home/away divergem entre Sofascore e martj42. Um bug aqui
aposta na odd do time errado SEM exceção: ledger plausível, P&L/CLV lixo.

Usa db.connect(":memory:") real (schema + migração + upsert verdadeiros) e o
_load_odds real — nada de schema manual, nada de disco."""
import pytest

from src import db
from src.backtest import _find_odds, _load_odds, run_backtest
from src.math_utils import shin_probabilities

# Linha de sofascore_matches na ordem do INSERT (20 colunas). Odds distintas em
# cada slot pra qualquer troca de orientação ficar visível na asserção.
def _ss_row(event_id, home, away, date, **over):
    base = dict(
        event_id=event_id, competition="WC", season="2026", date=date,
        home_team=home, away_team=away, home_score=None, away_score=None,
        home_xg=None, away_xg=None,
        odds_home=2.80, odds_draw=3.40, odds_away=2.50,
        odds_over=1.90, odds_under=1.95,
        odds_home_open=2.90, odds_draw_open=3.30, odds_away_open=2.40,
        odds_over_open=1.85, odds_under_open=2.00)
    base.update(over)
    return tuple(base.values())


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    yield c
    c.close()


# ------------------------------------------------------------- swap 1X2
def test_swap_orienta_odd_pro_time_certo(conn):
    # Sofascore gravou o confronto INVERTIDO: home=Serbia, away=Brazil.
    # martj42 diz Brazil mandante. A odd "home" devolvida tem que ser a do
    # Brasil (odds_away do Sofascore), close E open.
    db.upsert_ss_matches(conn, [_ss_row(1, "Serbia", "Brazil", "2026-06-20")])
    found = _find_odds(_load_odds(conn), "Brazil", "Serbia", "2026-06-20")
    assert found is not None
    close_1x2, close_ou, open_1x2, open_ou = found
    assert close_1x2 == (2.50, 3.40, 2.80)   # Brazil, empate, Serbia
    assert open_1x2 == (2.40, 3.30, 2.90)
    assert close_ou == (1.90, 1.95)          # total de gols não tem orientação
    assert open_ou == (1.85, 2.00)


def test_sem_swap_quando_orientacao_coincide(conn):
    db.upsert_ss_matches(conn, [_ss_row(1, "Brazil", "Serbia", "2026-06-20")])
    close_1x2, _, open_1x2, _ = _find_odds(
        _load_odds(conn), "Brazil", "Serbia", "2026-06-20")
    assert close_1x2 == (2.80, 3.40, 2.50)
    assert open_1x2 == (2.90, 3.30, 2.40)


def test_swap_fim_a_fim_no_ledger(conn):
    # A prova inteira: martj42 registra Brazil 2-0 Serbia; o Sofascore tem o
    # confronto invertido. A aposta 'home' do ledger tem que carregar a odd do
    # BRASIL (open 2.40) e liquidar como vitória. Se o swap quebrar, ela sai
    # com a odd da Sérvia (2.90) — ledger plausível, P&L lixo.
    cfg = {"elo": {"initial_rating": 1500, "home_advantage": 100,
                   "k_factors": {"default": 30, "Friendly": 20}},
           "model": {"max_goals": 8},
           "backtest": {"min_edge": -1.0, "max_edge": 1.0, "over_under_line": 2.5}}
    conn.execute(
        "INSERT INTO matches (date, home_team, away_team, home_score, away_score,"
        " tournament, city, country, neutral) "
        "VALUES ('2026-06-20','Brazil','Serbia',2,0,'Friendly','','',0)")
    conn.commit()
    db.upsert_ss_matches(conn, [_ss_row(1, "Serbia", "Brazil", "2026-06-20")])

    _params, ledger = run_backtest(cfg, conn)
    bets = {b["selection"]: b for b in ledger if b["market"] == "1x2"}
    assert bets["home"]["offered_odd"] == 2.40   # abertura do Brasil
    assert bets["home"]["odd_close"] == 2.50     # fechamento do Brasil
    assert bets["home"]["bet_at"] == "open"
    assert bets["home"]["won"] == 1
    assert bets["away"]["offered_odd"] == 2.90   # abertura da Sérvia
    assert bets["away"]["won"] == 0
    over = next(b for b in ledger if b["market"] == "ou25" and b["selection"] == "over")
    assert over["offered_odd"] == 1.85           # OU intocado pelo swap


# ------------------------------------------------------------- reconciliação de nomes
def test_alias_reconcilia_south_korea(conn):
    # martj42 "South Korea" ↔ Sofascore "Korea Republic": _canon mapeia os dois
    # pra "korea republic" e o confronto casa.
    db.upsert_ss_matches(conn, [_ss_row(1, "Korea Republic", "Ghana", "2026-06-20")])
    assert _find_odds(_load_odds(conn), "South Korea", "Ghana", "2026-06-20") is not None


def test_alias_reconcilia_united_states(conn):
    db.upsert_ss_matches(conn, [_ss_row(1, "USA", "Wales", "2026-06-20")])
    assert _find_odds(_load_odds(conn), "United States", "Wales", "2026-06-20") is not None


def test_nome_nao_mapeado_nao_casa(conn):
    # Variante de nome fora do _ALIASES não casa — comportamento correto (não
    # inventamos casamento); o que era bug era o SILÊNCIO, coberto pelo teste
    # de aviso de odds órfãs abaixo.
    db.upsert_ss_matches(conn, [_ss_row(1, "Türkiye", "Georgia", "2026-06-20")])
    assert _find_odds(_load_odds(conn), "Turkey", "Georgia", "2026-06-20") is None


def test_odds_orfas_geram_aviso(conn, capsys):
    # O conserto do buraco silencioso: odds cujo par de nomes não existe na
    # base martj42 agora são contadas e nomeadas no stdout do backtest — a
    # perda de amostra fica visível pro operador expandir o _ALIASES.
    cfg = {"elo": {"initial_rating": 1500, "home_advantage": 100,
                   "k_factors": {"default": 30, "Friendly": 20}},
           "model": {"max_goals": 8},
           "backtest": {"min_edge": -1.0, "max_edge": 1.0, "over_under_line": 2.5}}
    conn.execute(
        "INSERT INTO matches (date, home_team, away_team, home_score, away_score,"
        " tournament, city, country, neutral) "
        "VALUES ('2026-06-20','Turkey','Georgia',1,0,'Friendly','','',0)")
    conn.commit()
    db.upsert_ss_matches(conn, [_ss_row(1, "Türkiye", "Georgia", "2026-06-20")])
    run_backtest(cfg, conn)
    out = capsys.readouterr().out
    assert "não reconciliados" in out
    assert "türkiye" in out


# ------------------------------------------------------------- tolerância de data
def test_data_dentro_de_3_dias_casa(conn):
    db.upsert_ss_matches(conn, [_ss_row(1, "Brazil", "Serbia", "2026-06-17")])
    assert _find_odds(_load_odds(conn), "Brazil", "Serbia", "2026-06-20") is not None


def test_data_alem_de_3_dias_nao_casa(conn):
    # 4 dias de distância: candidato descartado calado (mesma classe de silêncio
    # do nome não mapeado).
    db.upsert_ss_matches(conn, [_ss_row(1, "Brazil", "Serbia", "2026-06-16")])
    assert _find_odds(_load_odds(conn), "Brazil", "Serbia", "2026-06-20") is None


def test_data_invalida_descartada_calada(conn):
    # Sofascore sem startTimestamp ⇒ date NULL no banco; date.fromisoformat
    # estoura, o except engole e o candidato some sem log.
    db.upsert_ss_matches(conn, [_ss_row(1, "Brazil", "Serbia", None)])
    assert _find_odds(_load_odds(conn), "Brazil", "Serbia", "2026-06-20") is None


def test_candidato_mais_proximo_na_data_vence(conn):
    # Dois jogos do mesmo par a 2 e a 0 dias do alvo: o mais próximo ganha.
    db.upsert_ss_matches(conn, [
        _ss_row(1, "Brazil", "Serbia", "2026-06-18", odds_home=9.99),
        _ss_row(2, "Brazil", "Serbia", "2026-06-20", odds_home=2.80)])
    close_1x2, _, _, _ = _find_odds(_load_odds(conn), "Brazil", "Serbia", "2026-06-20")
    assert close_1x2[0] == 2.80


# ------------------------------------------------------------- mercado parcial
def test_mercado_parcial_pula_o_mercado_nao_o_jogo(conn, capsys):
    # _load_odds só exige odds_home IS NOT NULL; o parser pode gravar mercado
    # parcial (frac malformada numa seleção ⇒ None). Antes do conserto, UMA
    # linha assim matava o run_backtest inteiro com TypeError dentro do Shin.
    # Agora: o 1X2 parcial é pulado COM AVISO e o resto do jogo (OU íntegro)
    # segue apostável.
    cfg = {"elo": {"initial_rating": 1500, "home_advantage": 100,
                   "k_factors": {"default": 30, "Friendly": 20}},
           "model": {"max_goals": 8},
           "backtest": {"min_edge": -1.0, "max_edge": 1.0, "over_under_line": 2.5}}
    conn.execute(
        "INSERT INTO matches (date, home_team, away_team, home_score, away_score,"
        " tournament, city, country, neutral) "
        "VALUES ('2026-06-20','Brazil','Serbia',2,0,'Friendly','','',0)")
    conn.commit()
    db.upsert_ss_matches(conn, [_ss_row(
        1, "Brazil", "Serbia", "2026-06-20",
        odds_draw=None,                      # 1X2 incompleto
        odds_home_open=None, odds_draw_open=None, odds_away_open=None)])

    _params, ledger = run_backtest(cfg, conn)
    assert all(b["market"] == "ou25" for b in ledger)    # nada de 1X2 capenga
    assert any(b["market"] == "ou25" for b in ledger)    # OU do jogo sobreviveu
    assert "parcial" in capsys.readouterr().out          # e a perda foi anunciada


def test_shin_estoura_com_odd_none():
    # O porquê do guard acima: shin não tolera None na lista — quem deixa
    # mercado parcial chegar nele derruba o processo.
    with pytest.raises(TypeError):
        shin_probabilities([2.5, None, 3.0])
