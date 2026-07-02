"""ZONA 0 — Teste de Sobrevivência Econômica e Estatística (Go/No-Go da v3).

Percorre a temporada de teste (2023-2024) comparando:
  Base   : Modelo Elo puro  (predict_match sem VORP)
  Híbrido: Elo + VORP delta (predict_match com theta > 0)

Relatório consolidado:
  • P-valor do Teste DM com correção HLN
  • Brier Score Médio e Brier Skill Score (BSS)
  • Curva de Calibração para mercado Over 2.5 gols
  • CLV Simulado (edge médio capturado vs odd de fechamento)
  • Probabilistic Sharpe Ratio (PSR) da curva de P&L via Kelly simplificado
  • Debug isolado por time (--debug-team)

Critério de avanço: superioridade estatística (p < 0.05) E edge econômico positivo.

Uso:
    python -m src.research.survival_test \\
        --db data/matches.db --vorp data/vorp.json \\
        [--theta 0.5] [--debug-team "Athletico Paranaense"] [--kelly-frac 0.25]
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src import db
from src.model import predict_match
from src.math_utils import shin_probabilities
# Métricas de domínio (placar) — de-forkadas do core para src/research (2026-06).
from src.research.score_metrics import (
    log_loss_matrix,
    brier_score_multiclass,
    brier_skill_score,
    diebold_mariano_hln,
)
# PSR é primitiva canônica da plataforma — continua vindo do core vendorizado.
from vendor.predictor_core.stats import probabilistic_sharpe_ratio

TEST_SEASONS = {"2023", "2024"}
MAX_GOALS = 12


# ---------------------------------------------------------------------------
# Construção dos tensores de previsão
# ---------------------------------------------------------------------------

def _one_hot(home_score: int, away_score: int, g: int = MAX_GOALS) -> np.ndarray:
    """One-hot (G,G) — clipa scores além de G-1 na borda."""
    y = np.zeros((g, g), dtype=np.float32)
    y[min(home_score, g - 1), min(away_score, g - 1)] = 1.0
    return y


def _predict_base(elo_a, elo_b, params) -> np.ndarray:
    """Grade (G,G) do modelo base (Elo puro, campo neutro)."""
    res = predict_match(elo_a, elo_b, params, home_adv=0.0)
    return res["grid"].astype(np.float32)


def _predict_hybrid(elo_a, elo_b, params, dvorp_a, dvorp_b, theta) -> np.ndarray:
    """Grade (G,G) do modelo híbrido com injeção de VORP."""
    res = predict_match(
        elo_a, elo_b, params, home_adv=0.0,
        delta_vorp_a=dvorp_a, delta_vorp_b=dvorp_b,
        theta=theta,
    )
    return res["grid"].astype(np.float32)


# ---------------------------------------------------------------------------
# Cálculo de Delta VORP por partida
# ---------------------------------------------------------------------------

def _team_delta_vorp(team, event_id, presence, beta_players, replacement_levels, positions):
    """VORP agregado dos jogadores que participaram para um time em uma partida."""
    players = [
        p for p, (t, _) in presence.get(event_id, {}).items() if t == team
    ]
    if not players:
        return 0.0

    total = 0.0
    for p in players:
        if p in beta_players:
            total += beta_players[p]
        else:
            pos = positions.get(p, "UNKNOWN")
            total += replacement_levels.get(pos, replacement_levels.get("UNKNOWN", 0.0))
    return total


# ---------------------------------------------------------------------------
# Calibração Over 2.5 (vetorizada)
# ---------------------------------------------------------------------------

def calibration_curve_over25(probs: np.ndarray, outcomes: np.ndarray, n_bins: int = 10):
    """Retorna (mean_pred, mean_true, counts) por bin. Vetorizado via np.bincount."""
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    bin_ids = np.digitize(probs, bins[1:-1])   # shape (N,), valores 0..n_bins-1
    counts   = np.bincount(bin_ids, minlength=n_bins)
    sum_pred = np.bincount(bin_ids, weights=probs, minlength=n_bins)
    sum_true = np.bincount(bin_ids, weights=outcomes.astype(float), minlength=n_bins)
    mask = counts > 0
    denom = np.where(mask, counts.astype(float), 1.0)
    mean_pred = np.where(mask, sum_pred / denom, np.nan)
    mean_true = np.where(mask, sum_true / denom, np.nan)
    return mean_pred, mean_true, counts


# ---------------------------------------------------------------------------
# CLV Simulado e P&L Kelly
# ---------------------------------------------------------------------------

def _simulated_clv_and_pnl(
    matches_data,    # list of dicts com probs e odds
    kelly_frac: float = 0.25,
    min_edge: float = 0.02,
):
    """Simula apostas de valor (edge > min_edge) usando Kelly fracionado.
    Retorna (clv_edges, pnl_series) para calcular PSR."""
    clv_edges = []
    pnl_series = []
    bankroll = 1.0

    for m in matches_data:
        p_model = m["p_model_1x2"]   # [p_win, p_draw, p_loss]
        odds_1x2 = m["odds_1x2"]     # [odd_home, odd_draw, odd_away]
        result_idx = m["result_idx"]  # 0=home, 1=draw, 2=away
        shin = m["shin_close"]        # probs purificadas do fechamento

        if any(o is None or o <= 1.0 for o in odds_1x2):
            continue

        # Edge vs preço (com vig) — gatilho correto do backtest existente
        for k in range(3):
            implied = 1.0 / odds_1x2[k]
            edge = p_model[k] - implied
            if edge < min_edge:
                continue

            # CLV = odd_pactuada × p_shin_close − 1
            clv = odds_1x2[k] * shin[k] - 1.0
            clv_edges.append(clv)

            # Kelly simplificado: f* = edge / (odd - 1)
            f = kelly_frac * edge / (odds_1x2[k] - 1.0)
            f = min(f, 0.05)   # cap de 5% do bankroll por aposta

            if result_idx == k:
                ret = f * (odds_1x2[k] - 1.0)
            else:
                ret = -f
            bankroll += bankroll * ret
            pnl_series.append(ret)

    return np.array(clv_edges), np.array(pnl_series)


# ---------------------------------------------------------------------------
# Loop principal
# ---------------------------------------------------------------------------

def run(db_path: str, vorp_path: str | None, theta: float, debug_team: str | None,
        kelly_frac: float):
    conn = db.connect(db_path, read_only=True)
    elo = db.load_elo(conn)
    prow = db.load_params(conn)
    if not elo or not prow:
        sys.exit("cache vazio — rode cron_update_models primeiro")
    params = (prow[0], prow[1], prow[2], prow[3])

    # Carrega artefato VORP (opcional — desativa se não fornecido)
    use_vorp = False
    beta_players, replacement_levels, positions = {}, {}, {}
    if vorp_path:
        artifact = json.loads(Path(vorp_path).read_text())
        beta_players      = artifact["beta_players"]
        replacement_levels = artifact["replacement_levels"]
        use_vorp = True

    # Carrega posições para fallback
    pos_rows = conn.execute(
        "SELECT player, position FROM player_comp_stats WHERE position IS NOT NULL"
    ).fetchall()
    pos_count = {}
    for player, pos in pos_rows:
        pos_count.setdefault(player, {}).setdefault(pos, 0)
        pos_count[player][pos] += 1
    positions = {p: max(d, key=d.get) for p, d in pos_count.items()}

    # Partidas de teste
    rows = conn.execute(
        "SELECT event_id, home_team, away_team, home_score, away_score, "
        "home_xg, away_xg, odds_home, odds_draw, odds_away, season "
        "FROM sofascore_matches "
        "WHERE home_score IS NOT NULL AND away_score IS NOT NULL"
    ).fetchall()
    test_rows = [r for r in rows if r[10] in TEST_SEASONS]

    if not test_rows:
        sys.exit(f"Nenhuma partida encerrada em seasons {TEST_SEASONS}. "
                 "Rode ingest_sofascore com historico (Euro 2024, Copa América 2024, etc.).")

    all_eids = {r[0] for r in test_rows}
    # Presença de jogadores por evento
    presence = {}
    if use_vorp:
        ph = ",".join("?" * len(all_eids))
        pres_rows = conn.execute(
            f"SELECT event_id, player, team, minutes FROM sofascore_player_ratings "
            f"WHERE event_id IN ({ph}) AND minutes > 0", list(all_eids)
        ).fetchall()
        for eid, player, team, minutes in pres_rows:
            presence.setdefault(eid, {})[player] = (team, minutes)

    # Odds de fechamento (para CLV)
    snap_rows = conn.execute(
        f"SELECT event_id, market, selection, odd FROM odds_snapshots "
        f"WHERE event_id IN ({','.join('?'*len(all_eids))}) AND pre_match=1",
        list(all_eids)
    ).fetchall() if all_eids else []
    # última odd pre_match por (event, market, selection) = fechamento
    close_odds = {}
    for eid, mkt, sel, odd in snap_rows:
        close_odds[(eid, mkt, sel)] = odd  # sobrescreve = pega o mais recente

    print(f"\n[survival_test] {len(test_rows)} partidas de teste (seasons {TEST_SEASONS})")

    P_base_list, P_hybrid_list, Y_list = [], [], []
    matches_for_clv = []
    debug_rows = []

    for eid, home, away, hs, as_, hxg, axg, oh, od, oa, _ in test_rows:
        elo_a = elo.get(home, 1500.0)
        elo_b = elo.get(away, 1500.0)

        grid_base = _predict_base(elo_a, elo_b, params)

        dvorp_a = dvorp_b = 0.0
        if use_vorp:
            dvorp_a = _team_delta_vorp(home, eid, presence, beta_players,
                                        replacement_levels, positions)
            dvorp_b = _team_delta_vorp(away, eid, presence, beta_players,
                                        replacement_levels, positions)
        grid_hyb = _predict_hybrid(elo_a, elo_b, params, dvorp_a, dvorp_b, theta)

        y = _one_hot(hs, as_)

        P_base_list.append(grid_base)
        P_hybrid_list.append(grid_hyb)
        Y_list.append(y)

        # Dados para CLV/P&L
        g = MAX_GOALS
        k = np.arange(g)
        totals = k.reshape(-1, 1) + k.reshape(1, -1)
        p_base_over25 = float(grid_base[totals > 2.5].sum())

        p_1x2_base = [
            float(np.tril(grid_base, -1).sum()),
            float(np.trace(grid_base)),
            float(np.triu(grid_base, 1).sum()),
        ]

        # Shin do fechamento
        odds_close = [
            close_odds.get((eid, "1x2", "home"), oh),
            close_odds.get((eid, "1x2", "draw"), od),
            close_odds.get((eid, "1x2", "away"), oa),
        ]
        shin_p = [0.0, 0.0, 0.0]
        if all(o is not None and o > 1.0 for o in odds_close):
            shin_p, _, _ = shin_probabilities(odds_close)

        result_idx = 0 if hs > as_ else (1 if hs == as_ else 2)
        matches_for_clv.append({
            "event_id": eid, "home": home, "away": away,
            "p_model_1x2": p_1x2_base,
            "odds_1x2": [oh, od, oa],
            "result_idx": result_idx,
            "shin_close": list(shin_p),
            "p_over25": p_base_over25,
            "over25_result": int((hs + as_) > 2),
        })

        if debug_team and (debug_team in (home, away)):
            debug_rows.append({
                "event_id": eid, "home": home, "away": away,
                "score": f"{hs}-{as_}",
                "bs_base": float(np.sum((grid_base - y) ** 2)),
                "bs_hyb":  float(np.sum((grid_hyb  - y) ** 2)),
                "dvorp_home": dvorp_a, "dvorp_away": dvorp_b,
            })

    # Tensores (N, G, G)
    P_base   = np.stack(P_base_list)
    P_hybrid = np.stack(P_hybrid_list)
    Y        = np.stack(Y_list)

    # ---------------------------------------------------------------------------
    # Relatório
    # ---------------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("RELATÓRIO — TESTE DE SOBREVIVÊNCIA (Go/No-Go v3)")
    print("=" * 60)

    bs_base = brier_score_multiclass(P_base, Y)
    bs_hyb  = brier_score_multiclass(P_hybrid, Y)
    bss     = brier_skill_score(P_hybrid, P_base, Y)
    ll_base = log_loss_matrix(P_base, Y)
    ll_hyb  = log_loss_matrix(P_hybrid, Y)
    print(f"\n[Brier Score]")
    print(f"  Base    : {bs_base:.5f}")
    print(f"  Híbrido : {bs_hyb:.5f}")
    print(f"  BSS     : {bss:+.4f}  ({'melhora' if bss > 0 else 'piora'} sobre base)")
    print(f"\n[Log-Loss]")
    print(f"  Base    : {ll_base:.5f}")
    print(f"  Híbrido : {ll_hyb:.5f}")

    # Erro por partida para DM (perda quadrática = ||P-Y||²)
    e_base = np.sqrt(np.sum((P_base   - Y) ** 2, axis=(1, 2)))
    e_hyb  = np.sqrt(np.sum((P_hybrid - Y) ** 2, axis=(1, 2)))
    dm_stat, dm_pval = diebold_mariano_hln(e_base, e_hyb, h=1)
    print(f"\n[Teste Diebold-Mariano (HLN)]")
    print(f"  DM_HLN  : {dm_stat:.4f}")
    print(f"  p-valor : {dm_pval:.4f}  " +
          ("*** SIGNIFICATIVO (p<0.05)" if dm_pval < 0.05 else "(não significativo)"))

    # Calibração Over 2.5
    probs_o25   = np.array([m["p_over25"]      for m in matches_for_clv])
    outcomes_o25 = np.array([m["over25_result"] for m in matches_for_clv], dtype=float)
    mp, mt, cnts = calibration_curve_over25(probs_o25, outcomes_o25, n_bins=8)
    print(f"\n[Calibração Over 2.5 — {len(probs_o25)} partidas]")
    print(f"  {'Bin prev':>10}  {'Real':>8}  {'N':>6}")
    for pred, real, cnt in zip(mp, mt, cnts):
        if np.isnan(pred):
            continue
        print(f"  {pred:10.3f}  {real:8.3f}  {cnt:6d}")

    # CLV Simulado e PSR
    clv_edges, pnl = _simulated_clv_and_pnl(matches_for_clv, kelly_frac=kelly_frac)
    print(f"\n[Análise Econômica — Kelly Simplificado (frac={kelly_frac})]")
    if len(clv_edges) > 0:
        print(f"  Apostas simuladas : {len(clv_edges)}")
        print(f"  CLV médio         : {clv_edges.mean():+.4f} ({clv_edges.mean()*100:+.2f}%)")
        print(f"  CLV IC 95% approx : [{np.percentile(clv_edges,2.5):+.4f}, {np.percentile(clv_edges,97.5):+.4f}]")
    else:
        print("  Nenhuma aposta de valor gerada (ajuste min_edge ou theta).")
    if len(pnl) >= 3:
        psr = probabilistic_sharpe_ratio(pnl.tolist(), benchmark_sharpe=0.0)
        print(f"  PSR (P(SR>0))     : {psr:.4f}  " +
              ("*** POSITIVO" if psr > 0.9 else "(insuficiente)"))
    else:
        print("  PSR: n<3 apostas — insuficiente.")

    # Veredito
    print("\n" + "-" * 60)
    estatistica_ok = (dm_pval < 0.05 and bss > 0)
    economico_ok   = len(clv_edges) > 0 and clv_edges.mean() > 0.0
    if estatistica_ok and economico_ok:
        print("VEREDITO: GO ✓ — superioridade estatística E edge econômico positivo.")
    elif estatistica_ok:
        print("VEREDITO: PARCIAL — estatisticamente superior, mas sem edge econômico.")
    elif economico_ok:
        print("VEREDITO: PARCIAL — edge econômico positivo, mas sem significância estatística.")
    else:
        print("VEREDITO: NO-GO — sem superioridade estatística nem edge econômico.")
    print("-" * 60)

    # Debug por time
    if debug_team:
        print(f"\n[DEBUG — {debug_team}] ({len(debug_rows)} jogos)")
        if not debug_rows:
            print("  Nenhum jogo encontrado para este time na amostra de teste.")
        for r in debug_rows:
            delta = r["bs_base"] - r["bs_hyb"]
            print(f"  {r['home']:20} × {r['away']:20}  {r['score']}  "
                  f"ΔBS={delta:+.4f}  ΔVORP=({r['dvorp_home']:+.3f},{r['dvorp_away']:+.3f})")


def main():
    parser = argparse.ArgumentParser(description="Teste de Sobrevivência — v3 Go/No-Go")
    parser.add_argument("--db",         default="data/matches.db")
    parser.add_argument("--vorp",       default=None, help="caminho para data/vorp.json")
    parser.add_argument("--theta",      type=float, default=0.5,
                        help="peso do delta VORP na link function (0 = desativado)")
    parser.add_argument("--debug-team", default=None,
                        help="time para debug isolado (ex: 'Athletico Paranaense')")
    parser.add_argument("--kelly-frac", type=float, default=0.25,
                        help="fração de Kelly para simulação de P&L")
    args = parser.parse_args()

    run(
        db_path=str(ROOT / args.db),
        vorp_path=str(ROOT / args.vorp) if args.vorp else None,
        theta=args.theta,
        debug_team=args.debug_team,
        kelly_frac=args.kelly_frac,
    )


if __name__ == "__main__":
    main()
