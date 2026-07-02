"""Testes de regressão dos fixes da auditoria 2026-07-02 (P2, P3, P5, P6, P7, P8, P10).

Cada teste trava um bug que existiu de verdade — se voltar, o teste nomeia o
problema. Tudo em banco temporário/memória, sem rede.
"""
import sqlite3

import numpy as np
import pytest

from src.bootstrap import ci_mean, ci_mean_cluster
from src.event_models import fit_event_model, predict_event
from src.model import fit_goal_model, predict_match
from src.ratings import ratings_asof

CFG_ELO = {
    "initial_rating": 1500,
    "home_advantage": 100,
    "k_factors": {"default": 30},
}


# ------------------------------------------------------------------ #
# P5 — max_goals posicional caía em delta_vorp_a                      #
# ------------------------------------------------------------------ #

def test_p5_params_5_elementos_com_deltas_zero_equivale_ao_baseline():
    """Com theta != 0 mas delta_vorp/delta_xg = 0, o resultado deve ser IGUAL
    ao da tupla de 4 params. O bug antigo (max_goals posicional virando
    delta_vorp_a=12) fazia p_win despencar de ~0.51 para ~0.21."""
    p4 = (0.224, 1.06, 0.154, -0.039)
    p5 = (0.224, 1.06, 0.154, -0.039, -0.087)
    r4 = predict_match(100, 0.0, p4, 0.0, max_goals=12)
    r5 = predict_match(100, 0.0, p5, 0.0, max_goals=12)
    assert r5["p_win"] == pytest.approx(r4["p_win"], abs=1e-12)
    assert r5["p_draw"] == pytest.approx(r4["p_draw"], abs=1e-12)


def test_p5_padrao_buggy_documentado():
    """Documenta o modo de falha: max_goals na posição de delta_vorp_a
    corrompe as probabilidades quando theta != 0. Se alguém 'simplificar' a
    assinatura e este teste parar de detectar a divergência, revisar TODOS
    os call-sites de predict_match."""
    p5 = (0.224, 1.06, 0.154, -0.039, -0.087)
    buggy = predict_match(100, 0.0, p5, 0.0, 12)      # 12 → delta_vorp_a!
    right = predict_match(100, 0.0, p5, 0.0, max_goals=12)
    assert abs(buggy["p_win"] - right["p_win"]) > 0.05


# ------------------------------------------------------------------ #
# P10 — MLE avisa não-convergência / parâmetro cravado no bound       #
# ------------------------------------------------------------------ #

def test_p10_history_no_formato_errado_dispara_warning():
    """O bug P1 (history [elo_h, elo_a, hs, as]) passava CALADO: o fit cravava
    a no bound superior e ninguém via. Agora tem que avisar."""
    rng = np.random.default_rng(7)
    buggy_history = [
        (1500 + rng.integers(-100, 100), 1450 + rng.integers(-100, 100),
         int(rng.integers(0, 4)))                     # h[1] ~ 1450 "gols"
        for _ in range(60)
    ]
    with pytest.warns(RuntimeWarning):
        fit_goal_model(buggy_history)


def test_p10_history_saudavel_nao_avisa():
    # dados NB realistas (gols dependem do diff, com overdispersao via mistura
    # gama) — nenhum parametro deve cravar em bound nem falhar convergencia
    rng = np.random.default_rng(7)
    history = []
    for _ in range(300):
        diff = float(rng.normal(0, 250))
        mu_h = np.exp(0.2 + 0.8 * diff / 400.0)
        mu_a = np.exp(0.2 - 0.8 * diff / 400.0)
        lam_h = rng.gamma(shape=6.67, scale=mu_h / 6.67)
        lam_a = rng.gamma(shape=6.67, scale=mu_a / 6.67)
        history.append((diff, int(rng.poisson(lam_h)), int(rng.poisson(lam_a))))
    import warnings as _w
    with _w.catch_warnings():
        _w.simplefilter("error", RuntimeWarning)      # warning vira erro
        params = fit_goal_model(history)
    assert len(params) == 4


