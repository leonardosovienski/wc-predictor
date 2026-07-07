"""Camada única de apresentação: separa CÁLCULO (compute) de EXIBIÇÃO (render).

Por quê: antes deste módulo, `src/predict.py:show()` e `scripts/prever.py:main()`
faziam cálculo e `print()` misturados, cada um com sua própria cópia da lógica
de exibição — qualquer ajuste tinha que ser replicado nos dois lugares (e não
era: o `-8,7%` hardcoded em `prever.py` já tinha divergido do CLV real -8,37%
antes desta refatoração). Agora os dois entry points chamam `compute()` uma vez
e `render()` no nível de verbosidade que quiserem; `--json` é `json.dumps` do
mesmo dict que os outros níveis leem.

Níveis de verbosidade (progressive disclosure):
  0 (padrão) — O/U 2.5 (manchete, único mercado com CLV comprovado), 1X2
      completo (as 3 pernas SEMPRE aparecem — colapsar pra só o favorito
      quebraria `scripts/ci_check.py`, que faz regex por 3 percentuais, e
      esconderia incerteza real em jogos equilibrados), BTTS.
  1 (--expand) — gols esperados, edge vs preço ofertado por seleção.
  2 (--stats) — mercado Shin completo, top-5 placares, parâmetros do modelo.
  3 (--full) — matriz completa, dupla chance, draw no bet, handicap asiático,
      escanteios e cartões (SEMPRE com aviso de que não têm CLV validado).
"""
import json as _json

from . import market_pricer as mp
from .ingest import ROOT

CACHE_PATH = ROOT / "data" / "bootstrap_cache.json"

_CLV_LABELS = {
    "ou25": "Over/Under 2.5",
    "1x2": "1X2",
    "total": "geral (todos os mercados)",
}


def get_clv_summary():
    """Lê data/bootstrap_cache.json (gravado por `python -m src.bootstrap`).
    None se o cache não existe ainda — o chamador decide o fallback; nunca
    inventamos um número aqui."""
    if not CACHE_PATH.exists():
        return None
    try:
        data = _json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        return data
    except (ValueError, OSError):
        return None


def _clv_line(cache, market):
    """Texto pronto pra exibir o CLV de um mercado, ou aviso de indisponível
    — nunca um número reinventado na hora."""
    label = _CLV_LABELS[market]
    if not cache or market not in cache.get("markets", {}):
        return f"CLV ({label}): sem dado ainda (rode `python -m src.bootstrap`)"
    m = cache["markets"][market]
    sig = "SIGNIFICATIVO" if m["significant"] else "cruza o zero"
    return (f"CLV histórico ({label}): {m['mean']:+.2%} "
           f"[{m['ci_low']:+.2%}, {m['ci_high']:+.2%}]  {sig}  (n={m['n']})")


