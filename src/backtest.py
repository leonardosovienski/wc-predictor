"""Backtest: roda o motor contra as odds históricas e mede P&L (o Quality Gate).

Replica a passada forward do Elo (sem vazamento — cada rating só vê o passado) e,
em cada jogo com odds, faz aposta de valor com stake fixo.

Gatilho = EV ao PREÇO ofertado: P_modelo > 1/odd (implícita bruta, com vig). NÃO
P_modelo > Shin: bater o Shin sem bater o preço é sangrar pro vig — o falso
positivo numérico. As duas comparações ficam no ledger para auditoria.

Lookahead: os params (a, b, alpha, rho) são o risco, não o Elo. Modo 'frozen'
calibra só com jogos ANTES da janela de teste e congela. Walk-forward (recalibrar
a cada passo, caro) fica como evolução atrás de flag — não nesta versão.

Preço e régua: a aposta é feita na ABERTURA quando ela existe (primeira odd
observada pré-apito pelo cron), com fallback pro fechamento na base histórica
(coluna bet_at separa as populações). A métrica definitiva é o CLV — odd
pactuada × probabilidade Shin do fechamento − 1 — porque converge com dezenas
de apostas, não milhares. Significância: `python -m src.bootstrap`.
"""
import csv
import sys
from datetime import date, timedelta

from . import db, model, ratings
from . import market_pricer as mp
from .ingest import ROOT, load_config
from .math_utils import shin_probabilities
from .predict import _canon
from predictor_core.obs import emit_event

OUTCOMES = ("home", "draw", "away")


def _load_odds(conn):
    out = {}
    try:
        rows = conn.execute(
            "SELECT date, home_team, away_team, odds_home, odds_draw, odds_away, "
            "odds_over, odds_under, odds_home_open, odds_draw_open, odds_away_open, "
            "odds_over_open, odds_under_open "
            "FROM sofascore_matches WHERE odds_home IS NOT NULL").fetchall()
    except Exception:
        return out
    for d, h, a, oh, od, oa, oov, oun, oh_o, od_o, oa_o, oov_o, oun_o in rows:
        out.setdefault(frozenset((_canon(h), _canon(a))), []).append(
            (d, _canon(h), oh, od, oa, oov, oun, oh_o, od_o, oa_o, oov_o, oun_o))
    return out


def _find_odds(odds, home, away, d):
    """Casa o confronto por nomes reconciliados, com tolerância de data (timezone).
    Devolve (close_1x2, close_ou, open_1x2, open_ou), 1X2 orientado ao mando.
    Semântica: odds_* = fechamento (última leitura); *_open = primeira leitura
    pré-apito — NULL em toda a base histórica coletada pós-jogo."""
    cands = odds.get(frozenset((_canon(home), _canon(away))))
    if not cands:
        return None
    gd = date.fromisoformat(d)
    best = None
    for od_date, ch, oh, odr, oa, oov, oun, oh_o, od_o, oa_o, oov_o, oun_o in cands:
        try:
            dd = abs((date.fromisoformat(od_date) - gd).days)
        except Exception:
            continue
        if dd <= 3 and (best is None or dd < best[0]):
            if ch == _canon(home):
                x12, x12_o = (oh, odr, oa), (oh_o, od_o, oa_o)
            else:
                x12, x12_o = (oa, odr, oh), (oa_o, od_o, oh_o)
            best = (dd, x12, (oov, oun), x12_o, (oov_o, oun_o))
    return best[1:] if best else None


# ------------------------------------------------------------------ #
# Mercados estendidos (Fase 1, SEM push) — caminho paralelo ao 1X2/OU #
# legado. Casam por event_id (DC/BTTS em colunas flat; OU multi-linha  #
# em odds_lines). Mantém _load_odds/_find_odds intactos (back-compat). #
# ------------------------------------------------------------------ #

