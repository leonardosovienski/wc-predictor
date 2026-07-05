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
}


def _canon(name):
    n = name.lower().strip()
    return _ALIASES.get(n, n)


def _market_probs(conn, name_a, name_b):
    """Procura odds entre os dois times no Sofascore (1X2 + Over/Under 2.5) e
    devolve odds cruas + probabilidades de mercado (Shin), orientadas a
    (name_a, name_b). Casa por CONJUNTO de nomes, não por ordem (campo neutro:
    ordem é arbitrária). None se não houver odds para o confronto.

    odds_* são as cruas (para o gatilho de EV vs preço, igual ao backtest:
    P_modelo > 1/odd — NÃO contra Shin, que só mede CLV depois do fato).
    p_* (Shin) ficam só como leitura da "probabilidade real" do mercado."""
    try:
        rows = conn.execute(
            "SELECT home_team, away_team, odds_home, odds_draw, odds_away, "
            "odds_over, odds_under FROM sofascore_matches "
            "WHERE odds_home IS NOT NULL").fetchall()
    except Exception:
        return None
    na, nb = _canon(name_a), _canon(name_b)
    for h, a, oh, od, oa, o_over, o_under in rows:
        if {_canon(h), _canon(a)} != {na, nb}:
            continue
        if _canon(h) != na:              # reorienta pra (a, b) como pedido
            oh, oa = oa, oh
        from .math_utils import shin_probabilities
        p1, _z1, over1 = shin_probabilities([oh, od, oa])
        out = {
            "odds_home": oh, "odds_draw": od, "odds_away": oa,
            "p_home": float(p1[0]), "p_draw": float(p1[1]), "p_away": float(p1[2]),
            "overround_1x2": over1,
            "odds_over": None, "odds_under": None,
            "p_over": None, "p_under": None, "overround_ou25": None,
        }
        if o_over and o_under:
            p2, _z2, over2 = shin_probabilities([o_over, o_under])
            out.update(odds_over=o_over, odds_under=o_under,
                      p_over=float(p2[0]), p_under=float(p2[1]), overround_ou25=over2)
        return out
    return None


def show(name_a, name_b, elo, params, cfg, neutral, conn=None, match_date=None):
    for t in (name_a, name_b):
        if t not in elo:
            sys.exit(f"time desconhecido: {t}")
    adv = 0.0 if neutral else cfg["elo"]["home_advantage"]
    r = model.predict_match(elo[name_a], elo[name_b], params, adv,
                            cfg["model"]["max_goals"])

    mk = _market_probs(conn, name_a, name_b) if conn is not None else None

    # OBRIGATÓRIO: congela o PACOTE COMPLETO da predição no momento em que é feita
    # (append-only). Falha ao gravar é avisada em alto e bom som, mas não derruba o serving.
    try:
        from .prediction_log import log_prediction
        log_prediction(name_a, name_b, neutral, elo[name_a], elo[name_b],
                       params, r, match_date=match_date, market=mk)
    except Exception as e:
        print(f"[AVISO: predição NÃO registrada no log ({e})]", file=sys.stderr)
    venue = "campo neutro" if neutral else f"mando de {name_a}"
    print(f"\n{name_a} (Elo {elo[name_a]:.0f}) vs {name_b} (Elo {elo[name_b]:.0f}) — {venue}")
    print(f"  gols esperados: {r['lambda_a']:.2f} x {r['lambda_b']:.2f}  (total {r['total_goals']:.2f})")
    print(f"  modelo  1X2: {name_a} {r['p_win']:.1%} | empate {r['p_draw']:.1%} | {name_b} {r['p_loss']:.1%}")
    print(f"  over 1.5: {r['over'][1.5]:.1%} | over 2.5: {r['over'][2.5]:.1%} | over 3.5: {r['over'][3.5]:.1%}")
    print(f"  ambos marcam: {r['btts']:.1%}")
    print("  placares mais prováveis: " +
          ", ".join(f"{i}x{j} ({p:.1%})" for (i, j), p in r["top_scores"]))

    if conn is not None and mk:
        bt = cfg.get("backtest", {})
        min_edge, max_edge = float(bt.get("min_edge", 0.0)), float(bt.get("max_edge", 1.0))

        print(f"  mercado 1X2: {name_a} {mk['p_home']:.1%} | empate {mk['p_draw']:.1%} | "
              f"{name_b} {mk['p_away']:.1%}  (Shin, overround {mk['overround_1x2']:.1%} removido)")
        # gatilho = EV ao PREÇO ofertado (1/odd) de CADA seleção, igual ao
        # backtest — NÃO contra o Shin (que só mede CLV depois do fato) e NÃO
        # inferido invertendo o sinal de outro lado: o vig não se reparte igual
        # entre as pontas, então cada seleção precisa da própria conta.
        for lado, p_model, odd in ((name_a, r["p_win"], mk["odds_home"]),
                                   ("empate", r["p_draw"], mk["odds_draw"]),
                                   (name_b, r["p_loss"], mk["odds_away"])):
            edge = p_model - (1.0 / odd)
            if min_edge < edge <= max_edge:
                print(f"  >> edge 1X2 de {edge:.1%} em {lado} vs preço ofertado "
                      f"(mercado historicamente NEGATIVO aqui — ver bootstrap antes de apostar)")

        if mk["odds_over"] and mk["odds_under"]:
            print(f"  mercado O/U 2.5: over {mk['p_over']:.1%} | under {mk['p_under']:.1%}"
                  f"  (Shin, overround {mk['overround_ou25']:.1%} removido)")
            p_over = r["over"][2.5]
            for lado, p_model, odd in (("Over", p_over, mk["odds_over"]),
                                       ("Under", 1.0 - p_over, mk["odds_under"])):
                edge = p_model - (1.0 / odd)
                if min_edge < edge <= max_edge:
                    print(f"  >> edge O/U de {edge:.1%} em {lado} vs preço ofertado "
                          f"(único mercado com CLV positivo comprovado no backtest)")


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
            show(h, a, elo, params, cfg, bool(n), conn, match_date=date)
        return

    if len(args.teams) != 2:
        ap.error("informe TIME_A TIME_B, ou use --fixtures/--rankings")
    show(args.teams[0], args.teams[1], elo, params, cfg, args.neutral, conn)


if __name__ == "__main__":
    main()
