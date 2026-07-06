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

    return out


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
