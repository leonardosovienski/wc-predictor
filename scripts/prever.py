"""Previsão COMPLETA de uma partida — todos os mercados derivaveis, num comando.

Uso:
    python scripts/prever.py Spain Austria              # campo neutro (padrao Copa)
    python scripts/prever.py Brazil France --mando      # com vantagem de mando p/ o 1o time
    python scripts/prever.py Spain Austria --mata-mata  # inclui P(classificar)
    python scripts/prever.py Spain Austria --json       # machine-output
    python scripts/prever.py Argentina Egypt --segundo-tempo 0-2
        # projecao do 2o tempo dado o placar do intervalo (SEM CLV validado —
        # nao existe mercado ao vivo no backtest; ver docs/HYPERPARAMETERS.md)

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
import json as _json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from src import display, model
from src.ingest import load_config


def _conn_ro():
    c = sqlite3.connect(f"file:{ROOT / 'data' / 'matches.db'}?mode=ro", uri=True)
    c.execute("PRAGMA query_only=ON")
    return c


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
    ap.add_argument("--segundo-tempo", metavar="H-A", dest="segundo_tempo",
                    help="placar do intervalo (gols de time_a-time_b) — projeta o "
                         "2o tempo em vez da previsao pre-jogo [SEM CLV validado]")
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

    if args.segundo_tempo:
        try:
            cur_a, cur_b = (int(x) for x in args.segundo_tempo.split("-", 1))
        except ValueError:
            sys.exit("--segundo-tempo espera 'H-A', ex: --segundo-tempo 0-2")
        live = display.compute_live(ta, tb, elo, params, cfg, neutral=not args.mando,
                                    cur_a=cur_a, cur_b=cur_b)
        if args.json:
            print(_json.dumps(live, ensure_ascii=False, indent=2))
        else:
            display.render_live(live)
        conn.close()
        return

    # todo o calculo + as 4 camadas de exibicao (Nivel 0..3) vem do mesmo
    # modulo que src/predict.py usa — ver src/display.py. O que fica so
    # aqui e' o que so o prever.py tem: mata-mata, escanteios/cartoes
    # (precisam de historico via conn, que predict.py nao consulta).
    adv = cfg["elo"]["home_advantage"] if args.mando else 0.0
    data = display.compute(ta, tb, elo, params, cfg, neutral=not args.mando, conn=conn)

    # OBRIGATÓRIO: mesmo registro append-only que src/predict.py grava — sem
    # isto os palpites deste script não entram na avaliação vs. resultado real.
    try:
        from src.prediction_log import log_prediction
        r = model.predict_match(elo[ta], elo[tb], params, adv,
                                max_goals=cfg["model"]["max_goals"])
        log_prediction(ta, tb, not args.mando, elo[ta], elo[tb], params, r,
                       market=data["core"]["market"])
    except Exception as e:
        print(f"[AVISO: predição NÃO registrada no log ({e})]", file=sys.stderr)

    display.render(data, level=3, as_json=args.json)
    if args.json:
        conn.close()
        return

    if args.ko:
        p_pen = 1.0 / (1.0 + 10 ** (-(elo[ta] + adv - elo[tb]) / 400.0))
        pa = data["core"]["p_win"] + data["core"]["p_draw"] * p_pen
        print(f"\nP(classificar): {ta} {pa:.1%} | {tb} {1 - pa:.1%}"
              f"  (empate no 90' resolvido pela logistica de Elo)")

    # eventos nao-gols: exclusivo do prever.py, exige historico de
    # match_statistics que so este script consulta. Calculo/exibicao vem de
    # display.compute_event/render_event — mesma funcao que --corners/--cards
    # em src/predict.py usa, sem duplicacao.
    display.render_event("Escanteios", display.compute_event(conn, elo, ta, tb,
                         "Corner kicks", (7.5, 8.5, 9.5)), ta, tb, (7.5, 8.5, 9.5))
    display.render_event("Cartoes amarelos", display.compute_event(conn, elo, ta, tb,
                         "Yellow cards", (2.5, 3.5, 4.5)), ta, tb, (2.5, 3.5, 4.5))

    conn.close()


if __name__ == "__main__":
    main()
