"""Maher walk-forward: lambda via atk/def por time (Poisson ridge), NB+DC iguais
ao baseline. Refit mensal em janela movel de 4 anos. Compara Brier/LogL/probMax/
calib-empate vs baseline Elo (mesmo holdout 2024->2026-05)."""
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
rows=[r for r in rows if r[0]>=cut]; _,hist=ratings.compute_ratings(rows,cfg["elo"])
MAXG=cfg["model"]["max_goals"]
ftd="2026-06-01"; cy=cfg["model"]["calibration_window_years"]
ccut=(date.fromisoformat(ftd)-timedelta(days=int(cy*365.25))).isoformat()
a_b,b_b,alpha,rho=model.fit_goal_model([h for h,r in zip(hist,rows) if ccut<=r[0]<ftd])  # baseline + alpha/rho compartilhados
K=np.arange(MAXG+1)
def grid_probs(lh,la):
    r=1.0/max(alpha,1e-9)
    pa=nbinom.pmf(K,r,r/(r+lh)); pb=nbinom.pmf(K,r,r/(r+la))
    g=np.outer(pa,pb)
    g[0,0]*=1-lh*la*rho; g[0,1]*=1+lh*rho; g[1,0]*=1+la*rho; g[1,1]*=1-rho
    g=np.clip(g,0,None); g/=g.sum()
    return float(np.tril(g,-1).sum()),float(np.trace(g)),float(np.triu(g,1).sum())
def brier(p,y): return sum((p[k]-(1 if k==y else 0))**2 for k in range(3))

# --- fit Maher (Poisson ridge) numa janela de jogos ---
def fit_maher(win, lam_reg):
    teams=sorted(set([g[1] for g in win])|set([g[2] for g in win])); idx={t:i for i,t in enumerate(teams)}; N=len(teams)
    hi=np.array([idx[g[1]] for g in win]); ai=np.array([idx[g[2]] for g in win])
    nn=np.array([0.0 if g[6] else 1.0 for g in win]); hg=np.array([g[3] for g in win],float); ag=np.array([g[4] for g in win],float)
    mu0=math.log(max(np.r_[hg,ag].mean(),1e-3))
    def fg(p):
        mu,gam=p[0],p[1]; atk=p[2:2+N]; dfn=p[2+N:2+2*N]
        lph=mu+atk[hi]-dfn[ai]+gam*nn; lpa=mu+atk[ai]-dfn[hi]
        lh=np.exp(lph); la=np.exp(lpa)
        nll=float(np.sum(lh-hg*lph+la-ag*lpa)+lam_reg*(np.sum(atk**2)+np.sum(dfn**2)))
        rh=lh-hg; ra=la-ag
        gat=np.zeros(N); np.add.at(gat,hi,rh); np.add.at(gat,ai,ra); gat+=2*lam_reg*atk
        gdf=np.zeros(N); np.add.at(gdf,ai,-rh); np.add.at(gdf,hi,-ra); gdf+=2*lam_reg*dfn
        return nll, np.concatenate([[float(np.sum(rh+ra))],[float(np.sum(rh*nn))],gat,gdf])
    res=minimize(fg,np.r_[mu0,0.0,np.zeros(2*N)],jac=True,method="L-BFGS-B")
    mu,gam=res.x[0],res.x[1]; atk=res.x[2:2+N]; dfn=res.x[2+N:2+2*N]
    return mu,gam,dict(zip(teams,atk)),dict(zip(teams,dfn))

def maher_lambda(par,g):
    mu,gam,atk,dfn=par
    lh=math.exp(mu+atk.get(g[1],0)-dfn.get(g[2],0)+(0 if g[6] else gam))
    la=math.exp(mu+atk.get(g[2],0)-dfn.get(g[1],0))
    return lh,la

WIN=int(4*365.25)
def window(end):  # jogos em [end-4yr, end)
    lo=(date.fromisoformat(end)-timedelta(days=WIN)).isoformat()
    return [r for r in rows if lo<=r[0]<end]

# --- tuning de lam_reg: valida nos ultimos 6 meses do 1o treino ---
t0="2024-01-01"; tv=(date.fromisoformat(t0)-timedelta(days=183)).isoformat()
wtrain=[r for r in window(tv)]; wval=[r for r in rows if tv<=r[0]<t0]
best=(None,1e18)
for lr in (1,3,10,30,100):
    par=fit_maher(wtrain,lr)
    dev=0.0
    for g in wval:
        lh,la=maher_lambda(par,g); dev+= (lh-g[3]*math.log(max(lh,1e-9))) + (la-g[4]*math.log(max(la,1e-9)))
    if dev<best[1]: best=(lr,dev)
LR=best[0]; print(f"lambda_reg escolhido (val 6m): {LR}\n")

# --- walk-forward mensal sobre o holdout ---
months=[]
y,m=2024,1
while (y,m)<=(2026,5):
    months.append((y,m)); m+=1
    if m>12: m=1; y+=1
def mstart(y,m): return f"{y:04d}-{m:02d}-01"
def mend(y,m):
    return mstart(y+1,1) if m==12 else mstart(y,m+1)

mb=[];mb_b=[];ll=[];ll_b=[];mx=[];mx_b=[];pd=[];pd_b=[];obs=[]
row_by_i={i:r for i,r in enumerate(rows)}
for (y,m) in months:
    s,e=mstart(y,m),mend(y,m)
    par=fit_maher(window(s),LR)
    for i,r in enumerate(rows):
        if not (s<=r[0]<e): continue
        y3=0 if r[3]>r[4] else (1 if r[3]==r[4] else 2)
        lh,la=maher_lambda(par,r); pM=grid_probs(lh,la)
        d=hist[i][0]/400.0; pB=grid_probs(math.exp(a_b+b_b*d),math.exp(a_b-b_b*d))
        mb.append(brier(pM,y3)); mb_b.append(brier(pB,y3)); ll.append(-math.log(max(pM[y3],1e-9))); ll_b.append(-math.log(max(pB[y3],1e-9)))
        mx.append(max(pM)); mx_b.append(max(pB)); pd.append(pM[1]); pd_b.append(pB[1]); obs.append(1 if y3==1 else 0)

print(f"holdout: {len(mb)} jogos | {len(months)} refits mensais\n")
print(f"{'modelo':<14}{'Brier':>9}{'LogL':>9}{'probMax':>9}{'P(draw)':>9}{'gap_draw':>9}")
print(f"{'BASELINE Elo':<14}{st.mean(mb_b):>9.4f}{st.mean(ll_b):>9.4f}{st.mean(mx_b):>9.1%}{st.mean(pd_b):>9.1%}{st.mean(pd_b)-st.mean(obs):>+9.1%}")
print(f"{'MAHER atk/def':<14}{st.mean(mb):>9.4f}{st.mean(ll):>9.4f}{st.mean(mx):>9.1%}{st.mean(pd):>9.1%}{st.mean(pd)-st.mean(obs):>+9.1%}")
d=st.mean(mb_b)-st.mean(mb)
print(f"\nDelta Brier (Maher - baseline): {st.mean(mb)-st.mean(mb_b):+.4f}  -> Maher {'MELHOR' if d>0 else 'PIOR/IGUAL'}")
print(f"empate real holdout: {st.mean(obs):.1%}")
