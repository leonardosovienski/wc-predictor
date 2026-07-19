"""Bootstrap de significância sobre o ledger do backtest (tabela backtest_bets).

Por quê: ROI médio de uma amostra pequena conta uma história; o intervalo de
confiança diz se a história é evidência. Reamostramos as apostas com reposição
(percentile bootstrap, 1000×) e reportamos o IC 95% da média. IC que cruza o
zero = ainda não há evidência de edge — decisão defensável, não convicção.

Duas métricas, duas naturezas:
- ROI (pnl/aposta, stake fixo 1u): Bernoulli escalada pela odd — variância
  alta, converge nas centenas/milhares. É o item 2 do roadmap.
- CLV (odd pactuada × Shin do fechamento − 1): quase-contínua, variância
  baixa — converge com dezenas. SÓ faz sentido na população bet_at='open';
  na população 'close' é tautologia (≈ −vig por construção) e fica de fora.

Roda DEPOIS de `python -m src.backtest` (que materializa o ledger).
Config opcional em backtest.: bootstrap_iterations (1000), bootstrap_seed (13).
"""
import sys

import numpy as np

from . import db
from .ingest import ROOT, load_config

BANDS = [(0.0, 0.05), (0.05, 0.10), (0.10, 0.15), (0.15, 1.01)]


def ci_mean(values, iterations: int, rng) -> tuple[float, float, float]:
    """IC 95% (percentil 2.5–97.5) da média por reamostragem com reposição.
    Amostra vazia estoura DE PROPÓSITO: size=(it, 0) faria o numpy pular a
    validação e devolver (nan, nan, nan) calado — NaN silencioso no veredito
    da hipótese é pior que exceção."""
    v = np.asarray(values, dtype=float)
    if v.size == 0:
        raise ValueError("ci_mean: amostra vazia — guarde com n >= 1 no chamador")
    idx = rng.integers(0, len(v), size=(iterations, len(v)))
    means = v[idx].mean(axis=1)
    return float(v.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def _row(label, values, iterations, rng):
    n = len(values)
    if n < 2:
        print(f"  {label:<14}{n:>5}  — amostra insuficiente")
        return
    mean, lo, hi = ci_mean(values, iterations, rng)
    sig = "✓ significativo" if (lo > 0 or hi < 0) else "cruza o zero"
    print(f"  {label:<14}{n:>5}{mean:>+10.2%}  [{lo:>+8.2%}, {hi:>+8.2%}]  {sig}")


def _section(title, bets, metric, iterations, rng):
    print(f"\n{title}")
    print(f"  {'fatia':<14}{'n':>5}{'média':>10}  {'IC 95%':^22}")
    _row("total", [b[metric] for b in bets], iterations, rng)
    for mkt in ("1x2", "ou25"):
        _row(mkt, [b[metric] for b in bets if b["market"] == mkt], iterations, rng)
    for lo, hi in BANDS:
        sub = [b[metric] for b in bets if lo <= b["edge_vs_price"] < hi]
        _row(f"edge {lo:.0%}-{hi:.0%}", sub, iterations, rng)


def main():
    cfg = load_config()
    bt = cfg.get("backtest", {})
    iterations = int(bt.get("bootstrap_iterations", 1000))
    seed = int(bt.get("bootstrap_seed", 13))
    rng = np.random.default_rng(seed)

    conn = db.connect(str(ROOT / cfg["database"]))
    try:
        cur = conn.execute("SELECT market, edge_vs_price, bet_at, pnl, clv "
                           "FROM backtest_bets")
        cols = [c[0] for c in cur.description]
        bets = [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception:
        sys.exit("tabela backtest_bets não existe — rode `python -m src.backtest` antes")
    if not bets:
        sys.exit("ledger vazio — rode `python -m src.backtest` antes")

    print(f"bootstrap: {iterations} reamostragens, seed {seed}, {len(bets)} apostas no ledger")

    _section("ROI por aposta (stake 1u) — variância alta, exige centenas:",
             bets, "pnl", iterations, rng)

    open_bets = [b for b in bets if b["bet_at"] == "open" and b["clv"] is not None]
    if open_bets:
        _section(f"CLV (população bet_at='open', n={len(open_bets)}) — a régua que "
                 "converge com dezenas:", open_bets, "clv", iterations, rng)
    else:
        print("\nCLV: nenhuma aposta na população 'open' ainda — o sinal nasce quando o"
              "\ncron de 2026 acumular abertura+fechamento. A população 'close' não entra"
              "\naqui: CLV de aposta no próprio fechamento é tautologia (≈ −vig).")


if __name__ == "__main__":
    main()
