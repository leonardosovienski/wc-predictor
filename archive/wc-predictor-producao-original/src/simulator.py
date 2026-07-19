"""Simulador de Monte Carlo do torneio (Parte 5).

Monta a Copa a partir das fixtures no banco — os grupos são derivados do grafo de
confrontos, sem hardcode — amostra placares do motor (Binomial Negativa) e roda o
torneio N vezes para estimar P(avançar), P(cada fase) e P(título).

Fatores contextuais (fatores humanos):
- Incentivo (Vergonha de Gijón): na última rodada, se um empate garante a
  classificação dos dois, o lambda de ataque de ambos cai INCENTIVE_CUT.
- Expulsão (versão pragmática): taxa-base de vermelho por jogo, com queda de lambda
  proporcional ao tempo jogado com um a menos. A versão temporal completa (minuto a
  minuto, com probabilidade de vermelho por t) é um sub-projeto à parte.

Aproximação conhecida: o mata-mata usa emparelhamento sorteado, não o chaveamento
oficial 2026 dos 8 melhores terceiros (tabela fixa da FIFA). Mantém a incerteza
realista sem fingir precisão de bracket que não temos.
"""
import math
import random
import sys
from collections import defaultdict

import numpy as np

from . import db
from .ingest import ROOT, load_config

INCENTIVE_CUT = 0.35        # corte de lambda quando o empate convém aos dois
RED_RATE = 0.22             # vermelhos por time por jogo (taxa-base agregada)
RED_LAMBDA_PENALTY = 0.45   # queda máxima de lambda do time com um a menos

STAGES = ["grupos", "mata-mata", "oitavas", "quartas", "semi", "final", "campeão"]
_NEXT = {32: "oitavas", 16: "quartas", 8: "semi", 4: "final", 2: "campeão"}


def derive_groups(conn):
    fx = conn.execute("SELECT home_team, away_team FROM matches "
                      "WHERE home_score IS NULL AND tournament='FIFA World Cup'").fetchall()
    adj = defaultdict(set)
    for h, a in fx:
        adj[h].add(a)
        adj[a].add(h)
    seen, groups = set(), []
    for t in adj:
        if t in seen:
            continue
        stack, comp = [t], []
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            comp.append(x)
            stack.extend(adj[x] - seen)
        if len(comp) == 4:
            groups.append(comp)
    return groups


def _lambdas(ta, tb, elo, params):
    a, b = params[0], params[1]
    diff = (elo.get(ta, 1500) - elo.get(tb, 1500)) / 400.0   # Copa = campo neutro
    return math.exp(a + b * diff), math.exp(a - b * diff)


def _red_factor():
    if random.random() < RED_RATE:
        frac_remaining = (90.0 - random.uniform(0, 90)) / 90.0
        return 1.0 - RED_LAMBDA_PENALTY * frac_remaining
    return 1.0


def _sample(lam, alpha):
    n = 1.0 / max(alpha, 1e-9)
    return int(np.random.negative_binomial(n, n / (n + lam)))


def _play(ta, tb, elo, params, cut=1.0):
    alpha = params[2]
    lam_a, lam_b = _lambdas(ta, tb, elo, params)
    ga = _sample(lam_a * cut * _red_factor(), alpha)
    gb = _sample(lam_b * cut * _red_factor(), alpha)
    return ga, gb


def _empate_classifica_ambos(ti, tj, pts, teams):
    """True se, com um empate, ambos terminam matematicamente no top 2 — mesmo
    no melhor caso do perseguidor (que pode somar +3). Aproxima o cenário de Gijón."""
    others = [t for t in teams if t not in (ti, tj)]
    best_chaser = max(pts[t] for t in others) + 3
    return min(pts[ti], pts[tj]) + 1 > best_chaser


