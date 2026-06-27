"""Verificacao do resultado Maher: (1) teste pareado de significancia do dBrier,
(2) estabilidade temporal (Brier por ano). Mesmo setup do maher.py."""
import os, sys, math
import numpy as np
import statistics as st
from datetime import date, timedelta
from scipy.optimize import minimize
from scipy.stats import nbinom
sys.path.insert(0, os.getcwd())
from src import db, model, ratings
from src.ingest import ROOT, load_config
cfg=load_config(); conn=db.connect(str(ROOT/cfg["database"]))
rows=conn.execute("SELECT date,home_team,away_team,home_score,away_score,tournament,neutral FROM matches WHERE home_score IS NOT NULL ORDER BY date").fetchall()
w=cfg["elo"]["window_years"]; cut=(date.fromisoformat(rows[-1][0])-timedelta(days=int(w*365.25))).isoformat()
rows=[r for r in rows if r[0]>=cut]; _,hist=ratings.compute_ratings(rows,cfg["elo"]); MAXG=cfg["model"]["max_goals"]
ftd="2026-06-01"; cy=cfg["model"]["calibration_window_years"]
ccut=(date.fromisoformat(ftd)-timedelta(days=int(cy*365.25))).isoformat()
a_b,b_b,alpha,rho=model.fit_goal_model([h for h,r in zip(hist,rows) if ccut<=r[0]<ftd])
K=np.arange(MAXG+1)
def gp(lh,la):
    r=1.0/max(alpha,1e-9); pa=nbinom.pmf(K,r,r/(r+lh)); pb=nbinom.pmf(K,r,r/(r+la))
    g=np.outer(pa,pb); g[0,0]*=1-lh*la*rho; g[0,1]*=1+lh*rho; g[1,0]*=1+la*rho; g[1,1]*=1-rho
    g=np.clip(g,0,None); g/=g.sum(); return float(np.tril(g,-1).sum()),float(np.trace(g)),float(np.triu(g,1).sum())
def brier(p,y): return sum((p[k]-(1 if k==y else 0))**2 for k in range(3))
def fit_maher(win,lr):
    tm=sorted(set([g[1] for g in win])|set([g[2] for g in win])); idx={t:i for i,t in enumerate(tm)}; N=len(tm)
    hi=np.array([idx[g[1]] for g in win]); ai=np.array([idx[g[2]] for g in win]); nn=np.array([0.0 if g[6] else 1.0 for g in win])
    hg=np.array([g[3] for g in win],float); ag=np.array([g[4] for g in win],float); mu0=math.log(max(np.r_[hg,ag].mean(),1e-3))
    def fg(p):
        mu,gam=p[0],p[1]; atk=p[2:2+N]; dfn=p[2+N:2+2*N]
        lph=mu+atk[hi]-dfn[ai]+gam*nn; lpa=mu+atk[ai]-dfn[hi]; lh=np.exp(lph); la=np.exp(lpa)
        nll=float(np.sum(lh-hg*lph+la-ag*lpa)+lr*(np.sum(atk**2)+np.sum(dfn**2))); rh=lh-hg; ra=la-ag
        gat=np.zeros(N); np.add.at(gat,hi,rh); np.add.at(gat,ai,ra); gat+=2*lr*atk
        gdf=np.zeros(N); np.add.at(gdf,ai,-rh); np.add.at(gdf,hi,-ra); gdf+=2*lr*dfn
        return nll,np.concatenate([[float(np.sum(rh+ra))],[float(np.sum(rh*nn))],gat,gdf])
    res=minimize(fg,np.r_[mu0,0.0,np.zeros(2*N)],jac=True,method="L-BFGS-B")
    return res.x[0],res.x[1],dict(zip(tm,res.x[2:2+N])),dict(zip(tm,res.x[2+N:2+2*N]))
def ml(par,g):
    mu,gam,atk,dfn=par
    return math.exp(mu+atk.get(g[1],0)-dfn.get(g[2],0)+(0 if g[6] else gam)), math.exp(mu+atk.get(g[2],0)-dfn.get(g[1],0))
WIN=int(4*365.25)
def window(end): lo=(date.fromisoformat(end)-timedelta(days=WIN)).isoformat(); return [r for r in rows if lo<=r[0]<end]
LR=3
months=[]; y,m=2024,1
while (y,m)<=(2026,5):
    months.append((y,m)); m+=1
    if m>12: m=1;y+=1
def ms(y,m): return f"{y:04d}-{m:02d}-01"
def me(y,m): return ms(y+1,1) if m==12 else ms(y,m+1)
diffs=[]; by_year={}  # year -> [bM, bB]
for (y,m) in months:
    s,e=ms(y,m),me(y,m); par=fit_maher(window(s),LR)
    for i,r in enumerate(rows):
        if not (s<=r[0]<e): continue
        y3=0 if r[3]>r[4] else (1 if r[3]==r[4] else 2)
        lh,la=ml(par,r); pM=gp(lh,la); d=hist[i][0]/400.0; pB=gp(math.exp(a_b+b_b*d),math.exp(a_b-b_b*d))
        bM,bB=brier(pM,y3),brier(pB,y3); diffs.append(bB-bM)  # >0 = Maher melhor
        by_year.setdefault(r[0][:4],[]).append((bM,bB))
d=np.array(diffs); n=len(d); mean=d.mean(); se=d.std(ddof=1)/math.sqrt(n); t=mean/se
print(f"=== TESTE PAREADO do dBrier (n={n}) ===")
print(f"  dBrier medio (baseline - Maher): {mean:+.4f} | SE {se:.4f} | t = {t:.1f}")
print(f"  IC 95%: [{mean-1.96*se:+.4f}, {mean+1.96*se:+.4f}] -> {'SIGNIFICATIVO' if abs(t)>2 else 'nao significativo'}")
print(f"  jogos em que Maher foi melhor: {(d>0).sum()}/{n} ({(d>0).mean():.0%})")
print(f"\n=== ESTABILIDADE TEMPORAL (Brier por ano) ===")
print(f"  {'ano':<6}{'n':>5}{'Maher':>9}{'baseline':>10}{'delta':>9}")
for yr in sorted(by_year):
    g=by_year[yr]; bm=st.mean(x[0] for x in g); bb=st.mean(x[1] for x in g)
    print(f"  {yr:<6}{len(g):>5}{bm:>9.4f}{bb:>10.4f}{bb-bm:>+9.4f}")
