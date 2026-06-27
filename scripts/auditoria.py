"""Auditoria de INSPECAO (nao altera o modelo): localizar onde nasce o
comportamento 'evita favorito + concentra empate'. Etapa 2 do protocolo.
Mede: lambda (home/away/total/diff), lambda_total vs gols reais, sharpness do
1X2 modelo vs mercado, decomposicao de P(empate) por placar, e 1X2 modelo vs
mercado vs observado."""
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

lam_t=[]; lam_d=[]; gols_reais=[]; entropies_m=[]; entropies_k=[]; maxp_m=[]; maxp_k=[]
pd00=[];pd11=[];pd22=[];pd33=[];pdrest=[]; pdtot=[]
Ph=[];Pd=[];Pa=[]; Mh=[];Md=[];Ma=[]; obs=[]
def ent(p): return -sum(x*math.log(max(x,1e-9)) for x in p)
for i in wc:
    d,h,a_,hs,as_,t,neu=rows[i]
    r=model.predict_match(hist[i][0],0.0,params,home_adv=0.0,max_goals=MAXG)
    lam_t.append(r["total_goals"]); lam_d.append(r["lambda_a"]-r["lambda_b"])
    gols_reais.append(hs+as_)
    g=r["grid"]
    pdtot.append(r["p_draw"])
    pd00.append(float(g[0,0]));pd11.append(float(g[1,1]));pd22.append(float(g[2,2]));pd33.append(float(g[3,3]))
    pdrest.append(r["p_draw"]-float(g[0,0]+g[1,1]+g[2,2]+g[3,3]))
    pm=[r["p_win"],r["p_draw"],r["p_loss"]]
    Ph.append(pm[0]);Pd.append(pm[1]);Pa.append(pm[2])
    entropies_m.append(ent(pm)); maxp_m.append(max(pm))
    o=odds(h,a_,d)
    if o:
        sh,_z,_o=shin_probabilities(list(o))
        Mh.append(sh[0]);Md.append(sh[1]);Ma.append(sh[2])
        entropies_k.append(ent(sh)); maxp_k.append(max(sh))
    obs.append(0 if hs>as_ else (1 if hs==as_ else 2))

n=len(wc)
print(f"=== A) LAMBDA (gols esperados) vs REALIDADE — {n} jogos ===")
print(f"  lambda_total modelo: media {st.mean(lam_t):.2f} (dp {st.pstdev(lam_t):.2f})")
print(f"  gols reais por jogo: media {st.mean(gols_reais):.2f} (dp {st.pstdev(gols_reais):.2f})")
print(f"  |lambda_diff| medio: {st.mean(abs(x) for x in lam_d):.2f}  (separacao favorito-azarao)")
print(f"  -> modelo {'SUBESTIMA' if st.mean(lam_t)<st.mean(gols_reais) else 'superestima'} "
      f"gols em {st.mean(gols_reais)-st.mean(lam_t):+.2f}/jogo")

print(f"\n=== B) SHARPNESS do 1X2: modelo vs mercado ===")
print(f"  prob MAXIMA media:  modelo {st.mean(maxp_m):.1%} | mercado {st.mean(maxp_k):.1%}")
print(f"  entropia media:     modelo {st.mean(entropies_m):.3f} | mercado {st.mean(entropies_k):.3f}")
print(f"  -> entropia MAIOR = mais 'achatado'. Modelo e {'MAIS' if st.mean(entropies_m)>st.mean(entropies_k) else 'menos'} achatado que o mercado.")

print(f"\n=== C) DECOMPOSICAO de P(empate) — de onde vem o empate? ===")
print(f"  P(empate) total medio: {st.mean(pdtot):.1%}")
for lbl,v in [("0-0",pd00),("1-1",pd11),("2-2",pd22),("3-3",pd33),(">=4-4",pdrest)]:
    print(f"    {lbl:<6}: {st.mean(v):.1%}  ({st.mean(v)/st.mean(pdtot):.0%} do empate)")

print(f"\n=== D) 1X2: modelo vs mercado vs OBSERVADO ===")
ofreq=[obs.count(k)/n for k in range(3)]
print(f"  {'':<10}{'home':>8}{'empate':>8}{'away':>8}")
print(f"  {'modelo':<10}{st.mean(Ph):>8.1%}{st.mean(Pd):>8.1%}{st.mean(Pa):>8.1%}")
print(f"  {'mercado':<10}{st.mean(Mh):>8.1%}{st.mean(Md):>8.1%}{st.mean(Ma):>8.1%}")
print(f"  {'observado':<10}{ofreq[0]:>8.1%}{ofreq[1]:>8.1%}{ofreq[2]:>8.1%}")
print(f"\n  empate: modelo {st.mean(Pd):.1%} | mercado {st.mean(Md):.1%} | real {ofreq[1]:.1%}")
