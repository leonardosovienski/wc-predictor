"""Fecha o confound do Maher. Controle = forca unica por time (str_i), MESMA
maquina (Poisson-ridge, refit mensal, janela 4a) — isola atk/def vs cadencia.
3 modelos no mesmo holdout: Elo congelado | Forca-unica batch | Maher atk/def."""
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
def prep(win):
    tm=sorted(set([g[1] for g in win])|set([g[2] for g in win])); idx={t:i for i,t in enumerate(tm)}; N=len(tm)
    hi=np.array([idx[g[1]] for g in win]); ai=np.array([idx[g[2]] for g in win]); nn=np.array([0.0 if g[6] else 1.0 for g in win])
    hg=np.array([g[3] for g in win],float); ag=np.array([g[4] for g in win],float); return tm,idx,N,hi,ai,nn,hg,ag
def fit_maher(win,lr):
    tm,idx,N,hi,ai,nn,hg,ag=prep(win); mu0=math.log(max(np.r_[hg,ag].mean(),1e-3))
    def fg(p):
        mu,gam=p[0],p[1]; atk=p[2:2+N]; dfn=p[2+N:2+2*N]; lph=mu+atk[hi]-dfn[ai]+gam*nn; lpa=mu+atk[ai]-dfn[hi]
        lh=np.exp(lph); la=np.exp(lpa); nll=float(np.sum(lh-hg*lph+la-ag*lpa)+lr*(np.sum(atk**2)+np.sum(dfn**2))); rh=lh-hg; ra=la-ag
        gat=np.zeros(N); np.add.at(gat,hi,rh); np.add.at(gat,ai,ra); gat+=2*lr*atk
        gdf=np.zeros(N); np.add.at(gdf,ai,-rh); np.add.at(gdf,hi,-ra); gdf+=2*lr*dfn
        return nll,np.concatenate([[float(np.sum(rh+ra))],[float(np.sum(rh*nn))],gat,gdf])
    r=minimize(fg,np.r_[mu0,0.0,np.zeros(2*N)],jac=True,method="L-BFGS-B"); return ("M",r.x[0],r.x[1],dict(zip(tm,r.x[2:2+N])),dict(zip(tm,r.x[2+N:2+2*N])))
def fit_str(win,lr):
    tm,idx,N,hi,ai,nn,hg,ag=prep(win); mu0=math.log(max(np.r_[hg,ag].mean(),1e-3))
    def fg(p):
        mu,gam=p[0],p[1]; s=p[2:2+N]; lph=mu+s[hi]-s[ai]+gam*nn; lpa=mu+s[ai]-s[hi]
        lh=np.exp(lph); la=np.exp(lpa); nll=float(np.sum(lh-hg*lph+la-ag*lpa)+lr*np.sum(s**2)); rh=lh-hg; ra=la-ag
        gs=np.zeros(N); np.add.at(gs,hi,rh-ra); np.add.at(gs,ai,ra-rh); gs+=2*lr*s
        return nll,np.concatenate([[float(np.sum(rh+ra))],[float(np.sum(rh*nn))],gs])
    r=minimize(fg,np.r_[mu0,0.0,np.zeros(N)],jac=True,method="L-BFGS-B"); return ("S",r.x[0],r.x[1],dict(zip(tm,r.x[2:2+N])),None)
def lam(par,g):
    typ,mu,gam,d1,d2=par
    if typ=="M": return math.exp(mu+d1.get(g[1],0)-d2.get(g[2],0)+(0 if g[6] else gam)), math.exp(mu+d1.get(g[2],0)-d2.get(g[1],0))
    return math.exp(mu+d1.get(g[1],0)-d1.get(g[2],0)+(0 if g[6] else gam)), math.exp(mu+d1.get(g[2],0)-d1.get(g[1],0))
WIN=int(4*365.25)
def window(end): lo=(date.fromisoformat(end)-timedelta(days=WIN)).isoformat(); return [r for r in rows if lo<=r[0]<end]
# tuning lam_reg p/ cada modelo na mesma validacao
t0="2024-01-01"; tv=(date.fromisoformat(t0)-timedelta(days=183)).isoformat()
wtr=window(tv); wv=[r for r in rows if tv<=r[0]<t0]
def tune(fitf):
    best=(None,1e18)
    for lr in (1,3,10,30,100):
        par=fitf(wtr,lr); dev=sum((lam(par,g)[0]-g[3]*math.log(max(lam(par,g)[0],1e-9)))+(lam(par,g)[1]-g[4]*math.log(max(lam(par,g)[1],1e-9))) for g in wv)
        if dev<best[1]: best=(lr,dev)
    return best[0]
LRm=tune(fit_maher); LRs=tune(fit_str); print(f"lam_reg: Maher={LRm} | Forca-unica={LRs}\n")
months=[]; y,m=2024,1
while (y,m)<=(2026,5):
    months.append((y,m)); m+=1
    if m>12: m=1;y+=1
def ms(y,m): return f"{y:04d}-{m:02d}-01"
def me(y,m): return ms(y+1,1) if m==12 else ms(y,m+1)
B={"elo":[],"str":[],"mah":[]}; L={"elo":[],"str":[],"mah":[]}; obs=[]
for (y,m) in months:
    s,e=ms(y,m),me(y,m); pm=fit_maher(window(s),LRm); ps=fit_str(window(s),LRs)
    for i,r in enumerate(rows):
        if not (s<=r[0]<e): continue
        y3=0 if r[3]>r[4] else (1 if r[3]==r[4] else 2); d=hist[i][0]/400.0
        pE=gp(math.exp(a_b+b_b*d),math.exp(a_b-b_b*d)); pS=gp(*lam(ps,r)); pM=gp(*lam(pm,r))
        B["elo"].append(brier(pE,y3)); B["str"].append(brier(pS,y3)); B["mah"].append(brier(pM,y3))
        obs.append(y3)
print(f"holdout {len(obs)} jogos:")
print(f"  {'modelo':<22}{'Brier':>9}")
print(f"  {'Elo congelado (orig)':<22}{st.mean(B['elo']):>9.4f}")
print(f"  {'Forca-unica (batch)':<22}{st.mean(B['str']):>9.4f}  <- controle de cadencia")
print(f"  {'Maher atk/def (batch)':<22}{st.mean(B['mah']):>9.4f}")
import numpy as _np
def pair(x,y):
    d=_np.array(x)-_np.array(y); return d.mean(), d.std(ddof=1)/math.sqrt(len(d))
mc,sc=pair(B["str"],B["mah"]); print(f"\n  forca-unica - Maher: {mc:+.4f} (SE {sc:.4f}) -> ganho de atk/def {'REAL' if mc/sc>2 else 'NAO significativo'}")
ec,esc=pair(B["elo"],B["str"]); print(f"  Elo - forca-unica  : {ec:+.4f} (SE {esc:.4f}) -> ganho de cadencia/batch {'real' if abs(ec/esc)>2 else 'desprezivel'}")
