# src/backtest_event.py
"""Backtest para mercados de cartões e escanteios (eventos não-gols).

CLV = open_odd / close_odd - 1 (bater o fechamento apostando na abertura).
Edge = model_prob - (1/open_odd): a decisão usa APENAS o que existe no momento
da aposta (abertura) — antes usava a odd de fechamento no gatilho (lookahead,
auditoria P7).

Fixes da auditoria 2026-07-02:
  P2 — o JOIN com match_statistics agora filtra period='ALL'. Sem o filtro,
       cada jogo virava ~9 linhas (ALL/1ST/2ND/ET1/ET2 em produto cartesiano)
       e contagens de 1º tempo eram liquidadas contra linhas de jogo inteiro
       ("898 jogos" documentados eram, na verdade, 98).
  P3 — Elo forward-only por data (ratings_asof), não o current_elo de hoje.
  P6 — bootstrap por CLUSTER de evento (linhas do mesmo jogo são correlacionadas).
  P7 — gatilho de aposta contra a odd de ABERTURA.
  P8 — modelo assimétrico (ver event_models.py).
"""

import sqlite3
import numpy as np
from typing import List, Dict
from src import db
from src.ingest import ROOT, load_config
from src.event_models import fit_event_model, predict_event
from src.predict import _canon
from src.ratings import ratings_asof
from src.obs import get_logger, setup_logging

# Configura logging imediatamente
setup_logging(ROOT / "data")
log = get_logger()


def _forward_elo(conn: sqlite3.Connection, cfg_elo: dict, dates) -> dict:
    """{data: {canon_team: rating}} forward-only a partir da tabela matches.
    Sem tabela matches (fixtures de teste), devolve {} — caller usa 1500."""
    try:
        rows = conn.execute(
            "SELECT date, home_team, away_team, home_score, away_score, "
            "tournament, neutral FROM matches WHERE home_score IS NOT NULL "
            "ORDER BY date").fetchall()
    except sqlite3.OperationalError:
        return {}
    if not rows:
        return {}
    snaps = ratings_asof(rows, cfg_elo, dates)
    return {d: {_canon(t): r for t, r in snap.items()} for d, snap in snaps.items()}


def load_event_data(conn: sqlite3.Connection, market: str,
                    cfg_elo: dict | None = None) -> List[Dict]:
    """Carrega jogos com odds e estatísticas para um mercado de evento."""
    cursor = conn.cursor()

    # Nomes exatos das estatísticas no banco
    if market == 'cards':
        stat_candidates = ['Yellow cards', 'Cards']
    else:  # corners
        stat_candidates = ['Corner kicks', 'Corners']

    rows = []
    used_stat = None

    for stat_name in stat_candidates:
        # period='ALL' nos DOIS joins (auditoria P2): sem isso, períodos
        # parciais entram como jogos e a amostra infla ~9× com dados errados.
        cursor.execute("""
            SELECT
                sm.event_id,
                sm.date,
                sm.home_team,
                sm.away_team,
                sm.home_score,
                sm.away_score,
                ol.line,
                ol.odd_a AS close_a,
                ol.odd_b AS close_b,
                ol.odd_a_open AS open_a,
                ol.odd_b_open AS open_b,
                ms_home.value AS home_event,
                ms_away.value AS away_event
            FROM sofascore_matches sm
            JOIN odds_lines ol ON sm.event_id = ol.event_id AND ol.market = ?
            JOIN match_statistics ms_home ON sm.event_id = ms_home.event_id
                AND ms_home.team = 'home' AND ms_home.stat_name = ?
                AND ms_home.period = 'ALL'
            JOIN match_statistics ms_away ON sm.event_id = ms_away.event_id
                AND ms_away.team = 'away' AND ms_away.stat_name = ?
                AND ms_away.period = 'ALL'
            WHERE sm.home_score IS NOT NULL AND sm.away_score IS NOT NULL
              AND ol.odd_a IS NOT NULL AND ol.odd_b IS NOT NULL
              AND ol.odd_a_open IS NOT NULL AND ol.odd_b_open IS NOT NULL
        """, (market, stat_name, stat_name))

        rows = cursor.fetchall()
        if rows:
            used_stat = stat_name
            log.info(f"Carregados {len(rows)} jogos para {market} usando estatística '{stat_name}'")
            break

    if not rows:
        log.warning(f"Nenhum dado encontrado para {market} com nomes {stat_candidates}")
        return []

    # Elo forward-only por data do evento (auditoria P3) — antes usava o
    # current_elo de HOJE como rating pré-jogo (lookahead).
    if cfg_elo is None:
        cfg_elo = load_config()["elo"]
    dates = {row[1] for row in rows if row[1]}
    elo_by_date = _forward_elo(conn, cfg_elo, dates)

    data = []
    for row in rows:
        (event_id, date, home, away, hg, ag, line, close_a, close_b,
         open_a, open_b, home_event, away_event) = row

        snap = elo_by_date.get(date, {})
        elo_home = snap.get(_canon(home or ""), 1500)
        elo_away = snap.get(_canon(away or ""), 1500)

        data.append({
            'event_id': event_id,
            'date': date,
            'home': home,
            'away': away,
            'line': line,
            'close_a': close_a,
            'close_b': close_b,
            'open_a': open_a,
            'open_b': open_b,
            'home_event': home_event,
            'away_event': away_event,
            'elo_home': elo_home,
            'elo_away': elo_away,
            'total_events': home_event + away_event,
        })
    return data