def compute(name_a, name_b, elo, params, cfg, neutral, conn=None):
    """Todo o cálculo de uma predição, sem nenhum print(). Retorna um dict
    plano — cada nível de `render()` lê um subconjunto dele; `--json` é
    `json.dumps(compute(...))` direto (por isso os valores já saem como
    float/tupla, nunca numpy).

    `neutral=False` sempre dá o mando pro time A — é a mesma semântica que
    `src/predict.py` e `scripts/prever.py` já usavam (nenhum dos dois tem
    flag pra mando do time B; se precisar, inverta a ordem dos times)."""
    from . import model
    from .predict import _market_probs

    adv = 0.0 if neutral else cfg["elo"]["home_advantage"]
    r = model.predict_match(elo[name_a], elo[name_b], params, adv,
                            max_goals=cfg["model"]["max_goals"])
    g = r["grid"]
    mk = _market_probs(conn, name_a, name_b) if conn is not None else None

    top = sorted(((i, j, float(g[i, j])) for i in range(g.shape[0])
                  for j in range(g.shape[1])), key=lambda x: -x[2])
    top5 = [{"home": i, "away": j, "prob": p} for i, j, p in top[:5]]

    out = {
        "meta": {
            "team_a": name_a, "team_b": name_b,
            "elo_a": elo[name_a], "elo_b": elo[name_b],
            "venue": "campo neutro" if neutral else f"mando de {name_a}",
        },
        "core": {
            "p_win": r["p_win"], "p_draw": r["p_draw"], "p_loss": r["p_loss"],
            "over_25": r["over"][2.5], "under_25": 1.0 - r["over"][2.5],
            "btts_yes": r["btts"], "btts_no": 1.0 - r["btts"],
            "top_score": top5[0],
            "market": mk,
        },
        "expand": {
            "lambda_a": r["lambda_a"], "lambda_b": r["lambda_b"],
            "total_goals": r["total_goals"],
            "edge_1x2": None, "edge_ou25": None,
        },
        "stats": {
            "top5_scores": top5,
            "params": {"a": params[0] if not isinstance(params, dict) else params.get("a"),
                       "b": params[1] if not isinstance(params, dict) else params.get("b"),
                       "alpha": params[2] if not isinstance(params, dict) else params.get("alpha"),
                       "rho": params[3] if not isinstance(params, dict) else params.get("rho")},
            "over_1_5": r["over"][1.5], "over_3_5": r["over"][3.5],
        },
        "full": {
            "dc": mp.double_chance(g),
            "dnb": mp.draw_no_bet(g),
            "handicap": [],
        },
    }

    if mk:
        out["expand"]["edge_1x2"] = {
            name_a: r["p_win"] - 1.0 / mk["odds_home"],
            "empate": r["p_draw"] - 1.0 / mk["odds_draw"],
            name_b: r["p_loss"] - 1.0 / mk["odds_away"],
        }
        if mk.get("odds_over") and mk.get("odds_under"):
            out["expand"]["edge_ou25"] = {
                "Over": r["over"][2.5] - 1.0 / mk["odds_over"],
                "Under": (1.0 - r["over"][2.5]) - 1.0 / mk["odds_under"],
            }

    center = -round((r["lambda_a"] - r["lambda_b"]) * 4) / 4
    for off in (-0.5, -0.25, 0.0, 0.25, 0.5):
        line = center + off
        ah = mp.asian_handicap(g, line)
        out["full"]["handicap"].append({"line": line, **ah})

    # divergência modelo-vs-mercado no favorito do modelo — é a régua que o
    # README já usa pra descrever o viés de achatamento ("divergências ≥10pp
    # não são valor"); reaproveitada aqui pro indicador de confiança.
    fav_label, fav_prob = max((name_a, r["p_win"]), ("empate", r["p_draw"]),
                              (name_b, r["p_loss"]), key=lambda x: x[1])
    divergence = None
    if mk:
        market_prob_of_fav = {name_a: mk["p_home"], "empate": mk["p_draw"],
                              name_b: mk["p_away"]}[fav_label]
        divergence = fav_prob - market_prob_of_fav
    out["core"]["favorite"] = fav_label
    out["core"]["favorite_divergence"] = divergence

    out["core"]["confidence"] = _confidence(out["core"], out["expand"], cfg)
    out["core"]["narrative"] = _narrative(out["core"])

    return out


def _confidence(core, expand, cfg):
    """Indicador ALTA/MÉDIA/BAIXA — não é vibe, são 2 réguas que o próprio
    projeto já validou: (a) edge no O/U 2.5 dentro da faixa historicamente
    lucrativa (min_edge/max_edge do config, a mesma usada no backtest); (b)
    divergência ≥10pp modelo-vs-mercado no 1X2, que o README documenta como
    viés de achatamento estrutural — NÃO valor, mesmo quando parece um edge
    grande. BAIXA nesse segundo caso é intencional: o modelo "mais confiante"
    no 1X2 é historicamente o menos confiável."""
    if not core["market"]:
        return {"level": "BAIXA", "reason": "sem odds de mercado para cross-check"}

    bt = cfg.get("backtest", {})
    min_edge, max_edge = float(bt.get("min_edge", 0.0)), float(bt.get("max_edge", 1.0))

    edge_ou = expand.get("edge_ou25")
    if edge_ou:
        best_lado, best_edge = max(edge_ou.items(), key=lambda kv: kv[1])
        if min_edge < best_edge <= max_edge:
            return {"level": "ALTA",
                    "reason": f"edge de {best_edge:+.1%} em {best_lado} (O/U 2.5) dentro da "
                             "faixa historicamente validada no backtest"}

    div = core.get("favorite_divergence")
    if div is not None and abs(div) >= 0.10:
        return {"level": "BAIXA",
                "reason": f"divergência de {div:+.1%} no 1X2 é o viés de achatamento "
                         "conhecido (README) — não é valor"}

    return {"level": "MÉDIA", "reason": "sem edge validado nem viés conhecido detectado"}