# ------------------------------------------------------------------ #
# P3 — ratings_asof é forward-only                                    #
# ------------------------------------------------------------------ #

def test_p3_ratings_asof_nao_enxerga_o_futuro():
    matches = [
        ("2026-01-10", "Brazil", "France", 3, 0, "Friendly", 1),
        ("2026-03-10", "Brazil", "France", 0, 3, "Friendly", 1),
    ]
    snaps = ratings_asof(matches, CFG_ELO, ["2026-01-01", "2026-02-01", "2026-04-01"])
    # antes de qualquer jogo: ninguém tem rating (caller usa default 1500)
    assert snaps["2026-01-01"] == {}
    # entre os jogos: só a vitória do Brasil existe
    assert snaps["2026-02-01"]["Brazil"] > 1500
    assert snaps["2026-02-01"]["France"] < 1500
    # depois dos dois jogos (simétricos): ratings voltam para perto da base,
    # e o snapshot de fevereiro NÃO foi contaminado pelo jogo de março
    assert snaps["2026-04-01"]["Brazil"] < snaps["2026-02-01"]["Brazil"]


# ------------------------------------------------------------------ #
# P6 — cluster bootstrap alarga o IC sob correlação intra-jogo        #
# ------------------------------------------------------------------ #

def test_p6_cluster_ci_mais_largo_que_iid_sob_correlacao():
    """4 'jogos', 5 apostas idênticas por jogo (correlação perfeita): o IC por
    cluster tem que ser mais largo que o iid — o iid finge ter 20 observações
    independentes quando só existem 4."""
    rng_pop = np.random.default_rng(3)
    game_vals = rng_pop.normal(0.0, 0.10, size=4)
    pairs = [(v, g) for g, v in enumerate(game_vals) for _ in range(5)]
    values = [v for v, _g in pairs]

    m_iid, lo_iid, hi_iid = ci_mean(values, 2000, np.random.default_rng(13))
    m_cl, lo_cl, hi_cl = ci_mean_cluster(pairs, 2000, np.random.default_rng(13))
    assert m_cl == pytest.approx(m_iid)
    assert (hi_cl - lo_cl) > (hi_iid - lo_iid)


def test_p6_cluster_degenera_no_iid_com_um_por_cluster():
    vals = [0.1, -0.2, 0.3, 0.05, -0.07]
    pairs = [(v, i) for i, v in enumerate(vals)]
    m_cl, lo_cl, hi_cl = ci_mean_cluster(pairs, 1000, np.random.default_rng(13))
    m_iid, _, _ = ci_mean(vals, 1000, np.random.default_rng(13))
    assert m_cl == pytest.approx(m_iid)
    assert lo_cl <= m_cl <= hi_cl


def test_p6_cluster_amostra_vazia_estoura():
    with pytest.raises(ValueError):
        ci_mean_cluster([], 100, np.random.default_rng(13))


# ------------------------------------------------------------------ #
# P8 — modelo de eventos assimétrico                                  #
# ------------------------------------------------------------------ #

def _synthetic_event_history(n=300, seed=11):
    """Time mais forte gera MAIS eventos: home_event ~ Poisson(exp(1.5+0.4d)),
    away ~ Poisson(exp(1.5-0.4d)), d = elo_diff/1000."""
    rng = np.random.default_rng(seed)
    hist = []
    for _ in range(n):
        diff = float(rng.normal(0, 300))
        d = diff / 1000.0
        hist.append({
            "home_team": "A", "away_team": "B",
            "home_elo": 1500 + diff / 2, "away_elo": 1500 - diff / 2,
            "home_event": int(rng.poisson(np.exp(1.5 + 0.4 * d))),
            "away_event": int(rng.poisson(np.exp(1.5 - 0.4 * d))),
        })
    return hist