def _simulate_group(teams, elo, params):
    pts = defaultdict(int)
    gf = defaultdict(int)
    ga = defaultdict(int)
    schedule = [[(0, 1), (2, 3)], [(0, 2), (1, 3)], [(0, 3), (1, 2)]]
    for rnd, games in enumerate(schedule):
        for i, j in games:
            ti, tj = teams[i], teams[j]
            cut = 1.0
            if rnd == 2 and _empate_classifica_ambos(ti, tj, pts, teams):
                cut = 1.0 - INCENTIVE_CUT
            gi, gj = _play(ti, tj, elo, params, cut)
            gf[ti] += gi; ga[ti] += gj
            gf[tj] += gj; ga[tj] += gi
            if gi > gj:
                pts[ti] += 3
            elif gi < gj:
                pts[tj] += 3
            else:
                pts[ti] += 1; pts[tj] += 1
    ranked = sorted(teams, key=lambda t: (pts[t], gf[t] - ga[t], gf[t]), reverse=True)
    table = {t: (pts[t], gf[t] - ga[t], gf[t]) for t in teams}
    return ranked, table


def _knockout_winner(ta, tb, elo, params):
    ga, gb = _play(ta, tb, elo, params)
    if ga != gb:
        return ta if ga > gb else tb
    pa = 1.0 / (1.0 + 10 ** (-(elo.get(ta, 1500) - elo.get(tb, 1500)) / 400.0))
    return ta if random.random() < pa else tb   # pênaltis, leve peso à força


def run_tournament(groups, elo, params):
    reached = {}
    qualifiers, thirds = [], []
    for teams in groups:
        ranked, table = _simulate_group(teams, elo, params)
        for t in teams:
            reached[t] = "grupos"
        qualifiers += ranked[:2]
        thirds.append((ranked[2], table[ranked[2]]))
    thirds.sort(key=lambda x: x[1], reverse=True)
    qualifiers += [t for t, _ in thirds[:8]]
    for t in qualifiers:
        reached[t] = "mata-mata"

    bracket = qualifiers[:]
    random.shuffle(bracket)
    while len(bracket) > 1:
        winners = [_knockout_winner(bracket[i], bracket[i + 1], elo, params)
                   for i in range(0, len(bracket), 2)]
        stage = _NEXT[len(bracket)]
        for t in winners:
            reached[t] = stage
        bracket = winners
    return reached


def monte_carlo(n=10000):
    cfg = load_config()
    conn = db.connect(str(ROOT / cfg["database"]))
    elo = db.load_elo(conn)
    prow = db.load_params(conn)
    if not elo or not prow:
        sys.exit("cache vazio — rode `python -m src.cron_update_models` primeiro")
    params = (prow[0], prow[1], prow[2], prow[3])
    groups = derive_groups(conn)
    if len(groups) != 12:
        sys.exit(f"esperava 12 grupos, derivei {len(groups)} — fixtures incompletas?")

    rank = {s: i for i, s in enumerate(STAGES)}
    best = defaultdict(lambda: defaultdict(int))
    for _ in range(n):
        for t, s in run_tournament(groups, elo, params).items():
            best[t][s] += 1

    rows = []
    for t, dist in best.items():
        cum = {}
        for s in STAGES:
            cum[s] = sum(c for st, c in dist.items() if rank[st] >= rank[s]) / n
        rows.append((t, cum))
    rows.sort(key=lambda r: r[1]["campeão"], reverse=True)
    return rows


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10000
    print(f"simulando a Copa {n} vezes...\n")
    rows = monte_carlo(n)
    print(f"{'seleção':<22}{'avança':>8}{'quartas':>9}{'semi':>7}{'final':>7}{'título':>8}")
    print("-" * 61)
    for t, c in rows[:16]:
        print(f"{t:<22}{c['oitavas']:>8.1%}{c['quartas']:>9.1%}"
              f"{c['semi']:>7.1%}{c['final']:>7.1%}{c['campeão']:>8.1%}")


if __name__ == "__main__":
    main()