def _load_ext_index(conn):
    """frozenset(canon_home, canon_away) → [(date, canon_home, event_id)].
    Espelha o casamento de _load_odds, mas carrega o event_id para juntar
    com as colunas flat e a tabela odds_lines."""
    idx = {}
    try:
        rows = conn.execute(
            "SELECT event_id, date, home_team, away_team FROM sofascore_matches").fetchall()
    except Exception:
        return idx
    for eid, d, h, a in rows:
        ch, ca = _canon(h or ""), _canon(a or "")
        idx.setdefault(frozenset((ch, ca)), []).append((d, ch, eid))
    return idx


def _find_event(idx, home, away, d):
    """(event_id, home_oriented) do jogo casado, ou None. home_oriented=False
    quando o Sofascore gravou o confronto invertido (precisa trocar 1X↔X2 no DC)."""
    cands = idx.get(frozenset((_canon(home), _canon(away))))
    if not cands:
        return None
    try:
        gd = date.fromisoformat(d)
    except (TypeError, ValueError):
        return None
    best = None
    for od_date, ch, eid in cands:
        try:
            dd = abs((date.fromisoformat(od_date) - gd).days)
        except (TypeError, ValueError):
            continue
        if dd <= 3 and (best is None or dd < best[0]):
            best = (dd, eid, ch == _canon(home))
    return best[1:] if best else None


def _load_flat_markets(conn):
    """event_id → dict de odds flat (DC/BTTS, close+open) em orientação Sofascore."""
    out = {}
    try:
        rows = conn.execute(
            "SELECT event_id, odds_dc_1x, odds_dc_x2, odds_dc_12, "
            "odds_btts_yes, odds_btts_no, "
            "odds_dc_1x_open, odds_dc_x2_open, odds_dc_12_open, "
            "odds_btts_yes_open, odds_btts_no_open FROM sofascore_matches").fetchall()
    except Exception:
        return out
    for r in rows:
        out[r[0]] = {"dc_1x": r[1], "dc_x2": r[2], "dc_12": r[3],
                     "btts_yes": r[4], "btts_no": r[5],
                     "dc_1x_open": r[6], "dc_x2_open": r[7], "dc_12_open": r[8],
                     "btts_yes_open": r[9], "btts_no_open": r[10]}
    return out


def _load_lines(conn):
    """event_id → {(market, line): (odd_a, odd_b, odd_a_open, odd_b_open)}."""
    out = {}
    try:
        rows = conn.execute(
            "SELECT event_id, market, line, odd_a, odd_b, odd_a_open, odd_b_open "
            "FROM odds_lines").fetchall()
    except Exception:
        return out
    for eid, mkt, line, a, b, ao, bo in rows:
        out.setdefault(eid, {})[(mkt, line)] = (a, b, ao, bo)
    return out


