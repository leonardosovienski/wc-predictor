"""Previsão COMPLETA de uma partida — todos os mercados derivaveis, num comando.

Uso:
    python scripts/prever.py Spain Austria              # campo neutro (padrao Copa)
    python scripts/prever.py Brazil France --mando      # com vantagem de mando p/ o 1o time
    python scripts/prever.py Spain Austria --mata-mata  # inclui P(classificar)

Entrega junta: 1X2, P(classificar) [mata-mata], gols esperados, Over/Under
0.5-5.5, BTTS, dupla chance, draw no bet, handicap asiatico, placares exatos,
escanteios e cartoes (modelo de eventos assimetrico + ajuste a media do
torneio), e comparacao com o mercado Shin quando ha odds no banco.

Read-only no banco. Regua: o backtest mostrou CLV -8,7% vs fechamento —
isto e' referencia de cenario, nao sinal de aposta.
"""
import argparse
import math
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from scipy.stats import poisson

from src.model import predict_match
from src import market_pricer as mp
from src.event_models import fit_event_model, predict_event
from src.ingest import load_config
from src.predict import _market_probs


def _conn_ro():
    c = sqlite3.connect(f"file:{ROOT / 'data' / 'matches.db'}?mode=ro", uri=True)
    c.execute("PRAGMA query_only=ON")
    return c


def _event_history(conn, stat_name, elo):
    rows = conn.execute("""
        SELECT sm.home_team, sm.away_team, h.value, a.value
        FROM sofascore_matches sm
        JOIN match_statistics h ON h.event_id=sm.event_id AND h.period='ALL'
          AND h.stat_name=? AND h.team='home'
        JOIN match_statistics a ON a.event_id=sm.event_id AND a.period='ALL'
          AND a.stat_name=? AND a.team='away'
        WHERE sm.home_score IS NOT NULL""", (stat_name, stat_name)).fetchall()
    return [{"home_team": h, "away_team": aw, "home_elo": elo.get(h, 1500),
             "away_elo": elo.get(aw, 1500), "home_event": hv, "away_event": av}
            for h, aw, hv, av in rows]


def _tournament_avg(conn, stat_name, competition="World Cup 2026"):
    row = conn.execute("""
        SELECT AVG(h.value+a.value), COUNT(*)
        FROM sofascore_matches sm
        JOIN match_statistics h ON h.event_id=sm.event_id AND h.period='ALL'
          AND h.stat_name=? AND h.team='home'
        JOIN match_statistics a ON a.event_id=sm.event_id AND a.period='ALL'
          AND a.stat_name=? AND a.team='away'
        WHERE sm.competition=?""", (stat_name, stat_name, competition)).fetchone()
    return row if row and row[1] else (None, 0)


def _print_event_block(nome, conn, stat_name, elo, ta, tb, lines):
    hist = _event_history(conn, stat_name, elo)
    if len(hist) < 30:
        print(f"\n{nome}: dados insuficientes ({len(hist)} jogos)")
        return
    params = fit_event_model(hist, stat_name, distribution="poisson")
    lh, la, probs = predict_event(elo.get(ta, 1500), elo.get(tb, 1500), params)
    lam = lh + la
    print(f"\n{nome} (n={len(hist)} jogos, b={params['b']:+.2f}):"
          f"  {ta} {lh:.1f} + {tb} {la:.1f} = {lam:.1f} esperados")
    print("  modelo:   " + " | ".join(
        f"Ov{ln}: {probs[f'over_{ln}']:.0%}" for ln in lines))
    wc_avg, n_wc = _tournament_avg(conn, stat_name)
    if wc_avg and len(hist) > n_wc:
        base_avg = sum(h["home_event"] + h["away_event"] for h in hist) / len(hist)
        lam_adj = lam * (wc_avg / base_avg)
        print(f"  ajustado ao torneio (media Copa {wc_avg:.1f} vs base {base_avg:.1f}"
              f" -> lambda {lam_adj:.1f}): " + " | ".join(
              f"Ov{ln}: {1 - poisson.cdf(ln, lam_adj):.0%}" for ln in lines))


