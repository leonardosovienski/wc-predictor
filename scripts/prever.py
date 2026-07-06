"""Previsão COMPLETA de uma partida — todos os mercados derivaveis, num comando.

Uso:
    python scripts/prever.py Spain Austria              # campo neutro (padrao Copa)
    python scripts/prever.py Brazil France --mando      # com vantagem de mando p/ o 1o time
    python scripts/prever.py Spain Austria --mata-mata  # inclui P(classificar)
    python scripts/prever.py Spain Austria --json       # machine-output

Entrega o pacote completo (Nivel 3 / --full de src/display.py) mais dois
extras exclusivos deste script: P(classificar) em mata-mata e escanteios/
cartoes (modelo de eventos, exige historico via `conn` que src/predict.py
nao consulta). Cálculo e exibição dos mercados de gol vêm de
`src/display.py` — mesma fonte que `python -m src.predict` usa, sem
duplicação.

Read-only no banco. CLV histórico exibido vem do cache gravado por
`python -m src.bootstrap` (não é mais hardcoded no código-fonte).
"""
import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from scipy.stats import poisson

from src import display
from src.event_models import fit_event_model, predict_event
from src.ingest import load_config


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
    ap.add_argument("--json", action="store_true",
                    help="saida estruturada (machine-output)")
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

    # todo o calculo + as 4 camadas de exibicao (Nivel 0..3) vem do mesmo
    # modulo que src/predict.py usa — ver src/display.py. O que fica so
    # aqui e' o que so o prever.py tem: mata-mata, escanteios/cartoes
    # (precisam de historico via conn, que predict.py nao consulta).
    data = display.compute(ta, tb, elo, params, cfg, neutral=not args.mando, conn=conn)
    display.render(data, level=3, as_json=args.json)
    if args.json:
        conn.close()
        return

    if args.ko:
        adv = cfg["elo"]["home_advantage"] if args.mando else 0.0
        p_pen = 1.0 / (1.0 + 10 ** (-(elo[ta] + adv - elo[tb]) / 400.0))
        pa = data["core"]["p_win"] + data["core"]["p_draw"] * p_pen
        print(f"\nP(classificar): {ta} {pa:.1%} | {tb} {1 - pa:.1%}"
              f"  (empate no 90' resolvido pela logistica de Elo)")

    # eventos nao-gols: exclusivo do prever.py, exige historico de
    # match_statistics que so este script consulta.
    _print_event_block("Escanteios", conn, "Corner kicks", elo, ta, tb,
                       (7.5, 8.5, 9.5))
    _print_event_block("Cartoes amarelos", conn, "Yellow cards", elo, ta, tb,
                       (2.5, 3.5, 4.5))

    conn.close()


if __name__ == "__main__":
    main()