def _narrative(core):
    """Over/Under e BTTS vêm da MESMA grade — checa se contam a mesma
    história. 'Over + BTTS Sim' e 'Under + BTTS Não' são o par coerente
    (mais gols tende a vir de mais times marcando); a combinação cruzada não
    é impossível, só menos intuitiva — vale um aviso, não um bloqueio."""
    over_side = "Over" if core["over_25"] >= 0.5 else "Under"
    btts_side = "Sim" if core["btts_yes"] >= 0.5 else "Não"
    coherent = (over_side == "Over") == (btts_side == "Sim")
    return {"over_side": over_side, "btts_side": btts_side, "coherent": coherent}


def _fmt_pct(x):
    return f"{x:.1%}"


def render(data, level=0, as_json=False):
    """Imprime `data` (saída de `compute()`) no nível de verbosidade pedido.
    Cada nível INCLUI o anterior — 3 (--full) mostra tudo. `as_json=True`
    ignora `level` e imprime o dict inteiro (menos a chave 'clv_cache', que
    não faz parte do cálculo da partida)."""
    if as_json:
        print(_json.dumps(data, ensure_ascii=False, indent=2))
        return

    meta, core = data["meta"], data["core"]
    ta, tb = meta["team_a"], meta["team_b"]
    cache = get_clv_summary()

    print(f"\n{ta} (Elo {meta['elo_a']:.0f}) vs {tb} (Elo {meta['elo_b']:.0f}) — {meta['venue']}")

    # ---- Nível 0: manchete O/U 2.5, depois 1X2 completo, depois BTTS ----
    print(f"  Over/Under 2.5: over {_fmt_pct(core['over_25'])} | under {_fmt_pct(core['under_25'])}")
    print(f"  {_clv_line(cache, 'ou25')}")

    fav = max((ta, core["p_win"]), ("empate", core["p_draw"]), (tb, core["p_loss"]),
              key=lambda x: x[1])
    marker = lambda nome: " *" if nome == fav[0] else ""
    # "modelo 1X2:" (não só "1X2:") e as 3 pernas SEMPRE presentes — não é só
    # estilo, é contrato com `scripts/ci_check.py`, que faz regex por essa
    # substring esperando 3 percentuais em sequência somando ~100%.
    print(f"  modelo  1X2: {ta} {_fmt_pct(core['p_win'])}{marker(ta)} | "
          f"empate {_fmt_pct(core['p_draw'])}{marker('empate')} | "
          f"{tb} {_fmt_pct(core['p_loss'])}{marker(tb)}  (* favorito)")
    print(f"  {_clv_line(cache, '1x2')}")
    print(f"  ambos marcam: sim {_fmt_pct(core['btts_yes'])} | não {_fmt_pct(core['btts_no'])}")

    if core["market"]:
        mk = core["market"]
        print(f"  mercado (Shin): {ta} {_fmt_pct(mk['p_home'])} | empate {_fmt_pct(mk['p_draw'])} "
              f"| {tb} {_fmt_pct(mk['p_away'])}")
    else:
        print("  mercado: sem odds deste confronto no banco")

    conf = core["confidence"]
    print(f"  confiança: {conf['level']} — {conf['reason']}")

    nar = core["narrative"]
    if nar["coherent"]:
        print(f"  narrativa: -> coerente ({nar['over_side']} + BTTS {nar['btts_side']})")
    else:
        print(f"  narrativa: -> ATENÇÃO: mercados conflitantes "
              f"({nar['over_side']} + BTTS {nar['btts_side']})")

    if level < 1:
        return

    # ---- Nível 1 (--expand): evidência de suporte ----
    exp = data["expand"]
    print(f"\n[--expand] gols esperados: {exp['lambda_a']:.2f} x {exp['lambda_b']:.2f} "
          f"(total {exp['total_goals']:.2f})")
    if exp["edge_1x2"]:
        print("  edge 1X2 vs preço ofertado: " +
              " | ".join(f"{k} {v:+.1%}" for k, v in exp["edge_1x2"].items()))
    if exp["edge_ou25"]:
        print("  edge O/U 2.5 vs preço ofertado: " +
              " | ".join(f"{k} {v:+.1%}" for k, v in exp["edge_ou25"].items()))
    top = core["top_score"]
    print(f"  placar mais provável: {top['home']}x{top['away']} ({_fmt_pct(top['prob'])})")

    if level < 2:
        return

    # ---- Nível 2 (--stats): métricas complementares ----
    st = data["stats"]
    print(f"\n[--stats] over 1.5: {_fmt_pct(st['over_1_5'])} | over 3.5: {_fmt_pct(st['over_3_5'])}")
    print("  placares top-5: " +
          ", ".join(f"{s['home']}x{s['away']} ({_fmt_pct(s['prob'])})" for s in st["top5_scores"]))
    p = st["params"]
    print(f"  parâmetros do modelo: a={p['a']:.4f} b={p['b']:.4f} "
          f"alpha={p['alpha']:.4f} rho={p['rho']:.4f}")

    if level < 3:
        return

    # ---- Nível 3 (--full): dados brutos / sem validação ----
    full = data["full"]
    dc, dnb = full["dc"], full["dnb"]
    print(f"\n[--full] dupla chance: 1X {_fmt_pct(dc['1X'])} | 12 {_fmt_pct(dc['12'])} "
          f"| X2 {_fmt_pct(dc['X2'])}")
    d1, d2 = dnb["1"], dnb["2"]
    print(f"  draw no bet: {ta} {_fmt_pct(d1['win'] / (d1['win'] + d1['lose']))} | "
          f"{tb} {_fmt_pct(d2['win'] / (d2['win'] + d2['lose']))} (push {_fmt_pct(d1['push'])})")
    print(f"  handicap asiático (lado {ta}) [sem CLV próprio medido]:")
    for h in full["handicap"]:
        print(f"    {h['line']:+.2f}: win {_fmt_pct(h['win'])} | push {_fmt_pct(h['push'])} "
              f"| lose {_fmt_pct(h['lose'])}")
    print("  escanteios/cartões: não calculados aqui (exigem histórico de match_statistics —"
          " ver `scripts/prever.py`) [SEM VALIDAÇÃO — IC cruza zero, ver docs/HYPERPARAMETERS.md]")


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


