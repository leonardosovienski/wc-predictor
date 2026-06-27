"""Etapa 2.2 (CRITICA): a baixa variancia de lambda_total vem da FUNCAO ou dos DADOS?
Link: lambda_total = 2*exp(a)*cosh(b*dElo/400). cosh e quase plano perto de 0,
entao lambda_total deveria ser quase invariante POR CONSTRUCAO. Testa empirico:
bins de |dElo| -> lambda_total, lambda_diff, P(empate). Mede elasticidade."""
import os, sys, math
import statistics as st
from datetime import date, timedelta
sys.path.insert(0, os.getcwd())
from src import db, model, ratings
from src.ingest import ROOT, load_config

cfg=load_config(); conn=db.connect(str(ROOT/cfg["database"]))
rows=conn.execute("SELECT date,home_team,away_team,home_score,away_score,tournament,neutral "
    "FROM matches WHERE home_score IS NOT NULL ORDER BY date").fetchall()
w=cfg["elo"]["window_years"]
cut=(date.fromisoformat(rows[-1][0])-timedelta(days=int(w*365.25))).isoformat()
rows=[r for r in rows if r[0]>=cut]
_,hist=ratings.compute_ratings(rows,cfg["elo"])
# usa TODO o periodo recente (nao so Copa) p/ varrer a faixa de dElo
idx=[i for i,r in enumerate(rows) if r[0]>="2024-01-01"]
ftd="2026-06-01"; cy=cfg["model"]["calibration_window_years"]
ccut=(date.fromisoformat(ftd)-timedelta(days=int(cy*365.25))).isoformat()
a,b,al,rho=model.fit_goal_model([h for h,r in zip(hist,rows) if ccut<=r[0]<ftd])
MAXG=cfg["model"]["max_goals"]
print(f"params: a={a:.3f} b={b:.3f}  =>  lambda_total = 2*exp(a)*cosh(b*dElo/400) = {2*math.exp(a):.2f}*cosh(...)\n")

data=[]
for i in idx:
    diff=hist[i][0]
    r=model.predict_match(diff,0.0,(a,b,al,rho),home_adv=0.0,max_goals=MAXG)
    data.append((abs(diff), r["total_goals"], abs(r["lambda_a"]-r["lambda_b"]), r["p_draw"]))

print(f"=== BINS de |dElo| ({len(data)} jogos) — lambda_total varia? ===")
print(f"  {'|dElo|':<12}{'n':>5}{'lam_total':>11}{'lam_diff':>10}{'P(empate)':>11}{'cosh-pred':>11}")
bins=[(0,50),(50,100),(100,200),(200,350),(350,9999)]
for lo,hi in bins:
    g=[d for d in data if lo<=d[0]<hi]
    if not g: continue
    de=st.mean(d[0] for d in g)
    lt=st.mean(d[1] for d in g); ld=st.mean(d[2] for d in g); pdr=st.mean(d[3] for d in g)
    pred=2*math.exp(a)*math.cosh(b*de/400)  # previsao analitica do link
    print(f"  {f'{lo}-{hi}':<12}{len(g):>5}{lt:>11.2f}{ld:>10.2f}{pdr:>11.1%}{pred:>11.2f}")

# elasticidade: % de variacao de lam_total e lam_diff do menor ao maior bin de dElo
g0=[d for d in data if d[0]<50]; g1=[d for d in data if d[0]>=200]
lt0,lt1=st.mean(d[1] for d in g0),st.mean(d[1] for d in g1)
ld0,ld1=st.mean(d[2] for d in g0),st.mean(d[2] for d in g1)
print(f"\n=== ELASTICIDADE (do bin |dElo|<50 ao bin >=200) ===")
print(f"  lambda_total: {lt0:.2f} -> {lt1:.2f}  ({(lt1/lt0-1)*100:+.0f}%)  <- quase nao muda")
print(f"  lambda_diff : {ld0:.2f} -> {ld1:.2f}  ({(ld1/ld0-1)*100:+.0f}%)  <- muda muito")
print(f"\nLeitura: se lambda_total ~ constante e a previsao 'cosh-pred' bate com o")
print(f"observado, a baixa variancia e da FUNCAO (cosh), nao dos dados. O link so")
print(f"REDISTRIBUI gols (lambda_diff), nunca muda o TOTAL esperado por matchup.")
