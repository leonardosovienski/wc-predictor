import argparse
import sys

from . import db, model
from .ingest import ROOT, load_config


def build(cfg):
    """Serving instantâneo: lê Elo e parâmetros do cache. Sem cache, calcula
    on-the-fly uma vez e avisa. Detecta cache velho (config ou dados mudaram)."""
    conn = db.connect(str(ROOT / cfg["database"]))
    elo = db.load_elo(conn)
    prow = db.load_params(conn)

    if not elo or not prow:
        print("[cache vazio — calculando agora; rode `python -m src.cron_update_models` "
              "para tornar a CLI instantânea]", file=sys.stderr)
        from .cron_update_models import compute
        out = compute(cfg, conn)
        if not out:
            sys.exit("banco vazio — rode `python -m src.ingest` primeiro")
        elo, params, _ = out
        return conn, elo, params

    a, b, alpha, rho, n_cached, cfg_hash, computed_at = prow
    from .cron_update_models import config_hash
    n_now = conn.execute(
        "SELECT COUNT(*) FROM matches WHERE home_score IS NOT NULL").fetchone()[0]
    if cfg_hash != config_hash(cfg) or n_cached != n_now:
        print("[cache desatualizado (config ou dados mudaram) — rode "
              "`python -m src.cron_update_models`]", file=sys.stderr)
    return conn, elo, (a, b, alpha, rho)


_ALIASES = {
    "south korea": "korea republic", "united states": "usa",
    "ir iran": "iran", "china pr": "china", "czechia": "czech republic",
    "cabo verde": "cape verde", "côte d'ivoire": "ivory coast",
    "bosnia & herzegovina": "bosnia and herzegovina",  # Sofascore usa '&', base usa 'and'
}


def _canon(name):
    n = name.lower().strip()
    return _ALIASES.get(n, n)


def _market_probs(conn, name_a, name_b):
    """Procura odds entre os dois times no Sofascore e devolve as probabilidades
    reais de mercado (Shin) na ordem (a, empate, b). None se não houver odds."""
    try:
        rows = conn.execute(
            "SELECT home_team, away_team, odds_home, odds_draw, odds_away "
            "FROM sofascore_matches WHERE odds_home IS NOT NULL").fetchall()
    except Exception:
        return None
    na, nb = _canon(name_a), _canon(name_b)
    for h, a, oh, od, oa in rows:
        if {_canon(h), _canon(a)} == {na, nb}:
            from .math_utils import shin_probabilities
            p, _z, over = shin_probabilities([oh, od, oa])
            if _canon(h) == na:
                return float(p[0]), float(p[1]), float(p[2]), over
            return float(p[2]), float(p[1]), float(p[0]), over
    return None


def show(name_a, name_b, elo, params, cfg, neutral, conn=None):
    for t in (name_a, name_b):
        if t not in elo:
            sys.exit(f"time desconhecido: {t}")
    adv = 0.0 if neutral else cfg["elo"]["home_advantage"]
    r = model.predict_match(elo[name_a], elo[name_b], params, adv,
                            cfg["model"]["max_goals"])
    venue = "campo neutro" if neutral else f"mando de {name_a}"
    print(f"\n{name_a} (Elo {elo[name_a]:.0f}) vs {name_b} (Elo {elo[name_b]:.0f}) — {venue}")
    print(f"  gols esperados: {r['lambda_a']:.2f} x {r['lambda_b']:.2f}  (total {r['total_goals']:.2f})")
    print(f"  modelo  1X2: {name_a} {r['p_win']:.1%} | empate {r['p_draw']:.1%} | {name_b} {r['p_loss']:.1%}")
    print(f"  over 1.5: {r['over'][1.5]:.1%} | over 2.5: {r['over'][2.5]:.1%} | over 3.5: {r['over'][3.5]:.1%}")
    print(f"  ambos marcam: {r['btts']:.1%}")
    print("  placares mais prováveis: " +
          ", ".join(f"{i}x{j} ({p:.1%})" for (i, j), p in r["top_scores"]))

    if conn is not None:
        mk = _market_probs(conn, name_a, name_b)
        if mk:
            ma, md, mb, over = mk
            print(f"  mercado 1X2: {name_a} {ma:.1%} | empate {md:.1%} | {name_b} {mb:.1%}"
                  f"  (Shin, overround {over:.1%} removido)")
            edge = r["p_win"] - ma
            if abs(edge) >= 0.05:
                lado = name_a if edge > 0 else name_b
                print(f"  >> divergência de {abs(edge):.1%} em {lado} — investigar "
                      f"(modelo {'acima' if edge > 0 else 'abaixo'} do mercado)")


def main():
    ap = argparse.ArgumentParser(description="Preditor de partidas internacionais")
    ap.add_argument("teams", nargs="*", help="TIME_A TIME_B (em inglês, ex: Brazil)")
    ap.add_argument("--neutral", action="store_true", help="campo neutro")
    ap.add_argument("--fixtures", type=int, metavar="N",
                    help="prevê os próximos N fixtures da base")
    ap.add_argument("--rankings", type=int, metavar="N", help="top N do Elo")
    args = ap.parse_args()

    cfg = load_config()
    conn, elo, params = build(cfg)

    if args.rankings:
        for i, (t, r) in enumerate(sorted(elo.items(), key=lambda x: -x[1])[:args.rankings], 1):
            print(f"{i:>3}. {t:<20} {r:.0f}")
        return

    if args.fixtures:
        rows = conn.execute(
            """SELECT date, home_team, away_team, neutral FROM matches
               WHERE home_score IS NULL ORDER BY date LIMIT ?""",
            (args.fixtures,)).fetchall()
        for date, h, a, n in rows:
            print(f"\n[{date}]", end="")
            show(h, a, elo, params, cfg, bool(n), conn)
        return

    if len(args.teams) != 2:
        ap.error("informe TIME_A TIME_B, ou use --fixtures/--rankings")
    show(args.teams[0], args.teams[1], elo, params, cfg, args.neutral, conn)


if __name__ == "__main__":
    main()
