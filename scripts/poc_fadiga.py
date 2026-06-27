"""PoC v2.0 — a feature de FADIGA (dias de descanso) bate o Elo puro?

Injeta theta*descanso na link function da Binomial Negativa (o hook que ja
existe em model.predict_match), calibra (a,b,alpha,rho,theta) por MLE no TREINO
(internacionais 2010-2023) e mede Brier no HOLDOUT massivo (2024 -> 2026-05).
A Copa 2026 (>= 2026-06) fica INTOCADA (reservada ao veredito de CLV).

Uso:  python scripts/poc_fadiga.py   (a partir da raiz do repo)
"""
import os
import sys
import math
import statistics as st
from datetime import date

import numpy as np
from scipy.optimize import minimize

sys.path.insert(0, os.getcwd())
from src import db, model, ratings
from src.ingest import ROOT, load_config
from src.model import _nb_logpmf, _tau

CAP = 5          # teto de recuperacao (dias); descanso > CAP nao ajuda mais
CENTER = 4.0     # centra a feature p/ interpretabilidade do theta

cfg = load_config()
conn = db.connect(str(ROOT / cfg["database"]))
rows = conn.execute(
    "SELECT date, home_team, away_team, home_score, away_score, tournament, neutral "
    "FROM matches WHERE home_score IS NOT NULL ORDER BY date").fetchall()

# Elo walk-forward sobre TODO o historico (ratings bem aquecidos); history[i]
# = (diff_pre_jogo, hs, as) alinhado a rows[i].
_, history = ratings.compute_ratings(rows, cfg["elo"])

# --- feature de descanso: dias desde o ultimo jogo de cada time (capado, centrado) ---
last_seen = {}
rest_h = [0.0] * len(rows)
rest_a = [0.0] * len(rows)
for i, (d, h, a, hs, as_, t, neu) in enumerate(rows):
    today = date.fromisoformat(d)
    def restc(team):
        if team not in last_seen:
            return float(CAP)  # estreia = totalmente descansado
        return float(min((today - last_seen[team]).days, CAP))
    rest_h[i] = restc(h) - CENTER
    rest_a[i] = restc(a) - CENTER
    last_seen[h] = last_seen[a] = today

# --- split temporal ---
def bucket(d):
    if "2010-01-01" <= d <= "2023-12-31":
        return "train"
    if "2024-01-01" <= d <= "2026-05-31":
        return "holdout"
    return None  # exclui Copa 2026 e pre-2010

tr = [i for i in range(len(rows)) if bucket(rows[i][0]) == "train"]
ho = [i for i in range(len(rows)) if bucket(rows[i][0]) == "holdout"]
print(f"treino: {len(tr)} jogos (2010-2023) | holdout: {len(ho)} jogos (2024 a 2026-05)")
print(f"Copa 2026 (>= 2026-06): INTOCADA\n")

# --- MLE da NB+DC COM theta*descanso, no treino ---
diffs = np.array([history[i][0] for i in tr]) / 400.0
rh = np.array([rest_h[i] for i in tr])
ra = np.array([rest_a[i] for i in tr])
hs = np.array([rows[i][3] for i in tr], dtype=float)
as_ = np.array([rows[i][4] for i in tr], dtype=float)
base_log = math.log(max(np.r_[hs, as_].mean(), 1e-3))

def negll(p, with_theta):
    a, b, log_alpha, rho, th = p
    if not with_theta:
        th = 0.0
    alpha = math.exp(log_alpha)
    lam = np.exp(a + b * diffs + th * rh)
    mu = np.exp(a - b * diffs + th * ra)
    tau = _tau(hs, as_, lam, mu, rho)
    if np.any(tau <= 1e-12):
        return 1e12
    ll = _nb_logpmf(hs, lam, alpha) + _nb_logpmf(as_, mu, alpha) + np.log(tau)
    if not np.isfinite(ll).all():
        return 1e12
    return -float(ll.sum())

x0 = [base_log, 0.3, math.log(0.1), -0.03, 0.0]
bnd = [(-3, 3), (-1, 4), (math.log(1e-4), math.log(3)), (-0.4, 0.4), (-1, 1)]
base = minimize(lambda p: negll(p, False), x0, method="L-BFGS-B", bounds=bnd).x
rest = minimize(lambda p: negll(p, True), x0, method="L-BFGS-B", bounds=bnd).x
a0, b0, al0, rho0, _ = base
a1, b1, al1, rho1, th1 = rest
al0, al1 = math.exp(al0), math.exp(al1)
print(f"BASE  (sem fadiga): a={a0:.3f} b={b0:.3f} alpha={al0:.3f} rho={rho0:.3f}")
print(f"REST  (com fadiga): a={a1:.3f} b={b1:.3f} alpha={al1:.3f} rho={rho1:.3f} "
      f"theta={th1:+.4f}")
print(f"  -> theta {'>0: mais descanso = mais gols' if th1 > 0 else '<0: efeito invertido'} "
      f"(magnitude por dia: {th1:+.4f})\n")

# --- avaliacao no HOLDOUT: Brier NB+fadiga vs NB puro ---
MAXG = cfg["model"]["max_goals"]
def brier(p, y):
    return sum((p[k] - (1 if k == y else 0)) ** 2 for k in range(3))

bb = []; br = []; ab = []; ar = []
for i in ho:
    diff = history[i][0]
    y = 0 if rows[i][3] > rows[i][4] else (1 if rows[i][3] == rows[i][4] else 2)
    pb = model.predict_match(diff, 0.0, (a0, b0, al0, rho0),
                             home_adv=0.0, max_goals=MAXG)
    pr = model.predict_match(diff, 0.0,
                             {"a": a1, "b": b1, "alpha": al1, "rho": rho1, "theta": th1},
                             home_adv=0.0, delta_vorp_a=rest_h[i], delta_vorp_b=rest_a[i],
                             max_goals=MAXG)
    Pb = (pb["p_win"], pb["p_draw"], pb["p_loss"])
    Pr = (pr["p_win"], pr["p_draw"], pr["p_loss"])
    bb.append(brier(Pb, y)); br.append(brier(Pr, y))
    ab.append(int(max(range(3), key=lambda k: Pb[k]) == y))
    ar.append(int(max(range(3), key=lambda k: Pr[k]) == y))

print(f"HOLDOUT ({len(ho)} jogos) — Brier (menor = melhor):")
print(f"  NB puro (Elo)      : {st.mean(bb):.5f}   acerto {st.mean(ab):.1%}")
print(f"  NB + fadiga (theta): {st.mean(br):.5f}   acerto {st.mean(ar):.1%}")
delta = st.mean(bb) - st.mean(br)
print(f"  -> fadiga {'MELHORA' if delta > 0 else 'PIORA'} o Brier em {delta:+.5f} "
      f"({100*delta/st.mean(bb):+.2f}%)")
# teste pareado simples: em quantos jogos a fadiga melhorou o Brier individual?
melhor = sum(1 for x, y in zip(br, bb) if x < y)
print(f"  jogos em que a fadiga melhorou a previsao: {melhor}/{len(ho)} ({melhor/len(ho):.0%})")
