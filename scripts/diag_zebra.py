"""Diagnóstico do viés de zebra + experimento de correção (NÃO toca o motor).

Mede: spread do Elo, calibração do empate, e o gap de força do favorito.
Depois varre valores de `b` (sensibilidade gol~Elo) para mostrar QUANTO de
correção alinharia a P(favorito) do modelo com a taxa real — informação para a
v2.0, não um fix para promover no meio da Copa (ver docs/VIES_ZEBRA.md).

Uso:  python scripts/diag_zebra.py    (a partir da raiz do repo)
"""
import os
import sys
import statistics as st

sys.path.insert(0, os.getcwd())
from src import db, model
from src.ingest import ROOT, load_config

cfg = load_config()
conn = db.connect(str(ROOT / cfg["database"]))
elo = db.load_elo(conn)
a, b, alpha, rho = db.load_params(conn)[:4]
MAXG = cfg["model"]["max_goals"]

rows = conn.execute(
    "SELECT home_team, away_team, home_score, away_score "
    "FROM sofascore_matches WHERE season='2026' AND home_score IS NOT NULL").fetchall()

_AL = {"south korea": "korea republic", "united states": "usa",
       "cabo verde": "cape verde", "côte d'ivoire": "ivory coast",
       "czechia": "czech republic", "türkiye": "turkey"}
elo_ci = {k.lower(): v for k, v in elo.items()}
def get_elo(n):
    n = n.lower().strip()
    return elo_ci.get(_AL.get(n, n)) or elo_ci.get(n)

games = []  # (elo_fav, elo_und, fav_is_home, resultado: 'fav'/'und'/'draw')
for h, a_, hs, as_ in rows:
    eh, ea = get_elo(h), get_elo(a_)
    if eh is None or ea is None:
        continue
    fav_home = eh >= ea
    ef, eu = (eh, ea) if fav_home else (ea, eh)
    if hs == as_:
        out = "draw"
    elif (hs > as_) == fav_home:
        out = "fav"
    else:
        out = "und"
    games.append((ef, eu, out))

n = len(games)
real_fav = sum(g[2] == "fav" for g in games) / n
real_draw = sum(g[2] == "draw" for g in games) / n
real_und = sum(g[2] == "und" for g in games) / n
print(f"=== REALIDADE ({n} jogos) ===")
print(f"  favorito vence {real_fav:.1%} | empate {real_draw:.1%} | AZARÃO vence {real_und:.1%}")

def model_split(bb):
    pf = pd = pu = 0.0
    for ef, eu, _ in games:
        r = model.predict_match(ef, eu, (a, bb, alpha, rho), 0.0, MAXG)
        pf += r["p_win"]; pd += r["p_draw"]; pu += r["p_loss"]
    return pf / n, pd / n, pu / n

print(f"\n=== VARREDURA DE b (atual = {b:.3f}) — quanto corrige o favorito? ===")
print(f"  {'b':>6} {'P(fav)':>8} {'P(empate)':>10} {'P(azarão)':>10}")
for bb in (b, 1.3, 1.5, 1.8, 2.1, 2.4):
    pf, pd, pu = model_split(bb)
    flag = "  <-- atual" if abs(bb - b) < 1e-6 else ("  ~realidade" if abs(pf - real_fav) < 0.03 else "")
    print(f"  {bb:>6.3f} {pf:>8.1%} {pd:>10.1%} {pu:>10.1%}{flag}")
print(f"\n  alvo (realidade):       P(fav) {real_fav:.1%}   P(azarão) {real_und:.1%}")
print("\n  NOTA: isto é in-sample (mesmos 56 jogos). Serve para DIMENSIONAR a")
print("  correção, não para fixá-la. O fix honesto é validado por CLV out-of-")
print("  sample em vários torneios — ver docs/VIES_ZEBRA.md.")
