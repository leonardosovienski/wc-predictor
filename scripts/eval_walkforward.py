"""Avaliacao WALK-FORWARD (sem lookahead) do modelo na Copa 2026 + comparacao
com o mercado. Reproduz os numeros de docs/RELATORIO_VIABILIDADE.md.

Replica a metodologia do src.backtest (Elo forward, params frozen) mas avalia
TODOS os jogos disputados — nao so os de aposta — e mede skill contra o acaso e
contra o mercado (Shin), que e o juiz de verdade.

Uso:  python scripts/eval_walkforward.py   (a partir da raiz do repo)
"""
import os
import sys
import math
import statistics as st
from datetime import date, timedelta

sys.path.insert(0, os.getcwd())
from src import db, model, ratings
from src.ingest import ROOT, load_config
from src.math_utils import shin_probabilities
from src.predict import _canon

cfg = load_config()
conn = db.connect(str(ROOT / cfg["database"]))

# --- passada forward identica ao backtest (Elo so ve o passado) ---
rows = conn.execute(
    "SELECT date, home_team, away_team, home_score, away_score, tournament, neutral "
    "FROM matches WHERE home_score IS NOT NULL ORDER BY date").fetchall()
window = cfg["elo"].get("window_years")
if window:
    cut = (date.fromisoformat(rows[-1][0]) - timedelta(days=int(window * 365.25))).isoformat()
    rows = [r for r in rows if r[0] >= cut]
_, history = ratings.compute_ratings(rows, cfg["elo"])

test_idx = [i for i, r in enumerate(rows)
            if r[5] == "FIFA World Cup" and r[0] >= "2026-06-01"]
first_test_date = rows[test_idx[0]][0]

# params frozen calibrados ANTES da Copa (mesma janela do backtest)
cy = cfg["model"].get("calibration_window_years")
ccut = (date.fromisoformat(first_test_date) - timedelta(days=int(cy * 365.25))).isoformat()
params = model.fit_goal_model([h for h, r in zip(history, rows) if ccut <= r[0] < first_test_date])
MAXG = cfg["model"]["max_goals"]

# odds -> probabilidades de mercado (Shin)
om = {}
for d, h, a, oh, od, oa in conn.execute(
        "SELECT date,home_team,away_team,odds_home,odds_draw,odds_away "
        "FROM sofascore_matches WHERE odds_home IS NOT NULL").fetchall():
    om.setdefault(frozenset((_canon(h), _canon(a))), []).append((d, _canon(h), oh, od, oa))

def market(h, a, d):
    c = om.get(frozenset((_canon(h), _canon(a))))
    if not c:
        return None
    gd = date.fromisoformat(d); best = None
    for od_date, ch, oh, od, oa in c:
        try:
            dd = abs((date.fromisoformat(od_date) - gd).days)
        except Exception:
            continue
        if dd <= 3 and (best is None or dd < best[0]):
            sh, _z, _o = shin_probabilities([oh, od, oa])
            best = (dd, (sh[0], sh[1], sh[2]) if ch == _canon(h) else (sh[2], sh[1], sh[0]))
    return best[1] if best else None

def brier(p, y):
    return sum((p[k] - (1 if k == y else 0)) ** 2 for k in range(3))
def logloss(p, y):
    return -math.log(max(p[y], 1e-9))

m_brier = []; u_brier = []; m_acc = []; m_ll = []
mb = []; mk_brier = []; mk_acc = []; mk_ll = []
fav_m = []; fav_r = []; dr_m = []; dr_r = []
agree = dis = dis_m = dis_k = 0

for i in test_idx:
    d, h, a, hs, as_, t, neu = rows[i]
    diff = history[i][0]
    r = model.predict_match(diff, 0.0, params, 0.0, MAXG)
    pm = (r["p_win"], r["p_draw"], r["p_loss"])
    y = 0 if hs > as_ else (1 if hs == as_ else 2)
    m_brier.append(brier(pm, y)); u_brier.append(brier((1/3, 1/3, 1/3), y))
    m_ll.append(logloss(pm, y))
    m_acc.append(int(max(range(3), key=lambda k: pm[k]) == y))
    fav_m.append(pm[0] if diff >= 0 else pm[2])
    fav_r.append(int((hs > as_) if diff >= 0 else (as_ > hs)))
    dr_m.append(pm[1]); dr_r.append(int(hs == as_))
    mk = market(h, a, d)
    if mk:
        mb.append(brier(pm, y)); mk_brier.append(brier(mk, y))
        mk_ll.append(logloss(mk, y))
        mk_acc.append(int(max(range(3), key=lambda k: mk[k]) == y))
        mp = max(range(3), key=lambda k: pm[k]); kp = max(range(3), key=lambda k: mk[k])
        if mp == kp:
            agree += 1
        else:
            dis += 1; dis_m += (mp == y); dis_k += (kp == y)

N = len(test_idx); n_mkt = len(mb)
print("=" * 60)
print(f"WALK-FORWARD — {N} jogos da Copa 2026 (sem lookahead) | {n_mkt} c/ odds")
print("=" * 60)
print("\n[1] SKILL ABSOLUTO (Brier; 0=perfeito, 0.667=acaso)")
print(f"    modelo {st.mean(m_brier):.4f}  vs  acaso {st.mean(u_brier):.4f}  "
      f"-> {'bate' if st.mean(m_brier) < st.mean(u_brier) else 'perde p/'} o acaso")
print("\n[2] O JUIZ — MODELO vs MERCADO (mesmos jogos)")
print(f"    Brier   modelo {st.mean(mb):.4f} | mercado {st.mean(mk_brier):.4f}")
print(f"    Logloss modelo {st.mean(m_ll):.4f} | mercado {st.mean(mk_ll):.4f}")
print(f"    Acerto  modelo {st.mean(m_acc):.1%} | mercado {st.mean(mk_acc):.1%}")
print(f"    -> {'MODELO bate' if st.mean(mb) < st.mean(mk_brier) else 'MERCADO bate'} "
      f"(dif Brier {st.mean(mb) - st.mean(mk_brier):+.4f})")
print("\n[3] DISCORDANCIA (onde nasce a aposta de valor)")
print(f"    concordam {agree} ({agree/n_mkt:.0%}) | discordam {dis} ({dis/n_mkt:.0%})")
if dis:
    print(f"    discordando: modelo acerta {dis_m}/{dis} ({dis_m/dis:.0%}) | "
          f"mercado {dis_k}/{dis} ({dis_k/dis:.0%})")
print("\n[4] VIES (walk-forward)")
print(f"    P(favorito) modelo {st.mean(fav_m):.1%} | favorito venceu {st.mean(fav_r):.1%}")
print(f"    P(empate)   modelo {st.mean(dr_m):.1%} | empate real   {st.mean(dr_r):.1%}")
