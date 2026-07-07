"""Aferição: cruza o palpite congelado (predictions.jsonl) com o resultado real
e grava a nota + os stats crus do jogo (data/results.jsonl, append-only).

Fecha o ciclo do registro obrigatório: prever → anotar o palpite → anotar o
resultado → medir acerto. Os stats que o modelo AINDA não prevê (escanteio,
cartão, chute, posse, xG) são guardados crus mesmo assim — viram matéria-prima
do build desses mercados, e o histórico de acerto fica auditável desde já.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .predict import _canon        # reusa os aliases (South Korea/Korea Republic,
                                    # USA/United States, etc.) — não duplica a lista

ROOT = Path(__file__).resolve().parent.parent
PRED_PATH = ROOT / "data" / "predictions.jsonl"
RESULTS_PATH = ROOT / "data" / "results.jsonl"
ENV_RESULTS = "RESULTS_LOG_PATH"

# stats por jogo, sempre [casa, fora]. O modelo só prevê gols hoje; o resto é
# guardado cru pro build de escanteio/cartão/chute.
STAT_KEYS = ("possession", "xg", "big_chances", "shots", "shots_on_target",
             "gk_saves", "corners", "fouls", "passes", "tackles", "yellow", "red")


def _find_prediction(home, away, match_date=None, pred_path=None):
    """Última predição congelada para o confronto (por nomes + data, se dada).
    Casa por CONJUNTO de times, não por ordem — em campo neutro (toda a Copa) a
    ordem casa/fora é arbitrária; exigir a mesma ordem faz o palpite existente
    "sumir" (falso negativo) se o resultado for registrado na ordem invertida."""
    p = Path(pred_path or PRED_PATH)
    if not p.exists():
        return None
    target = frozenset((_canon(home), _canon(away)))
    hit = None
    for line in p.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if frozenset((_canon(r["home"]), _canon(r["away"]))) == target:
            if match_date and r.get("match_date") != match_date:
                continue
            hit = r          # fica com a mais recente
    return hit


def _orient(pred, home, away):
    """Realinha o palpite para a ordem casa/fora com que o RESULTADO está sendo
    informado — se o predict.py congelou 'Norway vs Brazil' e o resultado chega
    como 'Brazil, Norway', p_home/p_away e lambda_* precisam trocar de lado, ou
    a nota do palpite (winner/placar) sai invertida."""
    if _canon(pred["home"]) == _canon(home):
        return pred
    swapped = dict(pred)
    swapped["home"], swapped["away"] = pred["away"], pred["home"]
    swapped["p_home"], swapped["p_away"] = pred["p_away"], pred["p_home"]
    swapped["lambda_home"], swapped["lambda_away"] = pred["lambda_away"], pred["lambda_home"]
    # placares em top_scores são (gols_casa, gols_fora) — inverte cada par também
    swapped["top_scores"] = [[[sc[1], sc[0]], p] for sc, p in pred["top_scores"]]
    return swapped


def grade(pred, home_score, away_score):
    """Nota do palpite vs placar real. Puro/testável. Devolve dict de mercados."""
    hs, as_ = int(home_score), int(away_score)
    res = "home" if hs > as_ else ("away" if as_ > hs else "draw")
    total = hs + as_
    ph, pd, pa = pred["p_home"], pred["p_draw"], pred["p_away"]
    # 1X2: o palpite é o maior
    pick_1x2 = max((("home", ph), ("draw", pd), ("away", pa)), key=lambda t: t[1])[0]
    pick_name = {"home": pred["home"], "away": pred["away"], "draw": "Empate"}[pick_1x2]
    o25 = pred["over"]["2.5"]
    ou_pick = "Over" if o25 >= 0.5 else "Under"
    ou_real = "Over" if total > 2.5 else "Under"
    btts_pick = "Sim" if pred["btts_yes"] >= 0.5 else "Não"
    btts_real = "Sim" if (hs >= 1 and as_ >= 1) else "Não"
    top = pred["top_scores"][0][0]
    exact_pick = f"{top[0]}x{top[1]}"
    grades = {
        "winner": {"pick": pick_name, "prob": round(max(ph, pd, pa), 4),
                   "actual": {"home": pred["home"], "away": pred["away"], "draw": "Empate"}[res],
                   "correct": pick_1x2 == res},
        "over_under_2.5": {"pick": ou_pick, "actual": ou_real, "correct": ou_pick == ou_real},
        "btts": {"pick": btts_pick, "actual": btts_real, "correct": btts_pick == btts_real},
        "exact_score": {"pick": exact_pick, "actual": f"{hs}x{as_}",
                        "correct": exact_pick == f"{hs}x{as_}"},
    }
    return grades


def record_result(home, away, home_score, away_score, *, match_date=None,
                  scorers=None, stats=None, path=None, pred_path=None,
                  recorded_at=None) -> dict:
    """Grava uma linha em results.jsonl: palpite + resultado + nota + stats crus.
    `stats` = dict com chaves de STAT_KEYS, cada valor [casa, fora]."""
    pred = _find_prediction(home, away, match_date, pred_path)
    if pred is not None:
        pred = _orient(pred, home, away)
        # sem --date do operador, herda a data que o palpite congelou — antes
        # disso TODO results.jsonl saía com match_date nulo (auditoria 2026-07-07)
        if match_date is None:
            match_date = pred.get("match_date")
    hs, as_ = int(home_score), int(away_score)
    record = {
        "recorded_at": recorded_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "match_date": match_date, "home": home, "away": away,
        "actual": {
            "home_score": hs, "away_score": as_,
            "result": "home" if hs > as_ else ("away" if as_ > hs else "draw"),
            "total_goals": hs + as_, "scorers": scorers or [],
            "stats": {k: stats[k] for k in STAT_KEYS if stats and k in stats} if stats else {},
        },
        "prediction": None if pred is None else {
            "p_home": pred["p_home"], "p_draw": pred["p_draw"], "p_away": pred["p_away"],
            "lambda_home": pred["lambda_home"], "lambda_away": pred["lambda_away"],
            "over_2.5": pred["over"]["2.5"], "btts_yes": pred["btts_yes"],
            "top_score": pred["top_scores"][0], "logged_at": pred["logged_at"],
        },
        "grades": None if pred is None else grade(pred, hs, as_),
    }
    if pred is None:
        record["warning"] = "sem palpite congelado para este confronto (não avaliado)"
    dest = Path(path or os.environ.get(ENV_RESULTS) or RESULTS_PATH)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def summary(path=None):
    """Placar acumulado do modelo por mercado (lê results.jsonl)."""
    dest = Path(path or os.environ.get(ENV_RESULTS) or RESULTS_PATH)
    if not dest.exists():
        return {}
    tally = {}
    for line in dest.read_text(encoding="utf-8").splitlines():
        g = json.loads(line).get("grades")
        if not g:
            continue
        for market, res in g.items():
            t = tally.setdefault(market, [0, 0])
            t[0] += int(res["correct"])
            t[1] += 1
    return tally


def main():
    import argparse
    ap = argparse.ArgumentParser(
        description="Registra resultado real + afere o palpite congelado")
    ap.add_argument("home", nargs="?"); ap.add_argument("away", nargs="?")
    ap.add_argument("home_score", type=int, nargs="?")
    ap.add_argument("away_score", type=int, nargs="?")
    ap.add_argument("--date", help="data do jogo (YYYY-MM-DD) p/ casar o palpite certo")
    ap.add_argument("--stats", help='JSON dos stats, cada valor [casa,fora] '
                    '(ex: \'{"corners":[2,12],"yellow":[0,3]}\')')
    ap.add_argument("--summary", action="store_true", help="só mostra o placar acumulado")
    args = ap.parse_args()
    if args.summary:
        tally = summary()
        if not tally:
            print("nada aferido ainda (data/results.jsonl vazio)")
        for mkt, (ok, n) in tally.items():
            print(f"  {mkt:16} {ok}/{n}  ({ok / n:.0%})" if n else f"  {mkt}: 0")
        return
    if None in (args.home, args.away, args.home_score, args.away_score):
        ap.error("informe: home away home_score away_score  (ou use --summary)")
    stats = json.loads(args.stats) if args.stats else None
    rec = record_result(args.home, args.away, args.home_score, args.away_score,
                        match_date=args.date, stats=stats)
    if rec["grades"] is None:
        print("resultado gravado, mas SEM palpite congelado p/ este confronto (não avaliado)")
    else:
        ok = sum(g["correct"] for g in rec["grades"].values())
        print(f"gravado: {args.home} {args.home_score}-{args.away_score} {args.away} "
              f"| palpite acertou {ok}/{len(rec['grades'])} mercados")


if __name__ == "__main__":
    main()
