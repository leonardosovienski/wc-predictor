"""Controle cosh-free: link assimetrico lam_home=exp(a+b1*d), lam_away=exp(a+b2*d),
b1,b2 LIVRES (quebra a simetria b2=-b1 do cosh). Mesma NB+DC, mesmo holdout.
Testa: o achatamento (probMax baixo, Brier) vem da SIMETRIA? Compara vs baseline."""
import os, sys, math
import numpy as np
import statistics as st
from datetime import date, timedelta
from scipy.optimize import minimize
sys.path.insert(0, os.getcwd())
from src import db, model, ratings
from src.ingest import ROOT, load_config
from src.model import _nb_logpmf, _tau
from scipy.stats import nbinom

cfg=load_config(); conn=db.connect(str(ROOT/cfg["database"]))
rows=conn.execute("SELECT date,home_team,away_team,home_score,away_score,tournament,neutral FROM matches WHERE home_score IS NOT NULL ORDER BY date").fetchall()
w=cfg["elo"]["window_years"]; cut=(date.fromisoformat(rows[-1][0])-timedelta(days=int(w*365.25))).isoformat()
rows=[r for r in rows if r[0]>=cut]; _,hist=ratings.compute_ratings(rows,cfg["elo"])
ftd="2026-06-01"; cy=cfg["model"]["calibration_window_years"]
ccut=(date.fromisoformat(ftd)-timedelta(days=int(cy*365.25))).isoformat()
tr=[i for i,r in enumerate(rows) if ccut<=r[0]<ftd]
ho=[i for i,r in enumerate(rows) if "2024-01-01"<=r[0]<ftd]
MAXG=cfg["model"]["max_goals"]
d=np.array([hist[i][0] for i in tr])/400.0
hs=np.array([rows[i][3] for i in tr],float); as_=np.array([rows[i][4] for i in tr],float)
base=math.log(max(np.r_[hs,as_].mean(),1e-3))

def negll(p):
    al0,b1,b2,la,rho=p; alpha=math.exp(la)
    lam=np.exp(al0+b1*d); mu=np.exp(al0+b2*d)
    tau=_tau(hs,as_,lam,mu,rho)
    if np.any(tau<=1e-12): return 1e12
    ll=_nb_logpmf(hs,lam,alpha)+_nb_logpmf(as_,mu,alpha)+np.log(tau)
    return 1e12 if not np.isfinite(ll).all() else -float(ll.sum())
res=minimize(negll,[base,0.3,-0.3,math.log(0.1),-0.03],method="L-BFGS-B",
             bounds=[(-3,3),(-2,4),(-4,2),(math.log(1e-4),math.log(3)),(-0.4,0.4)])
al0,b1,b2,la,rho_cf=res.x; alpha_cf=math.exp(la)
a_b,b_b,al_b,rho_b=model.fit_goal_model([hist[i] for i in tr])
print(f"BASELINE  (cosh): a={a_b:.3f} b={b_b:.3f}  (simetrico b2=-b)")
print(f"COSH-FREE       : a={al0:.3f} b1={b1:.3f} b2={b2:.3f}  (s={(b1-b2)/2:.3f} m={(b1+b2)/2:+.3f})")
print(f"  -> a MLE recuperou simetria? b1 ~ -b2 ? {'SIM' if abs(b1+b2)<0.15 else 'NAO'}\n")

K=np.arange(MAXG+1)
def probs(lam_a,lam_b,alpha,rho):
    r=1.0/max(alpha,1e-9)
    pa=nbinom.pmf(K,r,r/(r+lam_a)); pb=nbinom.pmf(K,r,r/(r+lam_b))
    g=np.outer(pa,pb)
    g[0,0]*=1-lam_a*lam_b*rho; g[0,1]*=1+lam_a*rho; g[1,0]*=1+lam_b*rho; g[1,1]*=1-rho
    g=np.clip(g,0,None); g/=g.sum()
    return float(np.tril(g,-1).sum()),float(np.trace(g)),float(np.triu(g,1).sum())
def brier(p,y): return sum((p[k]-(1 if k==y else 0))**2 for k in range(3))

def evalu(name, fn):
    brs=[];lls=[];mx=[];pd=[];obs=[]
    for i in ho:
        dd=hist[i][0]/400.0; p=fn(dd)
        y=0 if rows[i][3]>rows[i][4] else (1 if rows[i][3]==rows[i][4] else 2)
        brs.append(brier(p,y)); lls.append(-math.log(max(p[y],1e-9))); mx.append(max(p)); pd.append(p[1]); obs.append(1 if y==1 else 0)
    print(f"{name:<12} Brier {st.mean(brs):.4f} | LogL {st.mean(lls):.4f} | probMax {st.mean(mx):.1%} | "
          f"P(draw) {st.mean(pd):.1%} (real {st.mean(obs):.1%}, gap {st.mean(pd)-st.mean(obs):+.1%})")
evalu("BASELINE", lambda dd: probs(math.exp(a_b+b_b*dd),math.exp(a_b-b_b*dd),al_b,rho_b))
evalu("COSH-FREE", lambda dd: probs(math.exp(al0+b1*dd),math.exp(al0+b2*dd),alpha_cf,rho_cf))