def _settle_extended(r, eid, home_oriented, flat, lines, ctx,
                     res_1x2, hs, as_, total, oh, od_, oa, ou_line,
                     min_edge, max_edge, ledger):
    """Liquida os mercados SEM push (BTTS, DC, OU meia-linha) reusando _settle.
    DNB e AH (com push) ficam para o passo 4b."""
    fm = flat.get(eid, {})

    # --- BTTS (orientação-livre: simétrico sob troca de mando) ---
    if fm.get("btts_yes") and fm.get("btts_no"):
        p_yes = r["btts"]
        sh_b, _z, _o = shin_probabilities([fm["btts_yes"], fm["btts_no"]])
        won_yes = int(hs >= 1 and as_ >= 1)
        ctx["result"] = "yes" if won_yes else "no"
        for sel, p_m, o_cl, o_op, sp, won in (
                ("yes", p_yes, fm["btts_yes"], fm["btts_yes_open"], sh_b[0], won_yes),
                ("no", 1.0 - p_yes, fm["btts_no"], fm["btts_no_open"], sh_b[1], 1 - won_yes)):
            bet = _settle("btts", sel, p_m, sp, o_op, o_cl, won, ctx, min_edge, max_edge)
            if bet:
                ledger.append(bet)

    # --- Double Chance (precisa do 1X2; Shin VEM do 1X2 combinado, não das
    #     odds de DC — 1X/X2/12 se sobrepõem e somam ~2.0) ---
    if (None not in (oh, od_, oa)
            and all(fm.get(k) for k in ("dc_1x", "dc_x2", "dc_12"))):
        # odds em orientação Sofascore → orienta ao mando martj42 (swap 1X↔X2)
        if home_oriented:
            cl = {"1X": fm["dc_1x"], "X2": fm["dc_x2"], "12": fm["dc_12"]}
            op = {"1X": fm["dc_1x_open"], "X2": fm["dc_x2_open"], "12": fm["dc_12_open"]}
        else:
            cl = {"1X": fm["dc_x2"], "X2": fm["dc_1x"], "12": fm["dc_12"]}
            op = {"1X": fm["dc_x2_open"], "X2": fm["dc_1x_open"], "12": fm["dc_12_open"]}
        sh, _z, _o = shin_probabilities([oh, od_, oa])      # orientado a martj42
        p_dc = {"1X": r["p_win"] + r["p_draw"],
                "X2": r["p_draw"] + r["p_loss"],
                "12": r["p_win"] + r["p_loss"]}
        sh_dc = {"1X": sh[0] + sh[1], "X2": sh[1] + sh[2], "12": sh[0] + sh[2]}
        won_dc = {"1X": int(res_1x2 in ("home", "draw")),
                  "X2": int(res_1x2 in ("draw", "away")),
                  "12": int(res_1x2 in ("home", "away"))}
        ctx["result"] = res_1x2
        for sel in ("1X", "X2", "12"):
            bet = _settle("dc", sel, p_dc[sel], sh_dc[sel], op[sel], cl[sel],
                          won_dc[sel], ctx, min_edge, max_edge)
            if bet:
                ledger.append(bet)

    # --- OU multi-linha (só MEIA-linha: sem push). Pula 2.5 (bloco legado) e
    #     linhas inteiras (push → 4b). AH também é 4b. ---
    for (mkt, line), (a, b, a_op, b_op) in lines.get(eid, {}).items():
        if mkt != "ou" or not (a and b):
            continue
        if abs(line - ou_line) < 1e-9:                 # 2.5 já no bloco legado
            continue
        if abs((line % 1) - 0.5) > 1e-9:               # linha inteira → push → 4b
            continue
        p_over = mp.over_under(r["grid"], line)["Over"]
        sh_ou, _z, _o = shin_probabilities([a, b])
        won_over = int(total > line)
        ctx["result"] = "over" if won_over else "under"
        for sel, p_m, o_cl, o_op, sp, won in (
                ("over", p_over, a, a_op, sh_ou[0], won_over),
                ("under", 1.0 - p_over, b, b_op, sh_ou[1], 1 - won_over)):
            bet = _settle(f"ou{line}", sel, p_m, sp, o_op, o_cl, won, ctx, min_edge, max_edge)
            if bet:
                ledger.append(bet)


def _settle(market, selection, p_model, p_shin_close, odd_open, odd_close,
            won, ctx, min_edge, max_edge):
    """Monta uma linha do ledger se a aposta passa na janela de edge.

    Preço da aposta = ABERTURA quando existe (janela viável da vida real),
    fechamento como paliativo na base histórica (bet_at marca a população —
    no relatório elas não se misturam). Gatilho e P&L liquidam no preço
    pactuado. CLV = odd_pactuada × p_shin_close − 1: a régua de baixa
    variância — o mercado fechou a meu favor? NOTA: na população
    bet_at='close' o CLV é tautológico (mede o preço contra ele mesmo
    de-vigado ⇒ ~−vig sistemático); só a população 'open' carrega sinal."""
    odd = odd_open if (odd_open and odd_open > 1.0) else odd_close
    bet_at = "open" if (odd_open and odd_open > 1.0) else "close"
    if odd is None or odd <= 1.0:
        return None
    raw_imp = 1.0 / odd
    edge_price = p_model - raw_imp
    if not (min_edge < edge_price <= max_edge):
        return None
    clv = round(odd * float(p_shin_close) - 1.0, 4)
    row = {
        "date": ctx["date"], "competition": ctx["competition"],
        "home": ctx["home"], "away": ctx["away"],
        "market": market, "selection": selection, "offered_odd": round(odd, 3),
        "odd_close": round(odd_close, 3) if odd_close else None,
        "bet_at": bet_at,
        "raw_implied": round(raw_imp, 4), "shin_prob": round(float(p_shin_close), 4),
        "model_prob": round(p_model, 4), "elo_diff": ctx["elo_diff"],
        "lambda_home": ctx["lambda_home"], "lambda_away": ctx["lambda_away"],
        "edge_vs_shin": round(p_model - float(p_shin_close), 4),
        "edge_vs_price": round(edge_price, 4),
        "ev": round(p_model * odd - 1.0, 4),
        "clv": clv, "beat_close": int(clv > 0),
        "score": ctx["score"], "result": ctx["result"], "won": won,
        "stake": 1.0, "pnl": round((odd - 1.0) if won else -1.0, 3),
        "longshot": int(odd >= 5.0), "big_edge": int(edge_price >= 0.15),
        "params_mode": "frozen",
    }
    return row


