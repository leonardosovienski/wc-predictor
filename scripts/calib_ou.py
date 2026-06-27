"""Calibracao (1X2) + avaliacao Over/Under vs mercado — anexo do peer-review
de docs/RELATORIO_VIABILIDADE.md. Mesma metodologia walk-forward do
eval_walkforward.py.

Uso:  python scripts/calib_ou.py   (a partir da raiz do repo)
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
window = cfg["elo"]["window_years"]
cut = (date.fromisoformat(rows[-1][0]) - timedelta(days=int(window * 365.25))).isoformat()
rows = [r for r in rows if r[0] >= cut]
_, history = ratings.compute_ratings(rows, cfg["elo"])
test_idx = [i for i, r in enumerate(rows) if r[5] == "FIFA World Cup" and r[0] >= "2026-06-01"]
ftd = rows[test_idx[0]][0]
cy = cfg["model"]["calibration_window_years"]
ccut = (date.fromisoformat(ftd) - timedelta(days=int(cy * 365.25))).isoformat()
params = model.fit_goal_model([h for h, r in zip(history, rows) if ccut <= r[0] < ftd])
MAXG = cfg["model"]["max_goals"]
OU = cfg["backtest"]["over_under_line"]

oou = {}
for d, h, a, oov, oun in conn.execute(
        "SELECT date,home_team,away_team,odds_over,odds_under "
        "FROM sofascore_matches WHERE odds_over IS NOT NULL AND odds_under IS NOT NULL").fetchall():
    oou.setdefault(frozenset((_canon(h), _canon(a))), []).append((d, oov, oun))
def near(h, a, d):
    c = oou.get(frozenset((_canon(h), _canon(a))))
    if not c:
        return None
    gd = date.fromisoformat(d); best = None
    for rec in c:
        try:
            dd = abs((date.fromisoformat(rec[0]) - gd).days)
        except Exception:
            continue
        if dd <= 3 and (best is None or dd < best[0]):
            best = (dd, rec)
    return best[1] if best else None

# (1) calibracao 1X2 — pool das 3 saidas
pairs = []
for i in test_idx:
    d, h, a, hs, as_, t, neu = rows[i]
    r = model.predict_match(history[i][0], 0.0, params, 0.0, MAXG)
    pm = (r["p_win"], r["p_draw"], r["p_loss"])
    y = 0 if hs > as_ else (1 if hs == as_ else 2)
    for k in range(3):
        pairs.append((pm[k], 1 if k == y else 0))
print("DIAGRAMA DE CALIBRACAO 1X2 (pool das 3 saidas)")
print(f"  {'faixa':<14}{'n':>4}{'previu':>10}{'real':>9}  vies")
for lo, hi in [(0, .10), (.10, .20), (.20, .30), (.30, .45), (.45, 1.01)]:
    g = [p for p in pairs if lo <= p[0] < hi]
    if not g:
        continue
    pm_ = st.mean(x[0] for x in g); re = st.mean(x[1] for x in g)
    flag = "super-confiante" if pm_ > re + .05 else ("sub-confiante" if re > pm_ + .05 else "ok")
    print(f"  {f'{lo:.0%}-{hi:.0%}':<14}{len(g):>4}{pm_:>10.1%}{re:>9.1%}  {flag}")

# (2) Over/Under vs mercado
def brier2(p, y):
    return (p - y) ** 2 + ((1 - p) - (1 - y)) ** 2
mb = []; kb = []; ma = []; ka = []
for i in test_idx:
    d, h, a, hs, as_, t, neu = rows[i]
    ou = near(h, a, d)
    if not ou:
        continue
    _, oov, oun = ou
    pov = model.predict_match(history[i][0], 0.0, params, 0.0, MAXG)["over"].get(OU)
    if pov is None:
        continue
    y = 1 if (hs + as_) > OU else 0
    sh, _z, _o = shin_probabilities([oov, oun])
    mb.append(brier2(pov, y)); kb.append(brier2(sh[0], y))
    ma.append(int((pov >= .5) == (y == 1))); ka.append(int((sh[0] >= .5) == (y == 1)))
print(f"\nOVER/UNDER {OU} — MODELO vs MERCADO ({len(mb)} jogos)")
if mb:
    print(f"  Brier  modelo {st.mean(mb):.4f} | mercado {st.mean(kb):.4f}")
    print(f"  Acerto modelo {st.mean(ma):.1%} | mercado {st.mean(ka):.1%}")
    print(f"  -> {'MODELO bate' if st.mean(mb) < st.mean(kb) else 'mercado bate'} "
          f"(dif {st.mean(mb) - st.mean(kb):+.4f})")
