"""Exp F (ampliado): quanto o Dixon-Coles (rho) causa o excesso de EMPATES?
Curva rho: original, x0.5, x0.25, x0 (DC desligado). Intervencao em UM parametro.
Mede: distribuicao das apostas por papel, Brier, LogLoss, P(empate)_mod - mercado,
e a massa de empate do modelo (P(draw) medio)."""
import os, sys, math
import statistics as st
from datetime import date, timedelta
sys.path.insert(0, os.getcwd())
from src import db, model, ratings
from src.ingest import ROOT, load_config
from src.math_utils import shin_probabilities
from src.predict import _canon

MIN_E, MAX_E = 0.02, 0.15
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
a,b,al,rho=model.fit_goal_model([h for h,r in zip(hist,rows) if ccut<=r[0]<ftd])
MAXG=cfg["model"]["max_goals"]
print(f"rho ajustado (original) = {rho:+.4f}\n")

om={}
for d,h,a_,oh,od,oa in conn.execute("SELECT date,home_team,away_team,odds_home,odds_draw,odds_away "
    "FROM sofascore_matches WHERE odds_home IS NOT NULL").fetchall():
    om.setdefault(frozenset((_canon(h),_canon(a_))),[]).append((d,_canon(h),oh,od,oa))
def odds(h,a_,d):
    c=om.get(frozenset((_canon(h),_canon(a_))))
    if not c: return None
    gd=date.fromisoformat(d);best=None
    for od_date,ch,oh,o_d,oa in c:
        try:dd=abs((date.fromisoformat(od_date)-gd).days)
        except:continue
        if dd<=3 and (best is None or dd<best[0]):
            best=(dd,(oh,o_d,oa) if ch==_canon(h) else (oa,o_d,oh))
    return best[1] if best else None

games=[]
for i in wc:
    d,h,a_,hs,as_,t,neu=rows[i]
    o=odds(h,a_,d)
    if not o: continue
    oh,od,oa=o; sh,_z,_ov=shin_probabilities([oh,od,oa])
    y=0 if hs>as_ else (1 if hs==as_ else 2)
    games.append({"diff":hist[i][0],"odd":[oh,od,oa],"shin":list(sh),
                  "fav":0 if oh<=oa else 2,"y":y})

def brier(p,y): return sum((p[k]-(1 if k==y else 0))**2 for k in range(3))

print(f"{'rho':<14}{'fav':>6}{'empate':>8}{'azarao':>8}{'apostas':>9}"
      f"{'Brier':>8}{'LogL':>7}{'Pdraw_mod':>11}{'draw-mkt':>10}")
for scale,lbl in [(1.0,"original"),(0.5,"x0.50"),(0.25,"x0.25"),(0.0,"=0 (NB pura)")]:
    rr=rho*scale
    cnt={"fav":0,"emp":0,"aza":0}; tot=0; brs=[]; lls=[]; pdraws=[]; difs=[]
    for g in games:
        r=model.predict_match(g["diff"],0.0,(a,b,al,rr),home_adv=0.0,max_goals=MAXG)
        p=[r["p_win"],r["p_draw"],r["p_loss"]]
        brs.append(brier(p,g["y"])); lls.append(-math.log(max(p[g["y"]],1e-9)))
        pdraws.append(p[1]); difs.append(p[1]-g["shin"][1])
        for k in range(3):
            if MIN_E < p[k]-1/g["odd"][k] <= MAX_E:
                role="emp" if k==1 else ("fav" if k==g["fav"] else "aza")
                cnt[role]+=1; tot+=1
    fa,em,az=(cnt['fav']/tot,cnt['emp']/tot,cnt['aza']/tot) if tot else (0,0,0)
    print(f"{lbl:<14}{fa:>6.0%}{em:>8.0%}{az:>8.0%}{tot:>9}"
          f"{st.mean(brs):>8.4f}{st.mean(lls):>7.3f}{st.mean(pdraws):>11.1%}{st.mean(difs):>+10.1%}")

print("\nLeitura: se ao zerar rho a coluna 'empate' DESPENCA -> DC e a causa do excesso.")
print("         se 'empate' persistir -> a causa NAO e o rho (e a divergencia de")
print("         empate vs mercado tem outra origem). Brier/LogL mostram o custo.")