def test_p8_lambda_home_diferente_de_away_para_diff_positivo():
    params = fit_event_model(_synthetic_event_history(), "corners",
                             distribution="poisson")
    lam_h, lam_a, _probs = predict_event(1700, 1400, params)
    # o time mais forte tem que produzir mais eventos — a versão simétrica
    # antiga devolvia lam_h == lam_a sempre (b colapsava para ~0)
    assert lam_h > lam_a
    assert params["b"] > 0


def test_p8_b_recupera_o_sinal_gerador():
    params = fit_event_model(_synthetic_event_history(), "corners",
                             distribution="poisson")
    # gerador: 0.4 por 1000 pontos de Elo → 0.16 por unidade de 400 pontos
    # (b agora é na MESMA escala do model.py: diff/400)
    assert params["b"] == pytest.approx(0.16, rel=0.3)


# ------------------------------------------------------------------ #
# P2/P7 — load_event_data filtra período; gatilho usa abertura        #
# ------------------------------------------------------------------ #

@pytest.fixture
def event_db(tmp_path):
    """10 jogos de corners com odds abertura≠fechamento e estatísticas em
    TRÊS períodos (ALL/1ST/2ND) — o bug P2 fazia cada jogo virar 9 linhas."""
    p = tmp_path / "events.db"
    conn = sqlite3.connect(str(p))
    conn.executescript("""
        CREATE TABLE sofascore_matches (
            event_id INTEGER PRIMARY KEY, date TEXT,
            home_team TEXT, away_team TEXT,
            home_score INTEGER, away_score INTEGER);
        CREATE TABLE odds_lines (
            event_id INTEGER, market TEXT, line REAL,
            odd_a REAL, odd_b REAL, odd_a_open REAL, odd_b_open REAL,
            PRIMARY KEY (event_id, market, line));
        CREATE TABLE match_statistics (
            event_id INTEGER, team TEXT, period TEXT, stat_name TEXT, value REAL,
            PRIMARY KEY (event_id, team, period, stat_name));
    """)
    for i in range(1, 11):
        conn.execute("INSERT INTO sofascore_matches VALUES (?,?,?,?,?,?)",
                     (i, f"2026-06-{i:02d}", f"T{i}h", f"T{i}a", 1, 0))
        conn.execute("INSERT INTO odds_lines VALUES (?,?,?,?,?,?,?)",
                     (i, "corners", 8.5, 1.80, 2.00, 1.90, 1.90))
        for team, all_v, h1, h2 in (("home", 6.0, 4.0, 2.0), ("away", 5.0, 1.0, 4.0)):
            conn.execute("INSERT INTO match_statistics VALUES (?,?,?,?,?)",
                         (i, team, "ALL", "Corner kicks", all_v))
            conn.execute("INSERT INTO match_statistics VALUES (?,?,?,?,?)",
                         (i, team, "1ST", "Corner kicks", h1))
            conn.execute("INSERT INTO match_statistics VALUES (?,?,?,?,?)",
                         (i, team, "2ND", "Corner kicks", h2))
    conn.commit()
    return conn


def test_p2_load_event_data_uma_linha_por_jogo_e_so_periodo_all(event_db):
    from src.backtest_event import load_event_data
    data = load_event_data(event_db, "corners", cfg_elo=CFG_ELO)
    # sem o filtro period='ALL' seriam 90 linhas (10 jogos × 3×3 períodos)
    assert len(data) == 10
    assert all(d["home_event"] == 6.0 and d["away_event"] == 5.0 for d in data)
    assert all(d["total_events"] == 11.0 for d in data)


def test_p7_gatilho_e_prob_de_mercado_usam_a_abertura(event_db):
    from src.backtest_event import backtest_event
    out = backtest_event("corners", min_edge=-1.0, max_edge=1.0,
                         conn=event_db)
    assert out["n_trades"] >= 1
    for t in out["trades"]:
        # market_prob veio da odd de ABERTURA (1.90), não do fechamento
        assert t["market_prob"] == pytest.approx(1.0 / t["open_odd"])
        assert t["open_odd"] == pytest.approx(1.90)