def run_backtest(cfg, conn):
    bt = cfg.get("backtest", {})
    min_edge = float(bt.get("min_edge", 0.0))
    max_edge = float(bt.get("max_edge", 1.0))
    ou_line = float(bt.get("over_under_line", 2.5))

    rows = conn.execute(
        "SELECT date, home_team, away_team, home_score, away_score, tournament, neutral "
        "FROM matches WHERE home_score IS NOT NULL ORDER BY date").fetchall()
    if not rows:
        return None
    # PARIDADE TRAIN/SERVE (fix da auditoria, P1): aplica a MESMA janela do cron
    # (window_years no Elo) — senão o Quality Gate mede um Elo diferente do servido.
    window = cfg["elo"].get("window_years")
    if window:
        cut = (date.fromisoformat(rows[-1][0]) - timedelta(days=int(window * 365.25))).isoformat()
        rows = [r for r in rows if r[0] >= cut]
    _, history = ratings.compute_ratings(rows, cfg["elo"])

    odds = _load_odds(conn)
    if not odds:
        return None

    # Mercados estendidos (Fase 1): índice por event_id + odds flat e de linha.
    # Caminho paralelo — não interfere no casamento 1X2/OU legado.
    ext_index = _load_ext_index(conn)
    flat_markets = _load_flat_markets(conn)
    line_markets = _load_lines(conn)

    # Instrumentação do buraco silencioso: par de nomes que o _canon não
    # reconcilia (variante fora do _ALIASES) era descartado calado — odds
    # coletadas em rede limpa sumiam e a amostra encolhia sem aviso. A perda
    # continua (não inventamos casamento), mas agora é visível e nomeada.
    match_pairs = {frozenset((_canon(r[1]), _canon(r[2]))) for r in rows}
    orphans = [k for k in odds if k not in match_pairs]
    if orphans:
        n_rows = sum(len(odds[k]) for k in orphans)
        exemplos = "; ".join(" x ".join(sorted(k)) for k in orphans[:5])
        print(f"aviso: {n_rows} jogo(s) com odds sem par na base "
              f"(nomes não reconciliados?): {exemplos}")

    test_idx = [i for i, r in enumerate(rows) if _find_odds(odds, r[1], r[2], r[0])]
    if not test_idx:
        return None

    # PARIDADE: params frozen ajustados na janela de CALIBRAÇÃO antes do teste
    # (mesma do cron: calibration_window_years), não em todo o passado pré-teste.
    # Sem a chave (configs mínimos de teste) cai no comportamento antigo.
    cal_years = cfg["model"].get("calibration_window_years")
    if cal_years:
        first_test_date = rows[test_idx[0]][0]
        cal_cut = (date.fromisoformat(first_test_date)
                   - timedelta(days=int(cal_years * 365.25))).isoformat()
        hist_cal = [h for h, r in zip(history, rows) if cal_cut <= r[0] < first_test_date]
        params = model.fit_goal_model(hist_cal or history[:test_idx[0]])
    else:
        params = model.fit_goal_model(history[:test_idx[0]])
    max_goals = cfg["model"]["max_goals"]

    ledger = []
    n_partial = 0
    for i in test_idx:
        d, home, away, hs, as_, tournament, neutral = rows[i]
        found = _find_odds(odds, home, away, d)
        (oh, od_, oa), (o_over, o_under), x12_open, ou_open = found
        diff = history[i][0]
        # max_goals NOMEADO (auditoria P5): posicional caía em delta_vorp_a e,
        # com params de 5 elementos (theta != 0), corrompia as probabilidades.
        r = model.predict_match(diff, 0.0, params, 0.0, max_goals=max_goals)

        total = hs + as_
        ctx = {
            "date": d, "competition": tournament, "home": home, "away": away,
            "elo_diff": round(diff, 1),
            "lambda_home": round(r["lambda_a"], 3), "lambda_away": round(r["lambda_b"], 3),
            "score": f"{hs}-{as_}",
        }
        res_1x2 = "home" if hs > as_ else ("draw" if hs == as_ else "away")
        res_ou = "over" if total > ou_line else "under"

        # --- mercado 1X2 (Shin SEMPRE no fechamento: consenso final do mercado) ---
        # Mercado PARCIAL (parser devolveu None numa seleção): pula o MERCADO,
        # não o jogo — antes uma única linha assim matava o backtest inteiro
        # com TypeError dentro do Shin, sem processar nem os jogos saudáveis.
        if None in (oh, od_, oa):
            n_partial += 1
        else:
            ctx["result"] = res_1x2
            p1x2 = {"home": r["p_win"], "draw": r["p_draw"], "away": r["p_loss"]}
            closed = {"home": oh, "draw": od_, "away": oa}
            opened = {"home": x12_open[0], "draw": x12_open[1], "away": x12_open[2]}
            sh, _z, _ov = shin_probabilities([oh, od_, oa])
            p_shin = {"home": sh[0], "draw": sh[1], "away": sh[2]}
            for sel in OUTCOMES:
                bet = _settle("1x2", sel, p1x2[sel], p_shin[sel], opened[sel], closed[sel],
                              int(sel == res_1x2), ctx, min_edge, max_edge)
                if bet:
                    ledger.append(bet)

        # --- mercado Over/Under (o motor já gera a prob na matriz) ---
        if o_over and o_under:
            p_over = r["over"].get(ou_line)
            if p_over is not None:
                ctx["result"] = res_ou
                p_under = 1.0 - p_over
                sh_ou, _z2, _ov2 = shin_probabilities([o_over, o_under])
                for sel, p_m, o_open, o_close, sp in (
                        ("over", p_over, ou_open[0], o_over, sh_ou[0]),
                        ("under", p_under, ou_open[1], o_under, sh_ou[1])):
                    bet = _settle("ou25", sel, p_m, sp, o_open, o_close,
                                  int(sel == res_ou), ctx, min_edge, max_edge)
                    if bet:
                        ledger.append(bet)

        # --- mercados estendidos sem push (BTTS, DC, OU meia-linha) ---
        ev = _find_event(ext_index, home, away, d)
        if ev:
            eid, home_oriented = ev
            _settle_extended(r, eid, home_oriented, flat_markets, line_markets, ctx,
                             res_1x2, hs, as_, total, oh, od_, oa, ou_line,
                             min_edge, max_edge, ledger)
    if n_partial:
        print(f"aviso: {n_partial} jogo(s) com mercado 1X2 parcial (odd faltando) "
              f"— mercado pulado, jogo mantido")
    return params, ledger


