"""Livro-caixa de APOSTAS (JSONL append-only) — o elo financeiro do pipeline.

predictions.jsonl congela o que o MODELO disse; este arquivo congela o que o
OPERADOR apostou: seleção, linha, odd tomada, casa, stake. Sem isto não existe
ROI real nem CLV real — só acerto de palpite, que não paga boleto.

Fluxo:
    python -m src.bet_log add Norway England ou25 under 2.21 --casa BetOnline \
        --edge 0.095 --prob 0.548                    # ANTES do jogo
    python -m src.bet_log settle Norway England 0 1  # depois do placar final
    python -m src.bet_log summary                    # ROI acumulado por mercado

CLV real no settle: odd tomada × prob Shin do FECHAMENTO (sofascore_matches)
− 1. É a mesma régua do backtest — positivo consistente = você está batendo
o preço de fechamento, o único preditor confiável de lucro no longo prazo.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

ENV_PATH = "BETS_LOG_PATH"
ROOT = Path(__file__).resolve().parent.parent
_DEFAULT = ROOT / "data" / "bets.jsonl"

MARKETS = {"ou25": 2.5}          # linha por mercado; extensível (ou15, ah, ...)


def _resolve(path=None) -> Path:
    return Path(path or os.environ.get(ENV_PATH) or _DEFAULT)


def _read(path=None) -> list[dict]:
    p = _resolve(path)
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l]


def _append(rec: dict, path=None) -> None:
    dest = _resolve(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def add_bet(home, away, market, selection, odds, *, book=None, stake=1.0,
            model_prob=None, edge=None, match_date=None, note=None,
            path=None, logged_at=None) -> dict:
    """Registra a aposta ANTES do jogo. `market` em MARKETS; `selection` é o
    lado ('over'/'under'). `odds` é a odd DECIMAL tomada de fato (line shopping:
    a melhor que você conseguiu, não a média)."""
    if market not in MARKETS:
        raise ValueError(f"mercado desconhecido: {market!r} — use um de {sorted(MARKETS)}")
    if odds <= 1.0:
        raise ValueError(f"odd decimal inválida: {odds}")
    rec = {
        "logged_at": logged_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kind": "bet", "status": "open",
        "home": home, "away": away, "match_date": match_date,
        "market": market, "line": MARKETS[market], "selection": selection.lower(),
        "odds": float(odds), "book": book, "stake": float(stake),
        "model_prob": model_prob, "edge": edge, "note": note,
    }
    _append(rec, path)
    return rec


def _close_shin_prob(home, away, selection):
    """Prob Shin de FECHAMENTO da seleção (sofascore_matches) — None se não há
    odds do confronto no banco. Reusa _market_probs (aliases inclusos)."""
    import sqlite3
    from .predict import _market_probs
    try:
        conn = sqlite3.connect(f"file:{ROOT / 'data' / 'matches.db'}?mode=ro", uri=True)
        mk = _market_probs(conn, home, away)
        conn.close()
    except Exception:
        return None
    if not mk or mk.get("p_over") is None:
        return None
    return mk["p_over"] if selection == "over" else mk["p_under"]


def settle_bet(home, away, home_score, away_score, *, path=None,
               recorded_at=None) -> list[dict]:
    """Fecha TODAS as apostas abertas deste confronto contra o placar final.
    Grava uma linha 'settlement' por aposta (append-only — a aposta original
    não é editada). Devolve os settlements gravados."""
    from .predict import _canon
    total = int(home_score) + int(away_score)
    target = frozenset((_canon(home), _canon(away)))
    open_ids, settled_ids = {}, set()
    for i, r in enumerate(_read(path)):
        key = frozenset((_canon(r["home"]), _canon(r["away"])))
        if r["kind"] == "bet" and key == target:
            open_ids[i] = r
        elif r["kind"] == "settlement" and key == target:
            settled_ids.add(r["bet_line_no"])
    out = []
    for line_no, bet in open_ids.items():
        if line_no in settled_ids:
            continue
        won = (bet["selection"] == "over") == (total > bet["line"]) \
            if total != bet["line"] else None          # push só em linha inteira
        profit = 0.0 if won is None else \
            round(bet["stake"] * (bet["odds"] - 1.0), 4) if won else -bet["stake"]
        p_close = _close_shin_prob(bet["home"], bet["away"], bet["selection"])
        clv = None if p_close is None else round(bet["odds"] * p_close - 1.0, 4)
        rec = {
            "recorded_at": recorded_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "kind": "settlement", "bet_line_no": line_no,
            "home": bet["home"], "away": bet["away"],
            "score": f"{home_score}-{away_score}", "total_goals": total,
            "market": bet["market"], "selection": bet["selection"],
            "odds": bet["odds"], "stake": bet["stake"],
            "won": won, "profit": profit, "clv_close": clv,
        }
        _append(rec, path)
        out.append(rec)
    return out


def summary(path=None) -> dict:
    """ROI e CLV acumulados por mercado (só apostas fechadas)."""
    tally: dict = {}
    for r in _read(path):
        if r["kind"] != "settlement":
            continue
        t = tally.setdefault(r["market"], {"n": 0, "staked": 0.0, "profit": 0.0,
                                           "clv_sum": 0.0, "clv_n": 0})
        t["n"] += 1
        t["staked"] += r["stake"]
        t["profit"] += r["profit"]
        if r.get("clv_close") is not None:
            t["clv_sum"] += r["clv_close"]
            t["clv_n"] += 1
    for t in tally.values():
        t["roi"] = t["profit"] / t["staked"] if t["staked"] else 0.0
        t["clv_medio"] = t["clv_sum"] / t["clv_n"] if t["clv_n"] else None
    return tally


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Livro-caixa de apostas (append-only)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="registra aposta ANTES do jogo")
    a.add_argument("home"); a.add_argument("away")
    a.add_argument("market", choices=sorted(MARKETS))
    a.add_argument("selection", choices=["over", "under"])
    a.add_argument("odds", type=float)
    a.add_argument("--casa", dest="book")
    a.add_argument("--stake", type=float, default=1.0)
    a.add_argument("--prob", type=float, dest="model_prob")
    a.add_argument("--edge", type=float)
    a.add_argument("--date", dest="match_date")
    a.add_argument("--nota", dest="note")

    s = sub.add_parser("settle", help="fecha apostas do confronto no placar final")
    s.add_argument("home"); s.add_argument("away")
    s.add_argument("home_score", type=int); s.add_argument("away_score", type=int)

    sub.add_parser("summary", help="ROI/CLV acumulado por mercado")

    args = ap.parse_args()
    if args.cmd == "add":
        rec = add_bet(args.home, args.away, args.market, args.selection, args.odds,
                      book=args.book, stake=args.stake, model_prob=args.model_prob,
                      edge=args.edge, match_date=args.match_date, note=args.note)
        print(f"registrada: {rec['selection']} {rec['line']} @ {rec['odds']}"
              f" ({rec['book'] or 'casa nao informada'}) stake {rec['stake']}u"
              f" — {rec['home']} x {rec['away']}")
    elif args.cmd == "settle":
        recs = settle_bet(args.home, args.away, args.home_score, args.away_score)
        if not recs:
            print("nenhuma aposta aberta para este confronto")
        for r in recs:
            res = "PUSH" if r["won"] is None else ("GANHOU" if r["won"] else "PERDEU")
            clv = "" if r["clv_close"] is None else f" | CLV {r['clv_close']:+.2%}"
            print(f"{res}: {r['selection']} {r['market']} @ {r['odds']}"
                  f" -> {r['profit']:+.2f}u{clv}")
    else:
        tally = summary()
        if not tally:
            print("nenhuma aposta fechada ainda (data/bets.jsonl)")
        for m, t in tally.items():
            clv = "sem odds de fechamento" if t["clv_medio"] is None \
                else f"CLV médio {t['clv_medio']:+.2%}"
            print(f"  {m}: {t['n']} apostas | staked {t['staked']:.1f}u | "
                  f"lucro {t['profit']:+.2f}u | ROI {t['roi']:+.1%} | {clv}")


if __name__ == "__main__":
    main()
