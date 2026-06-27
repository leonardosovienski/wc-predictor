"""Experimentos causais: por que o filtro so gera azarao?
Separa a contribuicao do MODELO (compressao de Elo) da do FILTRO (geometria do
edge = p - 1/odd em odds altas).

Controle: modelo walk-forward real.
Exp B: p = mercado (Shin) exato -> o filtro gera azarao mesmo com prob perfeita?
Exp C: p = Shin + ruido N(0,sigma) -> o filtro AMPLIFICA ruido simetrico em odd alta?
Exp A: Elo de-comprimido (b*k) -> de-comprimir tira o vies?
Filtro identico ao backtest: 0.02 < (p - 1/odd) <= 0.15.
"""
import os, sys
import numpy as np
from datetime import date, timedelta
sys.path.insert(0, os.getcwd())
from src import db, model, ratings
from src.ingest import ROOT, load_config
from src.math_utils import shin_probabilities
from src.predict import _canon

MIN_E, MAX_E = 0.02, 0.15
rng = np.random.default_rng(42)

cfg = load_config()
conn = db.connect(str(ROOT / cfg["database"]))
rows = conn.execute("SELECT date,home_team,away_team,home_score,away_score,tournament,neutral "
    "FROM matches WHERE home_score IS NOT NULL ORDER BY date").fetchall()
w = cfg["elo"]["window_years"]
cut=(date.fromisoformat(rows[-1][0])-timedelta(days=int(w*365.25))).isoformat()
rows=[r for r in rows if r[0]>=cut]
_,hist=ratings.compute_ratings(rows,cfg["elo"])
wc=[i for i,r in enumerate(rows) if r[5]=="FIFA World Cup" and r[0]>="2026-06-01"]
ftd=rows[wc[0]][0]; cy=cfg["model"]["calibration_window_years"]
ccut=(date.fromisoformat(ftd)-timedelta(days=int(cy*365.25))).isoformat()
params=model.fit_goal_model([h for h,r in zip(hist,rows) if ccut<=r[0]<ftd])
a,b,al,rho=params; MAXG=cfg["model"]["max_goals"]

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
    oh,od,oa=o
    sh,_z,_ov=shin_probabilities([oh,od,oa])
    fav=0 if oh<=oa else 2  # indice da selecao favorita (0=home,2=away)
    games.append({"diff":hist[i][0],"odd":[oh,od,oa],"shin":list(sh),
                  "fav":fav,"und":2-fav})  # und = oposto

def role_of(g, k):
    if k==1: return "empate"
    return "favorito" if k==g["fav"] else "azarao"

def conta(probs_fn, label, draws=1):
    """probs_fn(g, rng) -> [p_home,p_draw,p_away]. Conta apostas por papel."""
    cnt={"favorito":0,"empate":0,"azarao":0}; tot=0
    for _ in range(draws):
        for g in games:
            p=probs_fn(g)
            for k in range(3):
                edge=p[k]-1.0/g["odd"][k]
                if MIN_E < edge <= MAX_E:
                    cnt[role_of(g,k)]+=1; tot+=1
    if tot==0:
        print(f"  {label:<34} 0 apostas")
        return
    print(f"  {label:<34} {tot/draws:>5.0f} apostas/exec | "
          f"fav {cnt['favorito']/tot:>4.0%} | empate {cnt['empate']/tot:>4.0%} | "
          f"AZARAO {cnt['azarao']/tot:>4.0%}")

def model_probs(g, k=1.0):
    r=model.predict_match(g["diff"],0.0,(a,b*k,al,rho),home_adv=0.0,max_goals=MAXG)
    return [r["p_win"],r["p_draw"],r["p_loss"]]

print(f"jogos: {len(games)} | filtro: {MIN_E:.0%} < (p - 1/odd) <= {MAX_E:.0%}\n")
print("CONTROLE (modelo real walk-forward):")
conta(lambda g: model_probs(g,1.0), "modelo Elo (k=1.0)")

print("\nEXP B (p = MERCADO Shin exato — modelo perfeito):")
conta(lambda g: g["shin"], "p = mercado (sem desvio)")

print("\nEXP C (p = Shin + ruido N(0,sigma), 500 execucoes — o filtro amplifica?):")
def noisy(g, sigma):
    p=np.array(g["shin"])+rng.normal(0,sigma,3)
    p=np.clip(p,1e-3,None); p/=p.sum()
    return p.tolist()
for sg in (0.03,0.06,0.10):
    conta(lambda g,s=sg: noisy(g,s), f"sigma={sg:.2f} (ruido simetrico)", draws=500)

print("\nEXP A (Elo DE-COMPRIMIDO b*k — de-comprimir muda o papel?):")
for k in (1.0,1.3,1.6,2.0):
    conta(lambda g,kk=k: model_probs(g,kk), f"b x {k:.1f}")