def _cluster_bootstrap_ci(trades: List[Dict], metric: str, iterations: int,
                          rng) -> tuple:
    """IC 95% da média por cluster bootstrap sobre event_id (auditoria P6):
    linhas do mesmo jogo (linhas múltiplas do mercado) são correlacionadas."""
    groups: dict = {}
    for t in trades:
        groups.setdefault(t['event_id'], []).append(float(t[metric]))
    vals_by_key = [np.asarray(v, dtype=float) for v in groups.values()]
    n = len(vals_by_key)
    means = np.empty(iterations)
    for it in range(iterations):
        idx = rng.integers(0, n, size=n)
        means[it] = np.concatenate([vals_by_key[i] for i in idx]).mean()
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def backtest_event(market: str, min_edge: float = 0.02, max_edge: float = 0.15,
                   stake: float = 1.0, conn: sqlite3.Connection | None = None) -> Dict:
    cfg = load_config()
    if conn is None:
        db_path = ROOT / cfg["database"]
        conn = db.connect(str(db_path), read_only=True)

    data = load_event_data(conn, market, cfg_elo=cfg["elo"])
    if not data:
        log.warning(f"Sem dados para {market}")
        return {}

    data.sort(key=lambda x: x['date'])
    split = int(0.8 * len(data))
    train = data[:split]
    test = data[split:]

    log.info(f"Treino: {len(train)}, Teste: {len(test)}")

    history = [{
        'home_team': d['home'],
        'away_team': d['away'],
        'home_elo': d['elo_home'],
        'away_elo': d['elo_away'],
        'home_event': d['home_event'],
        'away_event': d['away_event']
    } for d in train]

    params = fit_event_model(history, market, distribution='poisson')
    log.info(f"Parâmetros para {market}: a={params['a']:.4f}, b={params['b']:.4f}")

    trades = []
    for d in test:
        lam_h, lam_a, probs = predict_event(d['elo_home'], d['elo_away'], params)
        line = d['line']

        over_prob = probs.get(f'over_{line}', 0.5)
        under_prob = 1 - over_prob

        close_over = d['close_a']
        close_under = d['close_b']
        open_over = d['open_a']
        open_under = d['open_b']

        # Edge contra a ABERTURA (auditoria P7): é o preço da aposta; a odd de
        # fechamento não existe no momento da decisão.
        market_over = 1 / open_over
        market_under = 1 / open_under

        edge_over = over_prob - market_over
        edge_under = under_prob - market_under

        # Decisão de aposta
        if edge_over > min_edge and edge_over < max_edge:
            clv = open_over / close_over - 1
            win = d['total_events'] > line
            trades.append({
                'market': market,
                'event_id': d['event_id'],
                'selection': 'Over',
                'line': line,
                'open_odd': open_over,
                'close_odd': close_over,
                'model_prob': over_prob,
                'market_prob': market_over,
                'edge': edge_over,
                'clv': clv,
                'win': win,
                'profit': stake * (open_over - 1) if win else -stake,
            })
        elif edge_under > min_edge and edge_under < max_edge:
            clv = open_under / close_under - 1
            win = d['total_events'] < line
            trades.append({
                'market': market,
                'event_id': d['event_id'],
                'selection': 'Under',
                'line': line,
                'open_odd': open_under,
                'close_odd': close_under,
                'model_prob': under_prob,
                'market_prob': market_under,
                'edge': edge_under,
                'clv': clv,
                'win': win,
                'profit': stake * (open_under - 1) if win else -stake,
            })

    n_trades = len(trades)
    if n_trades == 0:
        log.warning(f"Nenhuma aposta para {market} (edge thresholds podem estar apertados)")
        return {'n_trades': 0}

    profits = [t['profit'] for t in trades]
    clvs = [t['clv'] for t in trades]
    wins = [t['win'] for t in trades]

    total_profit = sum(profits)
    mean_clv = np.mean(clvs)
    win_rate = sum(wins) / n_trades
    avg_profit = total_profit / n_trades

    # Cluster bootstrap por evento, RNG local (não polui o estado global).
    rng = np.random.default_rng(42)
    clv_lower, clv_upper = _cluster_bootstrap_ci(trades, 'clv', 1000, rng)
    n_events = len({t['event_id'] for t in trades})

    log.info(f"""
    === BACKTEST {market.upper()} ===
    N apostas: {n_trades} ({n_events} jogos distintos)
    Lucro total: {total_profit:.2f} (stake {stake})
    Win rate: {win_rate*100:.1f}%
    CLV médio: {mean_clv:.4f} (IC95 cluster: {clv_lower:.4f} - {clv_upper:.4f})
    Lucro médio por aposta: {avg_profit:.4f}
    """)

    return {
        'market': market,
        'n_trades': n_trades,
        'n_events': n_events,
        'total_profit': total_profit,
        'win_rate': win_rate,
        'mean_clv': mean_clv,
        'clv_lower': clv_lower,
        'clv_upper': clv_upper,
        'avg_profit': avg_profit,
        'trades': trades
    }


if __name__ == "__main__":
    for m in ['corners', 'cards']:
        backtest_event(m, min_edge=0.0, max_edge=0.15, stake=1.0)
