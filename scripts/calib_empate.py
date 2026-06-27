"""Etapa 2.4: calibracao de EMPATE POR FAIXAS (nao media).
- Modelo: holdout grande 2024->2026-05 (2424 jogos, SEM odds) -> N alto.
- Mercado: Copa 2026 (N=60 com odds) -> limitacao declarada.
Pergunta: o modelo tem defeito de empate? (se calibrado em N alto -> nao tem)"""
import os, sys, math
import statistics as st
from datetime import date, timedelta
sys.path.insert(0, os.getcwd())
from src import db, model, ratings
from src.ingest import ROOT, load_config
from src.math_utils import shin_probabilities
from src.predict import _canon

cfg = load_config()
conn = db.connect(str(ROOT / cfg["database"]))
rows = conn.execute("SELECT date,home_team,away_team,home_score,away_score,tournament,neutral "
    "FROM matches WHERE home_score IS NOT NULL ORDER BY date").fetchall()
w=cfg["elo"]["window_years"]
cut=(date.fromisoformat(rows[-1][0])-timedelta(days=int(w*365.25))).isoformat()
rows=[r for r in rows if r[0]>=cut]
_,hist=ratings.compute_ratings(rows,cfg["elo"])
wc=[i for i,r in enumerate(rows) if r[5]=="FIFA World Cup" and r[0]>="2026-06-01"]
ftd=rows[wc[0]][0]; cy=cfg["model"]["calibration_window_years"]
ccut=(date.fromisoformat(ftd)-timedelta(days=int(cy*365.25))).isoformat()
params=model.fit_goal_model([h for h,r in zip(hist,rows) if ccut<=r[0]<ftd])
MAXG=cfg["model"]["max_goals"]

hold=[i for i,r in enumerate(rows) if "2024-01-01"<=r[0]<"2026-06-01"]
print(f"=== CALIBRACAO DE EMPATE DO MODELO — holdout {len(hold)} jogos (sem odds) ===")
pts=[]
for i in hold:
    r=model.predict_match(hist[i][0],0.0,params,home_adv=0.0,max_goals=MAXG)
    pts.append((r["p_draw"], 1 if rows[i][3]==rows[i][4] else 0))
print(f"  {'faixa P(empate)':<18}{'n':>5}{'previu':>9}{'observado':>11}{'gap':>8}")
bands=[(0,.20),(.20,.23),(.23,.26),(.26,.30),(.30,1)]
brier_d=0
for lo,hi in bands:
    g=[p for p in pts if lo<=p[0]<hi]
    if not g: continue
    pv=st.mean(x[0] for x in g); ob=st.mean(x[1] for x in g)
    print(f"  {f'{lo:.0%}-{hi:.0%}':<18}{len(g):>5}{pv:>9.1%}{ob:>11.1%}{ob-pv:>+8.1%}")
# brier do empate (one-vs-rest)
bd=st.mean((p-y)**2 for p,y in pts)
print(f"  Brier do empate (one-vs-rest): {bd:.4f} | base rate observado: {st.mean(y for _,y in pts):.1%}")

# mercado na Copa (N=60) — limitacao
print(f"\n=== CALIBRACAO DE EMPATE DO MERCADO — Copa 2026 (N pequeno!) ===")
om={}
for d,h,a_,oh,od,oa in conn.execute("SELECT date,home_team,away_team,odds_home,odds_draw,odds_away "
    "FROM sofascore_matches WHERE odds_home IS NOT NULL").fetchall():
    om.setdefault(frozenset((_canon(h),_canon(a_))),[]).append((d,oh,od,oa))
mpts=[]
for i in wc:
    d,h,a_,hs,as_,t,neu=rows[i]
    c=om.get(frozenset((_canon(h),_canon(a_))))
    if not c: continue
    gd=date.fromisoformat(d);best=None
    for od_date,oh,od,oa in c:
        try:dd=abs((date.fromisoformat(od_date)-gd).days)
        except:continue
        if dd<=3 and (best is None or dd<best[0]): best=(dd,(oh,od,oa))
    if not best: continue
    sh,_z,_o=shin_probabilities(list(best[1]))
    mpts.append((sh[1], 1 if hs==as_ else 0))
print(f"  jogos: {len(mpts)} | P(empate) mercado medio: {st.mean(x[0] for x in mpts):.1%} | "
      f"empate observado: {st.mean(y for _,y in mpts):.1%}")
print(f"  -> diferenca de {st.mean(y for _,y in mpts)-st.mean(x[0] for x in mpts):+.1%}, MAS N={len(mpts)}:")
print("     insuficiente para calibracao por faixas confiavel. NAO conclui que o")
print("     mercado sub-precifica empate — fica como HIPOTESE (falta odds historicas).")
