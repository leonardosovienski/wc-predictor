"""Demonstracao empirica do vies de azarao (resposta ao peer-review que pediu
evidencia, nao mecanismo plausivel). Mostra COM dados: (1) P_modelo - P_mercado
por papel, (2) apostas-candidatas por faixa de odd, (3) teste do vig (valor vs
odd crua vs prob justa/Shin). Walk-forward, jogos da Copa 2026 com odds.

Uso:  python scripts/prova_mecanismo.py   (a partir da raiz do repo)
"""
import os
import sys
import statistics as st
from datetime import date, timedelta

sys.path.insert(0, os.getcwd())
from src import db, model, ratings
from src.ingest import ROOT, load_config
from src.math_utils import shin_probabilities
from src.predict import _canon

cfg = load_config()
conn = db.connect(str(ROOT / cfg["database"]))
rows = conn.execute(
    "SELECT date,home_team,away_team,home_score,away_score,tournament,neutral "
    "FROM matches WHERE home_score IS NOT NULL ORDER BY date").fetchall()
w = cfg["elo"]["window_years"]
cut = (date.fromisoformat(rows[-1][0]) - timedelta(days=int(w * 365.25))).isoformat()
rows = [r for r in rows if r[0] >= cut]
_, hist = ratings.compute_ratings(rows, cfg["elo"])
wc = [i for i, r in enumerate(rows) if r[5] == "FIFA World Cup" and r[0] >= "2026-06-01"]
ftd = rows[wc[0]][0]
cy = cfg["model"]["calibration_window_years"]
ccut = (date.fromisoformat(ftd) - timedelta(days=int(cy * 365.25))).isoformat()
params = model.fit_goal_model([h for h, r in zip(hist, rows) if ccut <= r[0] < ftd])
MAXG = cfg["model"]["max_goals"]

om = {}
for d, h, a, oh, od, oa in conn.execute(
        "SELECT date,home_team,away_team,odds_home,odds_draw,odds_away "
        "FROM sofascore_matches WHERE odds_home IS NOT NULL").fetchall():
    om.setdefault(frozenset((_canon(h), _canon(a))), []).append((d, _canon(h), oh, od, oa))
def odds(h, a, d):
    c = om.get(frozenset((_canon(h), _canon(a))))
    if not c:
        return None
    gd = date.fromisoformat(d); best = None
    for od_date, ch, oh, o_d, oa in c:
        try:
            dd = abs((date.fromisoformat(od_date) - gd).days)
        except Exception:
            continue
        if dd <= 3 and (best is None or dd < best[0]):
            best = (dd, (oh, o_d, oa) if ch == _canon(h) else (oa, o_d, oh))
    return best[1] if best else None

sels = []
for i in wc:
    d, h, a, hs, as_, t, neu = rows[i]
    o = odds(h, a, d)
    if not o:
        continue
    oh, od, oa = o
    r = model.predict_match(hist[i][0], 0.0, params, home_adv=0.0, max_goals=MAXG)
    pm = {"home": r["p_win"], "draw": r["p_draw"], "away": r["p_loss"]}
    sh, _z, _ov = shin_probabilities([oh, od, oa])
    shp = {"home": sh[0], "draw": sh[1], "away": sh[2]}
    oo = {"home": oh, "draw": od, "away": oa}
    fav = "home" if oh <= oa else "away"
    und = "away" if fav == "home" else "home"
    role = {"draw": "empate", fav: "favorito", und: "azarao"}
    for s in ("home", "draw", "away"):
        sels.append({"role": role[s], "odd": oo[s], "pm": pm[s], "shin": shp[s],
                     "edge_raw": pm[s] - 1 / oo[s], "edge_fair": pm[s] - shp[s]})

print(f"jogos com odds: {len(sels)//3} | selecoes: {len(sels)}\n")
print("[1] P_modelo - P_mercado(Shin) POR PAPEL")
for role in ("favorito", "empate", "azarao"):
    g = [s for s in sels if s["role"] == role]
    print(f"  {role:<9} n={len(g):>3} | P_mod-P_mkt {st.mean(s['pm']-s['shin'] for s in g):+.1%} "
          f"| acima do mercado em {sum(s['pm']>s['shin'] for s in g)/len(g):.0%}")
print("\n[2] APOSTAS-CANDIDATAS por faixa de odd")
print(f"  {'faixa':<12}{'sel':>5}{'valorRAW':>10}{'valorFAIR':>11}{'edge med':>10}")
for lo, hi in [(1.0, 1.5), (1.5, 2.0), (2.0, 3.0), (3.0, 5.0), (5.0, 99)]:
    g = [s for s in sels if lo <= s["odd"] < hi]
    if not g:
        continue
    print(f"  {f'{lo:.2f}-{hi:.2f}':<12}{len(g):>5}"
          f"{sum(s['edge_raw']>0 for s in g):>10}{sum(s['edge_fair']>0 for s in g):>11}"
          f"{st.mean(s['edge_raw'] for s in g):>10.1%}")
print("\n[3] TESTE DO VIG (valor persiste com prob justa?)")
for lbl, key in (("vs odd CRUA (com vig)", "edge_raw"), ("vs prob JUSTA (Shin)", "edge_fair")):
    v = [s for s in sels if s[key] > 0]
    u = sum(s["role"] == "azarao" for s in v)
    print(f"  {lbl:<24}: {len(v):>3} c/ valor | em azarao {u} ({u/max(len(v),1):.0%})")
print("  -> skew p/ azarao persiste na coluna FAIR => vig NAO e a causa.")
