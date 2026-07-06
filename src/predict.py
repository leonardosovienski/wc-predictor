import argparse
import sys

from . import db, model
from .ingest import ROOT, load_config
from predictor_core.obs import emit_event

_DOMAIN = "wc"


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
    """Procura odds entre os dois times no Sofascore (1X2 + Over/Under 2.5) e
    devolve odds cruas + probabilidades de mercado (Shin), orientadas a
    (name_a, name_b). None se não houver odds para o confronto.

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


def show(name_a, name_b, elo, params, cfg, neutral, conn=None, match_date=None,
        level=0, as_json=False, quiet=False, corners=False, cards=False):
    """quiet=True computa e registra a predição (log obrigatório) sem
    imprimir os blocos — usado por `--resumo` no modo lote, que só quer a
    tabela final. Sempre devolve o dict de `display.compute()` pro chamador
    montar a tabela (ou consumir como quiser).

    corners/cards: injeta o bloco de eventos (SEM validação de CLV) mesmo
    fora do --full — pede odd de decisão rápida sem forçar o operador a
    engolir o resto do Nível 3 junto."""
    for t in (name_a, name_b):
        if t not in elo:
            sys.exit(f"time desconhecido: {t}")
    adv = 0.0 if neutral else cfg["elo"]["home_advantage"]
    r = model.predict_match(elo[name_a], elo[name_b], params, adv,
                            max_goals=cfg["model"]["max_goals"])
    mk = _market_probs(conn, name_a, name_b) if conn is not None else None

    # OBRIGATÓRIO: congela o PACOTE COMPLETO da predição no momento em que é feita
    # (append-only). Falha ao gravar é avisada em alto e bom som, mas não derruba o serving.
    try:
        from .prediction_log import log_prediction
        log_prediction(name_a, name_b, neutral, elo[name_a], elo[name_b],
                       params, r, match_date=match_date, market=mk)
    except Exception as e:
        print(f"[AVISO: predição NÃO registrada no log ({e})]", file=sys.stderr)

    emit_event(_DOMAIN, "prediction",
               metrics={"home_goals_pred": round(float(r["lambda_a"]), 3),
                        "away_goals_pred": round(float(r["lambda_b"]), 3),
                        "p_win": round(float(r["p_win"]), 4),
                        "p_draw": round(float(r["p_draw"]), 4),
                        "p_loss": round(float(r["p_loss"]), 4)},
               metadata={"model": "NegBin+DixonColes",
                         "fixture_id": f"{name_a}_vs_{name_b}",
                         "neutral": neutral})

    from . import display
    data = display.compute(name_a, name_b, elo, params, cfg, neutral, conn)
    if not quiet:
        display.render(data, level=level, as_json=as_json)
        if not as_json and conn is not None:
            if corners:
                ev = display.compute_event(conn, elo, name_a, name_b,
                                           "Corner kicks", (7.5, 8.5, 9.5))
                display.render_event("Escanteios", ev, name_a, name_b, (7.5, 8.5, 9.5))
            if cards:
                ev = display.compute_event(conn, elo, name_a, name_b,
                                           "Yellow cards", (2.5, 3.5, 4.5))
                display.render_event("Cartões amarelos", ev, name_a, name_b, (2.5, 3.5, 4.5))
    return data


def main():
    ap = argparse.ArgumentParser(description="Preditor de partidas internacionais")
    ap.add_argument("teams", nargs="*", help="TIME_A TIME_B (em inglês, ex: Brazil)")
    ap.add_argument("--neutral", action="store_true", help="campo neutro")
    ap.add_argument("--fixtures", type=int, metavar="N",
                    help="prevê os próximos N fixtures da base")
    ap.add_argument("--rankings", type=int, metavar="N", help="top N do Elo")
    ap.add_argument("--resumo", action="store_true",
                    help="modo lote: só a tabela resumo ao final, sem os blocos por jogo "
                        "(--fixtures continua computando e registrando cada predição)")
    verbosity = ap.add_mutually_exclusive_group()
    verbosity.add_argument("--expand", action="store_true",
                           help="nível 1: gols esperados, edge detalhado, placar top-1")
    verbosity.add_argument("--stats", action="store_true",
                           help="nível 2: Shin completo, placares top-5, parâmetros do modelo")
    verbosity.add_argument("--full", action="store_true",
                           help="nível 3: dupla chance, draw no bet, handicap asiático")
    verbosity.add_argument("--json", action="store_true",
                           help="saída estruturada (machine-output), ignora os outros níveis")
    ap.add_argument("--corners", action="store_true",
                    help="injeta escanteios (SEM validação de CLV) sem precisar de --full")
    ap.add_argument("--cards", action="store_true",
                    help="injeta cartões (SEM validação de CLV) sem precisar de --full")
    args = ap.parse_args()
    level = 3 if args.full else 2 if args.stats else 1 if args.expand else 0

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
        batch = []
        for date, h, a, n in rows:
            # o prefixo "[date]" e' so pro modo texto legivel — em --json ele
            # vazaria uma linha solta antes de cada dict e quebraria o parse
            # de quem consome a saida (achado rodando --fixtures --resumo --json
            # junto: json.JSONDecodeError por causa desse texto intercalado).
            if not args.json and not args.resumo:
                print(f"\n[{date}]", end="")
            data = show(h, a, elo, params, cfg, bool(n), conn, match_date=date,
                       level=level, as_json=args.json, quiet=args.resumo and not args.json,
                       corners=args.corners, cards=args.cards)
            batch.append((date, data))
        if not args.json:
            from . import display
            display.render_summary_table(batch)
        return

    if len(args.teams) != 2:
        ap.error("informe TIME_A TIME_B, ou use --fixtures/--rankings")
    show(args.teams[0], args.teams[1], elo, params, cfg, args.neutral, conn,
        level=level, as_json=args.json, corners=args.corners, cards=args.cards)


if __name__ == "__main__":
    main()
