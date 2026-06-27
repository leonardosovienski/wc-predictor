"""Painel do experimento de CLV nos playoffs da Copa 2026.

Mostra, a qualquer momento:
  1. Proximos jogos e se a ABERTURA ja foi capturada (= o que falta coletar).
  2. A populacao 'open' acumulada (jogos com abertura JA disputados).
  3. O CLV atual na populacao 'open' (le o ledger do backtest, se existir).
  4. Quanto falta para o veredito (alvo ~25 apostas 'open').

Uso:  python scripts/playoff_clv.py   (a partir da raiz do repo)
Rotina: coletar antes do apito -> jogos -> backtest -> rodar este painel.
"""
import os
import sys
import statistics as st

sys.path.insert(0, os.getcwd())
from src import db
from src.ingest import ROOT, load_config

ALVO_OPEN = 25  # apostas 'open' para o CLV ganhar poder estatistico

cfg = load_config()
conn = db.connect(str(ROOT / cfg["database"]))

# --- 1. proximos jogos: abertura capturada? ---
fut = conn.execute("""
    SELECT date, home_team, away_team, odds_home, odds_home_open
    FROM sofascore_matches WHERE home_score IS NULL ORDER BY date LIMIT 14
""").fetchall()
print("=" * 70)
print("PROXIMOS JOGOS — abertura capturada? (— = rode o ingest antes do apito)")
print("=" * 70)
falta_coletar = 0
for d, h, a, oh, oh_open in fut:
    tem_odds = oh is not None
    tem_open = oh_open is not None
    if "/" in (h + a) or any(ch.isdigit() for ch in (h + a)[-6:]):
        status = "chaveamento a definir"
    elif tem_open:
        status = "ABERTURA OK"
    elif tem_odds:
        status = ">> COLETAR (tem odds, sem abertura)"; falta_coletar += 1
    else:
        status = "sem odds ainda"
    print(f"  {d}  {h[:18]:<18} x {a[:18]:<18}  {status}")

# --- 2. populacao 'open' acumulada ---
n_open_total = conn.execute(
    "SELECT COUNT(1) FROM sofascore_matches WHERE odds_home_open IS NOT NULL").fetchone()[0]
n_open_played = conn.execute(
    "SELECT COUNT(1) FROM sofascore_matches "
    "WHERE home_score IS NOT NULL AND odds_home_open IS NOT NULL").fetchone()[0]
print("\n" + "=" * 70)
print("POPULACAO 'open' (a materia-prima do CLV)")
print("=" * 70)
print(f"  aberturas capturadas: {n_open_total} | ja disputadas: {n_open_played} "
      f"| no ar (vao virar CLV): {n_open_total - n_open_played}")

# --- 3. CLV na populacao 'open' (le o ledger do backtest) ---
try:
    bets = conn.execute(
        "SELECT clv, beat_close, pnl FROM backtest_bets WHERE bet_at='open'").fetchall()
except Exception:
    bets = []
print("\n" + "=" * 70)
print("CLV ATUAL — populacao 'open' (o juiz definitivo)")
print("=" * 70)
if not bets:
    print("  0 apostas 'open' no ledger ainda.")
    print("  (nasce quando um jogo com abertura capturada for disputado E o")
    print("   backtest rodar: python -m src.backtest)")
else:
    clvs = [b[0] for b in bets]
    beat = sum(b[1] for b in bets) / len(bets)
    pnl = sum(b[2] for b in bets)
    print(f"  apostas 'open': {len(bets)}")
    print(f"  CLV medio: {st.mean(clvs):+.2%} | bateram o fechamento: {beat:.0%}")
    print(f"  P&L 'open': {pnl:+.2f}u")
    falta = max(0, ALVO_OPEN - len(bets))
    if falta:
        print(f"  -> faltam ~{falta} apostas 'open' para o veredito ter poder (alvo {ALVO_OPEN})")
    else:
        print(f"  -> amostra suficiente: rode 'python -m src.bootstrap' para o IC 95%")

print("\nPLAYBOOK DOS PLAYOFFS:")
print("  ANTES do apito (captura abertura dos jogos que o chaveamento resolveu):")
print("    python -m src.ingest_sofascore")
print("  DEPOIS dos jogos (refresca resultado, recalcula, mede CLV):")
print("    python -m src.ingest          # resultados/fixtures do GitHub (martj42)")
print("    python -m src.ingest_sofascore # placar + fechamento + xG")
print("    python -m src.cron_update_models")
print("    python -m src.backtest")
print("  ACOMPANHAR a qualquer hora:")
print("    python scripts/playoff_clv.py")
