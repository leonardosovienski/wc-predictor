"""Exp A revisitado: escalar b (de-comprimir) QUEBRA a calibracao?
Holdout 2024->2026-05 (2424 jogos, sem odds). Mede Brier/LogLoss/sharpness por k."""
import os, sys, math
import statistics as st
from datetime import date, timedelta
sys.path.insert(0, os.getcwd())
from src import db, model, ratings
from src.ingest import ROOT, load_config
cfg=load_config(); conn=db.connect(str(ROOT/cfg["database"]))
rows=conn.execute("SELECT date,home_team,away_team,home_score,away_score,tournament,neutral FROM matches WHERE home_score IS NOT NULL ORDER BY date").fetchall()
w=cfg["elo"]["window_years"]; cut=(date.fromisoformat(rows[-1][0])-timedelta(days=int(w*365.25))).isoformat()
rows=[r for r in rows if r[0]>=cut]; _,hist=ratings.compute_ratings(rows,cfg["elo"])
ftd="2026-06-01"; cy=cfg["model"]["calibration_window_years"]
ccut=(date.fromisoformat(ftd)-timedelta(days=int(cy*365.25))).isoformat()
a,b,al,rho=model.fit_goal_model([h for h,r in zip(hist,rows) if ccut<=r[0]<ftd])
MAXG=cfg["model"]["max_goals"]
hold=[i for i,r in enumerate(rows) if "2024-01-01"<=r[0]<"2026-06-01"]
def brier(p,y): return sum((p[k]-(1 if k==y else 0))**2 for k in range(3))
print(f"b ajustado (MLE) = {b:.3f}\n")
print(f"{'b x k':<10}{'b efetivo':>10}{'Brier':>9}{'LogL':>8}{'probMax':>9}{'P(draw)':>9}{'gap_draw':>10}")
for k in (1.0,1.3,1.6,2.0):
    brs=[];lls=[];mx=[];pd=[];obs_d=[]
    for i in hold:
        r=model.predict_match(hist[i][0],0.0,(a,b*k,al,rho),home_adv=0.0,max_goals=MAXG)
        p=[r["p_win"],r["p_draw"],r["p_loss"]]; y=0 if rows[i][3]>rows[i][4] else (1 if rows[i][3]==rows[i][4] else 2)
        brs.append(brier(p,y)); lls.append(-math.log(max(p[y],1e-9))); mx.append(max(p)); pd.append(p[1]); obs_d.append(1 if y==1 else 0)
    gap=st.mean(pd)-st.mean(obs_d)
    print(f"{'x'+str(k):<10}{b*k:>10.3f}{st.mean(brs):>9.4f}{st.mean(lls):>8.4f}{st.mean(mx):>9.1%}{st.mean(pd):>9.1%}{gap:>+10.1%}")
print(f"\nobservado: P(draw) real no holdout = {st.mean(obs_d):.1%}")
print("Leitura: se Brier/LogL PIORAM e gap_draw fica negativo ao subir k,")
print("de-comprimir melhora a 'cara' das apostas as custas da CALIBRACAO.")