def main():
    ap = argparse.ArgumentParser(description="Previsao completa de uma partida")
    ap.add_argument("time_a")
    ap.add_argument("time_b")
    ap.add_argument("--mando", action="store_true",
                    help="1o time joga em casa (padrao: campo neutro)")
    ap.add_argument("--mata-mata", action="store_true", dest="ko",
                    help="inclui P(classificar) — empate resolvido por Elo")
    args = ap.parse_args()

    cfg = load_config()
    conn = _conn_ro()
    elo = {t: e for t, e in conn.execute("SELECT team, elo FROM current_elo")}
    prow = conn.execute("SELECT param_a, param_b, param_alpha, param_rho "
                        "FROM model_parameters WHERE id=1").fetchone()
    if not prow:
        sys.exit("cache vazio — rode `python -m src.cron_update_models`")
    params = tuple(prow)

    ta, tb = args.time_a, args.time_b
    for t in (ta, tb):
        if t not in elo:
            sugest = [k for k in elo if t.lower() in k.lower()]
            sys.exit(f"time desconhecido: {t}" +
                     (f" — voce quis dizer {sugest}?" if sugest else ""))

    adv = cfg["elo"]["home_advantage"] if args.mando else 0.0
    r = predict_match(elo[ta], elo[tb], params, adv,
                      max_goals=cfg["model"]["max_goals"])
    g = r["grid"]

    venue = f"mando de {ta}" if args.mando else "campo neutro"
    print(f"{'=' * 62}\n{ta} (Elo {elo[ta]:.0f}) x {tb} (Elo {elo[tb]:.0f}) — {venue}\n{'=' * 62}")

    # 1X2 + mata-mata
    print(f"\n1X2: {ta} {r['p_win']:.1%} | empate {r['p_draw']:.1%} | {tb} {r['p_loss']:.1%}")
    if args.ko:
        p_pen = 1.0 / (1.0 + 10 ** (-(elo[ta] + adv - elo[tb]) / 400.0))
        pa = r["p_win"] + r["p_draw"] * p_pen
        print(f"P(classificar): {ta} {pa:.1%} | {tb} {1 - pa:.1%}"
              f"  (empate no 90' resolvido pela logistica de Elo)")

    # gols
    print(f"\nGols esperados: {r['lambda_a']:.2f} x {r['lambda_b']:.2f} "
          f"(total {r['total_goals']:.2f})")
    print("Over: " + " | ".join(
        f"{ln}: {mp.over_under(g, ln)['Over']:.1%}" for ln in (0.5, 1.5, 2.5, 3.5, 4.5, 5.5)))
    print(f"Ambos marcam: {r['btts']:.1%}")

    # DC / DNB
    dc = mp.double_chance(g)
    dnb = mp.draw_no_bet(g)
    d1, d2 = dnb["1"], dnb["2"]
    print(f"\nDupla chance: 1X {dc['1X']:.1%} | 12 {dc['12']:.1%} | X2 {dc['X2']:.1%}")
    print(f"Draw No Bet: {ta} {d1['win'] / (d1['win'] + d1['lose']):.1%} | "
          f"{tb} {d2['win'] / (d2['win'] + d2['lose']):.1%} (push {d1['push']:.1%})")

    # AH: linhas centradas na supremacia esperada
    center = -round((r["lambda_a"] - r["lambda_b"]) * 4) / 4
    print(f"\nHandicap asiatico (lado {ta}):")
    for off in (-0.5, -0.25, 0.0, 0.25, 0.5):
        line = center + off
        ah = mp.asian_handicap(g, line)
        print(f"  {line:+.2f}: win {ah['win']:.1%} | push {ah['push']:.1%} | "
              f"lose {ah['lose']:.1%}")

    # placares
    top = sorted(((i, j, g[i, j]) for i in range(g.shape[0])
                  for j in range(g.shape[1])), key=lambda x: -x[2])[:8]
    print("\nPlacares mais provaveis: " +
          ", ".join(f"{i}x{j} {p:.1%}" for i, j, p in top))

    # eventos nao-gols
    _print_event_block("Escanteios", conn, "Corner kicks", elo, ta, tb,
                       (7.5, 8.5, 9.5))
    _print_event_block("Cartoes amarelos", conn, "Yellow cards", elo, ta, tb,
                       (2.5, 3.5, 4.5))

    # mercado (se houver odds no banco)
    mk = _market_probs(conn, ta, tb)
    if mk:
        ma, md, mb, over = mk["p_home"], mk["p_draw"], mk["p_away"], mk["overround_1x2"]
        print(f"\nMercado 1X2 (Shin, overround {over:.1%} removido): "
              f"{ta} {ma:.1%} | empate {md:.1%} | {tb} {mb:.1%}")
        print(f"  divergencia modelo-mercado no favorito: {r['p_win'] - ma:+.1%}")
        if mk["odds_over"] and mk["odds_under"]:
            print(f"Mercado O/U 2.5 (Shin, overround {mk['overround_ou25']:.1%} removido): "
                  f"over {mk['p_over']:.1%} | under {mk['p_under']:.1%}")
    else:
        print("\n(sem odds deste confronto no banco — rode ingest_sofascore na rede limpa)")

    print("\nRegua: CLV historico do modelo vs fechamento = -8,7% — referencia de"
          "\ncenario e sanity-check, NAO sinal de aposta (docs/COPA_2026_PLAYBOOK.md).")
    conn.close()


if __name__ == "__main__":
    main()