def compute_event(conn, elo, ta, tb, stat_name, lines):
    """Escanteios/cartões: Poisson genérico via `event_models.py`. SEM CLV
    validado (IC cruza zero no backtest_event) — por isso fica de fora do
    Nível 0-2 e só entra via --corners/--cards ou --full, sempre rotulado.
    None-safe: <30 jogos de histórico devolve {'insufficient': True}."""
    from .event_models import fit_event_model, predict_event
    hist = _event_history(conn, stat_name, elo)
    if len(hist) < 30:
        return {"insufficient": True, "n": len(hist)}

    params = fit_event_model(hist, stat_name, distribution="poisson")
    lh, la, probs = predict_event(elo.get(ta, 1500), elo.get(tb, 1500), params)
    lam = lh + la
    out = {"insufficient": False, "n": len(hist), "b": params["b"],
           "lh": lh, "la": la, "lam": lam,
           "over": {ln: probs[f"over_{ln}"] for ln in lines}, "adjusted": None}

    wc_avg, n_wc = _tournament_avg(conn, stat_name)
    if wc_avg and len(hist) > n_wc:
        from scipy.stats import poisson as _poisson
        base_avg = sum(h["home_event"] + h["away_event"] for h in hist) / len(hist)
        lam_adj = lam * (wc_avg / base_avg)
        out["adjusted"] = {"wc_avg": wc_avg, "base_avg": base_avg, "lam_adj": lam_adj,
                           "over": {ln: 1 - _poisson.cdf(ln, lam_adj) for ln in lines}}
    return out


def render_event(nome, data, ta, tb, lines):
    if data["insufficient"]:
        print(f"\n{nome}: dados insuficientes ({data['n']} jogos) [SEM VALIDAÇÃO — "
             "ver docs/HYPERPARAMETERS.md]")
        return
    print(f"\n{nome} (n={data['n']} jogos, b={data['b']:+.2f}) "
         "[SEM VALIDAÇÃO — IC cruza zero, ver docs/HYPERPARAMETERS.md]:"
         f"  {ta} {data['lh']:.1f} + {tb} {data['la']:.1f} = {data['lam']:.1f} esperados")
    print("  modelo:   " + " | ".join(f"Ov{ln}: {data['over'][ln]:.0%}" for ln in lines))
    if data["adjusted"]:
        adj = data["adjusted"]
        print(f"  ajustado ao torneio (média Copa {adj['wc_avg']:.1f} vs base "
             f"{adj['base_avg']:.1f} -> lambda {adj['lam_adj']:.1f}): " + " | ".join(
             f"Ov{ln}: {adj['over'][ln]:.0%}" for ln in lines))


