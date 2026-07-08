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
ENV_BANK_PATH = "BANKROLL_LOG_PATH"
ROOT = Path(__file__).resolve().parent.parent
_DEFAULT = ROOT / "data" / "bets.jsonl"
_BANK_DEFAULT = ROOT / "data" / "bankroll.jsonl"

# guarda-corpos de gestão de banca (flat stake, alinhado ao backtest):
#   unidade > 2% da banca inicial = agressivo demais pra variância real do
#   O/U (3/8 de acerto numa rodada é normal); exposição aberta > 10u = muita
#   banca em jogo ao mesmo tempo. Avisos, não bloqueios — a banca é do operador.
MAX_UNIT_PCT = 0.02
MAX_OPEN_UNITS = 10.0

# mercado -> (linha, período). FT = jogo inteiro; 1T/2T = por tempo (settle
# exige o placar do intervalo). Só o ou25 tem CLV comprovado no backtest — os
# demais entram como registro fiel do que o operador apostou, marcados
# validated=False, e o summary separa os dois grupos (não misturar ROI de
# mercado validado com aposta informativa).
MARKETS = {
    "ou25":    (2.5, "FT"),
    "ou15":    (1.5, "FT"),
    "ou05_1t": (0.5, "1T"), "ou15_1t": (1.5, "1T"), "ou25_1t": (2.5, "1T"),
    "ou05_2t": (0.5, "2T"), "ou15_2t": (1.5, "2T"), "ou25_2t": (2.5, "2T"),
}
VALIDATED = {"ou25"}             # único gatilho com CLV comprovado


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
            model_prob=None, edge=None, match_date=None, kickoff=None,
            note=None, path=None, logged_at=None) -> dict:
    """Registra a aposta ANTES do jogo. `market` em MARKETS; `selection` é o
    lado ('over'/'under'). `odds` é a odd DECIMAL tomada de fato (line shopping:
    a melhor que você conseguiu, não a média). `kickoff` = ISO-8601 UTC do
    apito — habilita a contagem regressiva no `list` e o carimbo de
    integridade: aposta registrada APÓS o kickoff é marcada late=True (o
    edge 'pré-jogo' dela não vale e o CLV vira mentira)."""
    if market not in MARKETS:
        raise ValueError(f"mercado desconhecido: {market!r} — use um de {sorted(MARKETS)}")
    if odds <= 1.0:
        raise ValueError(f"odd decimal inválida: {odds}")
    line, period = MARKETS[market]
    now_iso = logged_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    late = None
    if kickoff:
        try:
            ko = datetime.fromisoformat(kickoff.replace("Z", "+00:00"))
            now = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
            late = now >= ko
        except ValueError:
            kickoff, late = None, None       # kickoff ilegível: ignora, não trava
    # aviso de bilhete duplicado: mesma partida+mercado+seleção ainda aberta
    from .predict import _canon
    target = frozenset((_canon(home), _canon(away)))
    rows = _read(path)
    settled = {r["bet_line_no"] for r in rows if r["kind"] == "settlement"}
    dup = any(r["kind"] == "bet" and i not in settled
              and frozenset((_canon(r["home"]), _canon(r["away"]))) == target
              and r["market"] == market and r["selection"] == selection.lower()
              for i, r in enumerate(rows))
    rec = {
        "logged_at": now_iso,
        "kind": "bet", "status": "open",
        "home": home, "away": away, "match_date": match_date,
        "kickoff": kickoff, "late": late,
        "market": market, "line": line, "period": period,
        "selection": selection.lower(),
        "odds": float(odds), "book": book, "stake": float(stake),
        "model_prob": model_prob, "edge": edge, "note": note,
        "validated": market in VALIDATED,
        "duplicate_of_open": dup,
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


def settle_bet(home, away, home_score, away_score, *, ht=None, path=None,
               recorded_at=None) -> list[dict]:
    """Fecha TODAS as apostas abertas deste confronto contra o placar final.
    Grava uma linha 'settlement' por aposta (append-only — a aposta original
    não é editada). Devolve os settlements gravados.

    `ht` = placar do intervalo (tupla ou 'H-A'), na MESMA ordem casa/fora do
    placar final informado — obrigatório pra fechar apostas de 1T/2T; sem ele
    essas ficam abertas (aviso no CLI), as de jogo inteiro fecham normal."""
    from .predict import _canon
    if isinstance(ht, str):
        ht = tuple(int(x) for x in ht.split("-", 1))
    total_ft = int(home_score) + int(away_score)
    total_ht = None if ht is None else int(ht[0]) + int(ht[1])
    if total_ht is not None and total_ht > total_ft:
        raise ValueError(f"placar do intervalo ({total_ht} gols) maior que o final "
                         f"({total_ft}) — erro de digitação? dinheiro real exige "
                         "placar certo")
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
        period = bet.get("period", "FT")
        if period == "FT":
            total = total_ft
        elif total_ht is None:
            continue                       # 1T/2T sem HT informado: segue aberta
        else:
            total = total_ht if period == "1T" else total_ft - total_ht
        won = (bet["selection"] == "over") == (total > bet["line"]) \
            if total != bet["line"] else None          # push só em linha inteira
        profit = 0.0 if won is None else \
            round(bet["stake"] * (bet["odds"] - 1.0), 4) if won else -bet["stake"]
        # CLV de fechamento: só o ou25 tem odd de close no banco (linha 2.5)
        clv = None
        if bet["market"] == "ou25":
            p_close = _close_shin_prob(bet["home"], bet["away"], bet["selection"])
            clv = None if p_close is None else round(bet["odds"] * p_close - 1.0, 4)
        rec = {
            "recorded_at": recorded_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "kind": "settlement", "bet_line_no": line_no,
            "home": bet["home"], "away": bet["away"],
            "score": f"{home_score}-{away_score}",
            "ht": None if ht is None else f"{ht[0]}-{ht[1]}",
            "total_do_periodo": total,
            "market": bet["market"], "period": period, "selection": bet["selection"],
            "odds": bet["odds"], "stake": bet["stake"],
            "won": won, "profit": profit, "clv_close": clv,
            "validated": bet.get("validated", bet["market"] in VALIDATED),
        }
        _append(rec, path)
        out.append(rec)
    return out


def _resolve_bank(path=None) -> Path:
    return Path(path or os.environ.get(ENV_BANK_PATH) or _BANK_DEFAULT)


def bank_init(amount, unit, *, currency="BRL", path=None, at=None) -> dict:
    """Abre (ou reabre) a banca: valor total e valor da UNIDADE em dinheiro.
    Append-only — um novo init reinicia a contagem a partir dele (o histórico
    anterior fica no arquivo, auditável)."""
    if amount <= 0 or unit <= 0:
        raise ValueError("banca e unidade devem ser positivas")
    rec = {"at": at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "kind": "init", "amount": float(amount), "unit": float(unit),
           "currency": currency}
    dest = _resolve_bank(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def bank_flow(kind, amount, *, path=None, at=None) -> dict:
    """Depósito ou saque (kind='deposit'|'withdraw')."""
    if kind not in ("deposit", "withdraw"):
        raise ValueError(f"kind inválido: {kind}")
    if amount <= 0:
        raise ValueError("valor deve ser positivo")
    rec = {"at": at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "kind": kind, "amount": float(amount)}
    dest = _resolve_bank(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def bank_state(bank_path=None, bets_path=None) -> dict | None:
    """Estado da banca: saldo em dinheiro, exposição aberta, drawdown máximo.
    None se a banca nunca foi aberta. Só considera settlements DEPOIS do
    último init (a banca conta a partir de quando foi aberta)."""
    p = _resolve_bank(bank_path)
    if not p.exists():
        return None
    init, flows = None, 0.0
    for line in p.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["kind"] == "init":
            init, flows = r, 0.0            # novo init zera a contagem
        elif r["kind"] == "deposit":
            flows += r["amount"]
        elif r["kind"] == "withdraw":
            flows -= r["amount"]
    if init is None:
        return None
    unit = init["unit"]
    settles = sorted((r for r in _read(bets_path)
                      if r["kind"] == "settlement" and r["recorded_at"] >= init["at"]),
                     key=lambda r: r["recorded_at"])
    profit_units = sum(r["profit"] for r in settles)
    # equity curve em dinheiro -> max drawdown (do pico ao vale)
    equity, peak, mdd = init["amount"] + flows, init["amount"] + flows, 0.0
    for r in settles:
        equity += r["profit"] * unit
        peak = max(peak, equity)
        mdd = max(mdd, peak - equity)
    # exposição = TODA aposta ainda aberta no livro (mesmo registrada antes do
    # init — aposta viva é dinheiro em jogo desta banca), casada por linha
    all_rows = _read(bets_path)
    settled_lines = {r["bet_line_no"] for r in all_rows if r["kind"] == "settlement"}
    open_units = sum(r["stake"] for i, r in enumerate(all_rows)
                     if r["kind"] == "bet" and i not in settled_lines)
    balance = init["amount"] + flows + profit_units * unit
    return {
        "currency": init.get("currency", "BRL"), "initial": init["amount"],
        "unit": unit, "unit_pct": unit / init["amount"],
        "flows": flows, "balance": round(balance, 2),
        "profit_units": round(profit_units, 4),
        "profit_money": round(profit_units * unit, 2),
        "n_settled": len(settles), "open_units": round(max(open_units, 0.0), 2),
        "open_money": round(max(open_units, 0.0) * unit, 2),
        "max_drawdown_money": round(mdd, 2),
        "since": init["at"],
    }


def list_bets(path=None) -> list[dict]:
    """Todas as apostas com status resolvido por linha: cada bet ganha
    'result' (settlement casado por bet_line_no) ou None se aberta."""
    rows = _read(path)
    settles = {r["bet_line_no"]: r for r in rows if r["kind"] == "settlement"}
    out = []
    for i, r in enumerate(rows):
        if r["kind"] != "bet":
            continue
        out.append({**r, "result": settles.get(i)})
    return out


def _countdown(kickoff: str | None) -> str:
    """'em 3h12', 'em 2d 04h', 'EM ANDAMENTO/ENCERRADO' ou '' sem kickoff."""
    if not kickoff:
        return ""
    try:
        ko = datetime.fromisoformat(kickoff.replace("Z", "+00:00"))
    except ValueError:
        return ""
    delta = (ko - datetime.now(timezone.utc)).total_seconds()
    if delta <= 0:
        return "JÁ COMEÇOU"
    d, rem = divmod(int(delta), 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    return f"em {d}d {h:02d}h" if d else (f"em {h}h{m:02d}" if h else f"em {m}min")


def summary(path=None) -> dict:
    """ROI e CLV acumulados por mercado (só apostas fechadas). A chave carrega
    o grupo: mercado validado (ou25) separado dos informativos — misturar os
    dois esconderia um ROI negativo atrás do outro."""
    tally: dict = {}
    for r in _read(path):
        if r["kind"] != "settlement":
            continue
        t = tally.setdefault(r["market"], {"n": 0, "staked": 0.0, "profit": 0.0,
                                           "clv_sum": 0.0, "clv_n": 0,
                                           "validated": r.get("validated", False)})
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
    a.add_argument("--kickoff", help="ISO-8601 UTC do apito (habilita contagem "
                                     "regressiva e o carimbo de aposta tardia)")
    a.add_argument("--nota", dest="note")

    sub.add_parser("list", help="todas as apostas: abertas com contagem "
                                "regressiva, fechadas com resultado")

    s = sub.add_parser("settle", help="fecha apostas do confronto no placar final")
    s.add_argument("home"); s.add_argument("away")
    s.add_argument("home_score", type=int); s.add_argument("away_score", type=int)
    s.add_argument("--ht", help="placar do intervalo 'H-A' (obrigatório pra "
                                "fechar apostas de 1T/2T)")

    sub.add_parser("summary", help="ROI/CLV acumulado por mercado")

    b = sub.add_parser("banca", help="painel da banca (saldo/exposição/drawdown)")
    b.add_argument("--init", type=float, metavar="VALOR",
                   help="abre a banca com este valor total")
    b.add_argument("--unidade", type=float,
                   help="valor da unidade em dinheiro (com --init)")
    b.add_argument("--deposito", type=float, metavar="VALOR")
    b.add_argument("--saque", type=float, metavar="VALOR")
    b.add_argument("--moeda", default="BRL")

    args = ap.parse_args()
    if args.cmd == "add":
        rec = add_bet(args.home, args.away, args.market, args.selection, args.odds,
                      book=args.book, stake=args.stake, model_prob=args.model_prob,
                      edge=args.edge, match_date=args.match_date,
                      kickoff=args.kickoff, note=args.note)
        aviso = "" if rec["validated"] else "  [mercado SEM CLV validado]"
        print(f"registrada: {rec['selection']} {rec['line']} ({rec['period']}) "
              f"@ {rec['odds']} ({rec['book'] or 'casa nao informada'}) "
              f"stake {rec['stake']}u — {rec['home']} x {rec['away']}{aviso}")
        if rec["late"]:
            print("  ALERTA: registrada APÓS o kickoff — o edge pré-jogo desta "
                  "aposta NÃO vale e ela ficou carimbada late=True no livro.")
        if rec["duplicate_of_open"]:
            print("  ALERTA: já existe aposta ABERTA idêntica (mesmo jogo/mercado/"
                  "lado) — se foi sem querer, a exposição dobrou.")
    elif args.cmd == "list":
        st = bank_state()
        unit = st["unit"] if st else None
        bets = list_bets()
        if not bets:
            print("nenhuma aposta no livro ainda")
            return
        abertas = [b for b in bets if b["result"] is None]
        fechadas = [b for b in bets if b["result"] is not None]
        if abertas:
            print(f"\n=== ABERTAS ({len(abertas)}) ===")
            for b in abertas:
                v = "VALID" if b.get("validated", b["market"] in VALIDATED) else "info "
                money = f" = R$ {b['stake'] * unit:.0f}" if unit else ""
                extra = " ".join(x for x in (
                    _countdown(b.get("kickoff")) or (b.get("match_date") or ""),
                    "[LATE]" if b.get("late") else "",
                    "[DUP?]" if b.get("duplicate_of_open") else "") if x)
                print(f"  [{v}] {b['home']} x {b['away']}: {b['selection']} "
                      f"{b['line']} ({b.get('period', 'FT')}) @ {b['odds']} "
                      f"{b['book'] or ''} | {b['stake']}u{money} | {extra}")
        if fechadas:
            print(f"\n=== FECHADAS ({len(fechadas)}) ===")
            for b in fechadas:
                r = b["result"]
                res = "PUSH" if r["won"] is None else ("GANHOU" if r["won"] else "PERDEU")
                money = f" = R$ {r['profit'] * unit:+.0f}" if unit else ""
                clv = f" | CLV {r['clv_close']:+.1%}" if r.get("clv_close") is not None else ""
                print(f"  [{res}] {b['home']} x {b['away']}: {b['selection']} "
                      f"{b['line']} ({b.get('period', 'FT')}) @ {b['odds']} "
                      f"-> {r['profit']:+.2f}u{money}{clv}")
        if st:
            print(f"\n  banca: R$ {st['balance']:.2f} | em jogo: {st['open_units']:.1f}u "
                  f"= R$ {st['open_money']:.2f} | unidade R$ {st['unit']:.2f}")
    elif args.cmd == "settle":
        recs = settle_bet(args.home, args.away, args.home_score, args.away_score,
                          ht=args.ht)
        if not recs:
            print("nenhuma aposta aberta para este confronto")
        for r in recs:
            res = "PUSH" if r["won"] is None else ("GANHOU" if r["won"] else "PERDEU")
            clv = "" if r["clv_close"] is None else f" | CLV {r['clv_close']:+.2%}"
            print(f"{res}: {r['selection']} {r['market']} ({r['period']}) "
                  f"@ {r['odds']} -> {r['profit']:+.2f}u{clv}")
        if recs and args.ht is None:
            print("(apostas de 1T/2T, se houver, seguem abertas — repita com --ht H-A)")
    elif args.cmd == "banca":
        if args.init is not None:
            if args.unidade is None:
                ap.error("--init exige --unidade (valor da unidade em dinheiro)")
            rec = bank_init(args.init, args.unidade, currency=args.moeda)
            pct = args.unidade / args.init
            print(f"banca aberta: {rec['amount']:.2f} {rec['currency']} | "
                  f"unidade = {rec['unit']:.2f} ({pct:.1%} da banca)")
            if pct > MAX_UNIT_PCT:
                print(f"  AVISO: unidade acima de {MAX_UNIT_PCT:.0%} da banca — "
                      "3 derrotas em 8 apostas é variância NORMAL do O/U; "
                      "unidade grande transforma variância em ruína.")
        if args.deposito:
            bank_flow("deposit", args.deposito)
            print(f"depósito: +{args.deposito:.2f}")
        if args.saque:
            bank_flow("withdraw", args.saque)
            print(f"saque: -{args.saque:.2f}")
        st = bank_state()
        if st is None:
            print("banca não aberta — use: python -m src.bet_log banca "
                  "--init VALOR --unidade VALOR_DA_UNIDADE")
            return
        cur = st["currency"]
        print(f"\n=== BANCA ({cur}) — desde {st['since'][:10]} ===")
        fluxos = f", fluxos {st['flows']:+.2f}" if st["flows"] else ""
        print(f"  saldo atual:      {st['balance']:.2f}"
              f"  (inicial {st['initial']:.2f}{fluxos})")
        print(f"  unidade:          {st['unit']:.2f}  ({st['unit_pct']:.1%} da banca inicial)")
        print(f"  resultado:        {st['profit_units']:+.2f}u = {st['profit_money']:+.2f} {cur}"
              f"  em {st['n_settled']} apostas fechadas")
        print(f"  em jogo (aberto): {st['open_units']:.1f}u = {st['open_money']:.2f} {cur}")
        print(f"  drawdown máximo:  {st['max_drawdown_money']:.2f} {cur}")
        if st["unit_pct"] > MAX_UNIT_PCT:
            print(f"  AVISO: unidade > {MAX_UNIT_PCT:.0%} da banca inicial")
        if st["open_units"] > MAX_OPEN_UNITS:
            print(f"  AVISO: exposição aberta > {MAX_OPEN_UNITS:.0f}u")
    else:
        tally = summary()
        if not tally:
            print("nenhuma aposta fechada ainda (data/bets.jsonl)")
        for grupo, ok in (("MERCADO VALIDADO (CLV comprovado)", True),
                          ("INFORMATIVO (sem CLV)", False)):
            linhas = {m: t for m, t in tally.items() if t["validated"] == ok}
            if not linhas:
                continue
            print(f"\n{grupo}:")
            for m, t in linhas.items():
                clv = "sem odd de fechamento" if t["clv_medio"] is None \
                    else f"CLV médio {t['clv_medio']:+.2%}"
                print(f"  {m}: {t['n']} apostas | staked {t['staked']:.1f}u | "
                      f"lucro {t['profit']:+.2f}u | ROI {t['roi']:+.1%} | {clv}")


if __name__ == "__main__":
    main()