def _persist(conn, ledger):
    cols = list(ledger[0].keys())
    def sqltype(v):
        return "REAL" if isinstance(v, float) else ("INTEGER" if isinstance(v, int) else "TEXT")
    conn.execute("DROP TABLE IF EXISTS backtest_bets")
    conn.execute("CREATE TABLE backtest_bets (id INTEGER PRIMARY KEY, " +
                 ", ".join(f"{c} {sqltype(ledger[0][c])}" for c in cols) + ")")
    conn.executemany(
        f"INSERT INTO backtest_bets ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        [tuple(b[c] for c in cols) for b in ledger])
    conn.commit()
    path = ROOT / "data" / "backtest_bets.csv"
    path.parent.mkdir(exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(ledger)
    return path


def _line(label, bets):
    n = len(bets)
    if not n:
        return
    staked = sum(b["stake"] for b in bets)
    pnl = sum(b["pnl"] for b in bets)
    wins = sum(b["won"] for b in bets)
    print(f"  {label:<10}{n:>5} apostas{wins:>5} acertos ({wins / n:>5.1%})"
          f"{pnl:>+9.2f}u{pnl / staked:>+8.1%} ROI")


def _report(ledger):
    print(f"total: {len(ledger)} apostas | "
          f"P&L {sum(b['pnl'] for b in ledger):+.2f}u | "
          f"ROI {sum(b['pnl'] for b in ledger) / sum(b['stake'] for b in ledger):+.1%}")
    print("\npor mercado — onde o motor encontra borda:")
    for mkt in sorted({b["market"] for b in ledger}):
        _line(mkt, [b for b in ledger if b["market"] == mkt])

    print("\nCLV — a régua de baixa variância (odd pactuada × Shin do fechamento − 1):")
    for label, pop in (("open", [b for b in ledger if b["bet_at"] == "open"]),
                       ("close*", [b for b in ledger if b["bet_at"] == "close"])):
        if not pop:
            print(f"  {label:<8}    0 apostas — sem dados (cron de 2026 ainda não acumulou)")
            continue
        mean_clv = sum(b["clv"] for b in pop) / len(pop)
        beat = sum(b["beat_close"] for b in pop) / len(pop)
        print(f"  {label:<8}{len(pop):>5} apostas | CLV médio {mean_clv:+.2%} | "
              f"bateram o fechamento {beat:.1%}")
    print("  (*) população 'close' é paliativa: aposta no próprio fechamento ⇒ CLV ≈ −vig"
          "\n      por construção. Sinal real só na população 'open'. IC 95%: src.bootstrap")

    print("\ncalibração por faixa de edge (vs preço) — o veredito genial vs ruído:")
    print(f"  {'faixa':<12}{'n':>5}{'prob média':>12}{'acerto real':>13}{'ROI/aposta':>12}")
    for lo, hi in [(0.0, 0.05), (0.05, 0.10), (0.10, 0.15), (0.15, 1.01)]:
        b = [x for x in ledger if lo <= x["edge_vs_price"] < hi]
        if not b:
            continue
        avg_p = sum(x["model_prob"] for x in b) / len(b)
        hit = sum(x["won"] for x in b) / len(b)
        roi = sum(x["pnl"] for x in b) / len(b)
        print(f"  {f'{lo:.0%}-{hi:.0%}':<12}{len(b):>5}{avg_p:>12.1%}{hit:>13.1%}{roi:>12.1%}")


def _emit_telemetry(ledger):
    """Telemetria JSONL do Quality Gate (Shadow v2): resultado estruturado do backtest."""
    staked = sum(b["stake"] for b in ledger)
    pnl = sum(b["pnl"] for b in ledger)
    open_clv = [b["clv"] for b in ledger if b["bet_at"] == "open"]
    emit_event(
        "wc", "backtest_completed",
        metrics={"n_bets": len(ledger),
                 "roi": round(pnl / staked, 4) if staked else 0.0,
                 "clv_open_mean": round(sum(open_clv) / len(open_clv), 4) if open_clv else 0.0},
        metadata={"params_mode": "frozen", "shadow": "v2"})


def main():
    cfg = load_config()
    conn = db.connect(str(ROOT / cfg["database"]))
    out = run_backtest(cfg, conn)
    if not out:
        sys.exit("sem odds históricas no banco — rode `python -m src.ingest_sofascore`")
    params, ledger = out
    if not ledger:
        sys.exit("nenhuma aposta de valor (P_modelo > 1/odd) na janela")
    _report(ledger)
    _emit_telemetry(ledger)
    path = _persist(conn, ledger)
    print(f"\nledger: tabela backtest_bets + {path}")


if __name__ == "__main__":
    main()