def compute_live(name_a, name_b, elo, params, cfg, neutral, cur_a, cur_b, fraction=0.5):
    """Projeção do RESTO do jogo a partir do placar atual — 2 metades (fraction=0.5
    escala os λ pré-jogo pela metade, hipótese de taxa de gol constante). SEM CLV
    validado (não existe mercado ao vivo no backtest) — sempre rotulado assim em
    `render_live`. `cur_a`/`cur_b` são os gols já feitos por name_a/name_b."""
    import numpy as np

    from . import model

    adv = 0.0 if neutral else cfg["elo"]["home_advantage"]
    rem = model.predict_remaining(elo[name_a], elo[name_b], params, adv,
                                  fraction=fraction, max_goals=cfg["model"]["max_goals"])
    g = rem["grid"]
    idx = np.arange(g.shape[0])
    i_idx, j_idx = idx.reshape(-1, 1), idx.reshape(1, -1)
    final_a, final_b = cur_a + i_idx, cur_b + j_idx

    p_a_more = 1.0 - float(g[0, :].sum())   # P(name_a marca >=1 no resto)
    p_b_more = 1.0 - float(g[:, 0].sum())

    totals_final = final_a + final_b
    flat = [((int(cur_a + i), int(cur_b + j)), float(g[i, j])) for i in idx for j in idx]
    top_final = sorted(flat, key=lambda t: -t[1])[:5]

    return {
        "meta": {"team_a": name_a, "team_b": name_b, "fraction": fraction,
                 "current_score": (cur_a, cur_b)},
        "remaining": {"lambda_a": rem["lambda_a"], "lambda_b": rem["lambda_b"],
                     "p_a_scores_more": p_a_more, "p_b_scores_more": p_b_more},
        "final": {
            "p_win": float(g[final_a > final_b].sum()),
            "p_draw": float(g[final_a == final_b].sum()),
            "p_loss": float(g[final_a < final_b].sum()),
            "over": {t: float(g[totals_final > t].sum()) for t in (1.5, 2.5, 3.5)},
            "top_scores": top_final,
        },
    }


def render_live(data):
    m, rem, fin = data["meta"], data["remaining"], data["final"]
    ta, tb = m["team_a"], m["team_b"]
    ca, cb = m["current_score"]
    print(f"\n[SEM VALIDAÇÃO — projeção de resto de jogo assume taxa de gol constante "
         "nos 90min, não calibrada com dado de minuto real; ver docs/HYPERPARAMETERS.md]")
    print(f"Placar atual: {ta} {ca} x {cb} {tb}  "
         f"(projeção pros {m['fraction']:.0%} restantes do jogo)")
    print(f"  gols esperados no resto: {ta} {rem['lambda_a']:.2f} + {tb} {rem['lambda_b']:.2f}")
    print(f"  {ta} marca mais >=1: {_fmt_pct(rem['p_a_scores_more'])} | "
         f"{tb} marca mais >=1: {_fmt_pct(rem['p_b_scores_more'])}")
    print(f"\nPlacar final projetado (atual + resto):")
    print(f"  {ta} vence: {_fmt_pct(fin['p_win'])} | empate: {_fmt_pct(fin['p_draw'])} "
         f"| {tb} vence: {_fmt_pct(fin['p_loss'])}")
    print("  Over/Under 2.5 (jogo completo): over " + _fmt_pct(fin["over"][2.5]) +
         " | under " + _fmt_pct(1.0 - fin["over"][2.5]))
    print("  placares finais mais prováveis: " +
         ", ".join(f"{h}x{a} ({_fmt_pct(p)})" for (h, a), p in fin["top_scores"]))


def render_summary_table(batch):
    """Tabela ASCII ao final do modo lote (`--fixtures N`) — sempre aparece,
    com ou sem `--resumo` (--resumo só suprime os blocos individuais acima
    dela). `batch`: lista de (date, data) onde `data` é a saída de compute()."""
    if not batch:
        return
    print("\n" + "=" * 88)
    print(f"{'data':<12}{'confronto':<26}{'favorito':<20}{'O/U 2.5':<14}{'BTTS':<8}{'conf.':<8}")
    print("-" * 88)
    for date, data in batch:
        core, meta = data["core"], data["meta"]
        ta, tb = meta["team_a"], meta["team_b"]
        fav_label = core["favorite"]
        fav_prob = {ta: core["p_win"], "empate": core["p_draw"], tb: core["p_loss"]}[fav_label]
        ou_side = "Over" if core["over_25"] >= 0.5 else "Under"
        ou_prob = core["over_25"] if ou_side == "Over" else core["under_25"]
        btts_side = "Sim" if core["btts_yes"] >= 0.5 else "Não"
        confronto = f"{ta} x {tb}"
        print(f"{str(date):<12}{confronto:<26}{fav_label + ' ' + _fmt_pct(fav_prob):<20}"
              f"{ou_side + ' ' + _fmt_pct(ou_prob):<14}{btts_side:<8}{core['confidence']['level']:<8}")
    print("=" * 88)
