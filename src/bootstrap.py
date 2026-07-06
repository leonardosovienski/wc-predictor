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

Cache para consumo por outras CLIs (`src/display.py`): toda vez que este
módulo roda, grava `data/bootstrap_cache.json` com o CLV por mercado
(população 'open'). Existe pra que `predict`/`prever` mostrem o número real
sem recalcular 1000 reamostragens a cada chamada (custaria a resposta
instantânea do cache de Elo) e sem hardcodar a string no código-fonte (o
`-8,7%` fixo em `scripts/prever.py` já tinha divergido do valor real -8,37%
antes desta mudança — exatamente o bug que este cache elimina)."""
import json
import sys

import numpy as np

from . import db
from .ingest import ROOT, load_config

BANDS = [(0.0, 0.05), (0.05, 0.10), (0.10, 0.15), (0.15, 1.01)]
CACHE_PATH = ROOT / "data" / "bootstrap_cache.json"


def ci_mean(values, iterations: int, rng) -> tuple[float, float, float]:
    """IC 95% (percentil 2.5–97.5) da média por reamostragem com reposição.
    Amostra vazia estoura DE PROPÓSITO: size=(it, 0) faria o numpy pular a
    validação e devolver (nan, nan, nan) calado — NaN silencioso no veredito
    da hipótese é pior que exceção.

    ATENÇÃO: assume observações i.i.d. Para apostas correlacionadas por jogo
    (o caso do ledger — até 9 apostas do mesmo jogo), use ci_mean_cluster."""
    v = np.asarray(values, dtype=float)
    if v.size == 0:
        raise ValueError("ci_mean: amostra vazia — guarde com n >= 1 no chamador")
    idx = rng.integers(0, len(v), size=(iterations, len(v)))
    means = v[idx].mean(axis=1)
    return float(v.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def ci_mean_cluster(pairs, iterations: int, rng) -> tuple[float, float, float]:
    """IC 95% da média por CLUSTER bootstrap (auditoria P6).

    pairs: iterável de (valor, cluster_id). Reamostra CLUSTERS (jogos) com
    reposição, não apostas individuais: apostas do mesmo jogo compartilham o
    choque do resultado (o ledger tem até 9 apostas por jogo), e o bootstrap
    i.i.d. produzia IC estreito demais — significância superestimada.
    Com 1 aposta por cluster, degenera exatamente no bootstrap i.i.d."""
    groups: dict = {}
    for v, c in pairs:
        groups.setdefault(c, []).append(float(v))
    if not groups:
        raise ValueError("ci_mean_cluster: amostra vazia — guarde com n >= 1 no chamador")
    vals_by_key = [np.asarray(vs, dtype=float) for vs in groups.values()]
    n = len(vals_by_key)
    means = np.empty(iterations, dtype=float)
    for it in range(iterations):
        idx = rng.integers(0, n, size=n)
        sample = np.concatenate([vals_by_key[i] for i in idx])
        means[it] = sample.mean()
    all_vals = np.concatenate(vals_by_key)
    return (float(all_vals.mean()),
            float(np.percentile(means, 2.5)),
            float(np.percentile(means, 97.5)))


def _game_key(b):
    """Cluster de correlação: todas as apostas do mesmo jogo compartilham o
    choque do resultado — reamostrar por jogo, não por aposta (P6)."""
    return (b["date"], b["home"], b["away"])


def _row(label, pairs, iterations, rng):
    n = len(pairs)
    n_games = len({c for _v, c in pairs})
    if n < 2:
        print(f"  {label:<14}{n:>5}  — amostra insuficiente")
        return
    mean, lo, hi = ci_mean_cluster(pairs, iterations, rng)
    # ASCII: '✓' estourava UnicodeEncodeError no console cp1252 do Windows
    sig = "SIGNIFICATIVO" if (lo > 0 or hi < 0) else "cruza o zero"
    print(f"  {label:<14}{n:>5} ({n_games:>3}j){mean:>+10.2%}  "
          f"[{lo:>+8.2%}, {hi:>+8.2%}]  {sig}")


def _section(title, bets, metric, iterations, rng):
    print(f"\n{title}")
    print(f"  {'fatia':<14}{'n':>5} {'jogos':>5}{'média':>9}  {'IC 95%':^22}")
    _row("total", [(b[metric], _game_key(b)) for b in bets], iterations, rng)
    for mkt in ("1x2", "ou25"):
        _row(mkt, [(b[metric], _game_key(b)) for b in bets if b["market"] == mkt],
             iterations, rng)
    for lo, hi in BANDS:
        sub = [(b[metric], _game_key(b)) for b in bets
               if lo <= b["edge_vs_price"] < hi]
        _row(f"edge {lo:.0%}-{hi:.0%}", sub, iterations, rng)


def _clv_cache_entry(label, pairs, iterations, rng):
    """Mesmo cálculo de `_row`, mas devolvendo dict em vez de imprimir —
    usado só pra montar o cache de CLV consumido por `src/display.py`."""
    n = len(pairs)
    if n < 2:
        return None
    n_games = len({c for _v, c in pairs})
    mean, lo, hi = ci_mean_cluster(pairs, iterations, rng)
    return {"n": n, "n_games": n_games, "mean": mean, "ci_low": lo, "ci_high": hi,
            "significant": bool(lo > 0 or hi < 0)}


def save_clv_cache(open_bets, iterations, rng, computed_at):
    """Grava data/bootstrap_cache.json com o CLV por mercado (população
    'open') pra leitura instantânea por outras CLIs — ver docstring do módulo."""
    entries = {}
    total = _clv_cache_entry("total", [(b["clv"], _game_key(b)) for b in open_bets],
                             iterations, rng)
    if total:
        entries["total"] = total
    for mkt in ("1x2", "ou25"):
        e = _clv_cache_entry(mkt, [(b["clv"], _game_key(b)) for b in open_bets
                                    if b["market"] == mkt], iterations, rng)
        if e:
            entries[mkt] = e
    CACHE_PATH.write_text(json.dumps({"computed_at": computed_at, "markets": entries},
                                     indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    cfg = load_config()
    bt = cfg.get("backtest", {})
    iterations = int(bt.get("bootstrap_iterations", 1000))
    seed = int(bt.get("bootstrap_seed", 13))
    rng = np.random.default_rng(seed)

    conn = db.connect(str(ROOT / cfg["database"]))
    try:
        cur = conn.execute("SELECT market, edge_vs_price, bet_at, pnl, clv, "
                           "date, home, away FROM backtest_bets")
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
        import datetime
        computed_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        save_clv_cache(open_bets, iterations, rng, computed_at)
        print(f"\n[cache gravado: {CACHE_PATH.relative_to(ROOT)}]")
    else:
        print("\nCLV: nenhuma aposta na população 'open' ainda — o sinal nasce quando o"
              "\ncron de 2026 acumular abertura+fechamento. A população 'close' não entra"
              "\naqui: CLV de aposta no próprio fechamento é tautologia (~ -vig).")


if __name__ == "__main__":
    main()
