"""ZONA 3 — Kernel Python Daemon (Persistent, Zero Cold Start).

Roda como processo residente via asyncio + redis.asyncio.
Hiperparâmetros são carregados UMA VEZ no boot e mantidos em RAM.
A grade bivariada NB é computada por função Numba @njit compilada no boot
(cache=True → compilação persiste entre restarts do processo).

Tempo esperado por invocação após boot: < 15ms.

Contratos:
  Entrada  : canal Redis  "system:invoke_kernel"       (JSON KernelInvokePayload)
  Saída    : chave Redis  "fair_odds:{match_id}"       (JSON FairOddsPayload, TTL 5s)
           + canal Redis  "fair_odds_ready:{match_id}" (notificação para o C#)

Inicialização:
    python -m src.kernel_daemon [--db data/matches.db] [--redis redis://localhost:6379]

Não acessa disco após o boot — toda I/O é via Redis.
"""
import argparse
import asyncio
import json
import logging
import math
import signal
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import db as _db
from src.ingest import ROOT as _ROOT, load_config

log = logging.getLogger("kernel_daemon")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)

# ---------------------------------------------------------------------------
# Compilação Numba da grade bivariada — zero imports scipy no hot path
# ---------------------------------------------------------------------------

try:
    from numba import njit

    @njit(cache=True)
    def _compute_grid_jit(lam_a: float, lam_b: float, alpha: float,
                           rho: float, max_goals: int) -> np.ndarray:
        """Grade bivariada NB + correção Dixon-Coles, compilada JIT.
        Sem scipy, sem imports externos — aritmética pura com math.lgamma."""
        G = max_goals + 1
        r = 1.0 / alpha if alpha > 1e-9 else 1e9

        p_a = r / (r + lam_a)
        p_b = r / (r + lam_b)

        pa = np.empty(G)
        pb = np.empty(G)
        log_pa = math.log(p_a)
        log_1mpa = math.log(1.0 - p_a)
        log_pb = math.log(p_b)
        log_1mpb = math.log(1.0 - p_b)
        lgamma_r = math.lgamma(r)

        for k in range(G):
            lk = float(k)
            lgk1 = math.lgamma(lk + 1.0)
            pa[k] = math.exp(math.lgamma(lk + r) - lgamma_r - lgk1
                             + r * log_pa + lk * log_1mpa)
            pb[k] = math.exp(math.lgamma(lk + r) - lgamma_r - lgk1
                             + r * log_pb + lk * log_1mpb)

        grid = np.empty((G, G))
        for i in range(G):
            for j in range(G):
                grid[i, j] = pa[i] * pb[j]

        # Dixon-Coles: quatro células de placar baixo
        v00 = 1.0 - lam_a * lam_b * rho
        v01 = 1.0 + lam_a * rho
        v10 = 1.0 + lam_b * rho
        v11 = 1.0 - rho
        grid[0, 0] *= v00 if v00 > 0.0 else 0.0
        grid[0, 1] *= v01 if v01 > 0.0 else 0.0
        grid[1, 0] *= v10 if v10 > 0.0 else 0.0
        grid[1, 1] *= v11 if v11 > 0.0 else 0.0

        total = 0.0
        for i in range(G):
            for j in range(G):
                if grid[i, j] < 0.0:
                    grid[i, j] = 0.0
                total += grid[i, j]
        if total > 0.0:
            for i in range(G):
                for j in range(G):
                    grid[i, j] /= total

        return grid

    _NUMBA_AVAILABLE = True
    log.info("[kernel] Numba disponível — grade será compilada JIT no boot.")

except ImportError:
    _NUMBA_AVAILABLE = False
    log.warning("[kernel] Numba NÃO disponível — usando NumPy puro (fallback adequado).")

    def _compute_grid_jit(lam_a, lam_b, alpha, rho, max_goals):  # type: ignore[misc]
        """Fallback NumPy quando Numba não está instalado."""
        from scipy.stats import nbinom
        G = max_goals + 1
        k = np.arange(G)
        r = 1.0 / max(alpha, 1e-9)
        pa = nbinom.pmf(k, r, r / (r + lam_a))
        pb = nbinom.pmf(k, r, r / (r + lam_b))
        grid = np.outer(pa, pb)
        grid[0, 0] *= max(0.0, 1.0 - lam_a * lam_b * rho)
        grid[0, 1] *= max(0.0, 1.0 + lam_a * rho)
        grid[1, 0] *= max(0.0, 1.0 + lam_b * rho)
        grid[1, 1] *= max(0.0, 1.0 - rho)
        grid = np.clip(grid, 0.0, None)
        s = grid.sum()
        return grid / s if s > 0 else grid


def _fair_odds_from_grid(grid: np.ndarray) -> dict:
    """Extrai fair odds (preço justo = 1/p) da grade bivariada. Vetorizado."""
    G = grid.shape[0]
    k = np.arange(G)
    totals = k[:, None] + k[None, :]

    p_home  = float(np.tril(grid, -1).sum())
    p_draw  = float(np.trace(grid))
    p_away  = float(np.triu(grid, 1).sum())
    p_over  = float(grid[totals > 2.5].sum())
    p_under = 1.0 - p_over

    def safe_odd(p): return round(1.0 / p, 4) if p > 1e-6 else None

    return {
        "1":   safe_odd(p_home),
        "X":   safe_odd(p_draw),
        "2":   safe_odd(p_away),
        "o25": safe_odd(p_over),
        "u25": safe_odd(p_under),
    }


# ---------------------------------------------------------------------------
# Warm-up JIT (executa no boot para compilar o cache Numba)
# ---------------------------------------------------------------------------

def _warmup_jit(params: tuple) -> float:
    """Compila a grade JIT uma vez. Retorna o tempo em ms."""
    a, b, alpha, rho, theta, max_goals = params
    lam_a, lam_b = math.exp(a), math.exp(a)
    t0 = time.perf_counter()
    _compute_grid_jit(lam_a, lam_b, alpha, abs(rho), max_goals)
    # segunda chamada: usa o cache compilado — esta é a latência real
    _compute_grid_jit(lam_a, lam_b, alpha, abs(rho), max_goals)
    elapsed = (time.perf_counter() - t0) * 1000
    log.info("[kernel] JIT warm-up concluído em %.2f ms (2 invocações)", elapsed)
    return elapsed


# ---------------------------------------------------------------------------
# Carregamento de hiperparâmetros (uma vez no boot)
# ---------------------------------------------------------------------------

def _load_params(db_path: str) -> tuple:
    """Carrega (a, b, alpha, rho, theta, max_goals) do banco. Nunca mais acessa disco."""
    conn = _db.connect(db_path, read_only=True)
    prow = _db.load_params(conn)
    if not prow:
        raise RuntimeError("cache vazio — rode cron_update_models primeiro")
    cfg = load_config()
    theta     = float(cfg.get("model", {}).get("vorp_theta", 0.0))
    max_goals = int(cfg.get("model", {}).get("max_goals", 12))
    log.info("[kernel] params carregados: a=%.4f b=%.4f alpha=%.4f rho=%.4f theta=%.4f",
             prow[0], prow[1], prow[2], prow[3], theta)
    return (float(prow[0]), float(prow[1]), float(prow[2]),
            float(prow[3]), theta, max_goals)


# ---------------------------------------------------------------------------
# Handler de invocação (hot path)
# ---------------------------------------------------------------------------

async def _handle_invoke(client, payload_bytes: bytes, params: tuple) -> None:
    """Processa uma mensagem de kernel_invoke. Custo: < 15ms após warm-up."""
    t_recv = time.perf_counter()
    try:
        msg = json.loads(payload_bytes)
    except json.JSONDecodeError:
        log.error("[kernel] payload inválido: %s", payload_bytes[:120])
        return

    match_id    = str(msg.get("match_id", ""))
    elo_a       = float(msg.get("elo_a", 1500))
    elo_b       = float(msg.get("elo_b", 1500))
    dvorp_a     = float(msg.get("dvorp_a", 0.0))
    dvorp_b     = float(msg.get("dvorp_b", 0.0))
    t3_source   = int(msg.get("timestamp_t3", 0))

    a, b, alpha, rho, theta, max_goals = params

    # Link function com perturbação VORP
    diff  = (elo_a - elo_b) / 400.0
    lam_a = math.exp(a + b * diff  + theta * dvorp_a)
    lam_b = math.exp(a - b * diff  + theta * dvorp_b)

    # Grade bivariada JIT (< 15ms após compilação)
    grid = _compute_grid_jit(lam_a, lam_b, alpha, rho, max_goals)
    fair = _fair_odds_from_grid(grid)

    t_compute = time.perf_counter()

    # SETEX TTL=5s: janela de oportunidade
    key     = f"fair_odds:{match_id}"
    payload = json.dumps(fair)
    await client.setex(key, 5, payload)

    # Notificação para o MarketStateEngine C# (não usa keyspace — mais simples e portável)
    notify_channel = f"fair_odds_ready:{match_id}"
    await client.publish(notify_channel, payload)

    t_write = time.perf_counter()

    elapsed_ms = (t_write - t_recv) * 1000
    network_lag_ms = (t_recv * 1000) - t3_source if t3_source else 0
    log.info(
        "[kernel] %s -> lambda=(%.3f,%.3f) compute=%.2fms write=%.2fms total=%.2fms odds=%s",
        match_id, lam_a, lam_b,
        (t_compute - t_recv) * 1000,
        (t_write - t_compute) * 1000,
        elapsed_ms, payload)

    if elapsed_ms > 15:
        log.warning("[kernel] LATÊNCIA ACIMA DE 15ms: %.2fms — investigar JIT ou GC.", elapsed_ms)


# ---------------------------------------------------------------------------
# Daemon principal
# ---------------------------------------------------------------------------

async def _run_daemon(db_path: str, redis_url: str) -> None:
    import redis.asyncio as aioredis

    # Boot: carrega params uma vez
    params = _load_params(db_path)

    # Warm-up JIT (compilação Numba — lenta na primeira vez, O(ms) depois)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _warmup_jit, params)

    # Conexão Redis (hiredis parser para throughput máximo)
    client = aioredis.from_url(redis_url, decode_responses=False)
    pubsub = client.pubsub()
    await pubsub.subscribe("system:invoke_kernel")

    log.info("[kernel] DAEMON PRONTO. Escutando system:invoke_kernel em %s", redis_url)

    # Graceful shutdown via SIGTERM/SIGINT
    stop = asyncio.Event()
    loop.add_signal_handler(signal.SIGTERM, stop.set)
    loop.add_signal_handler(signal.SIGINT,  stop.set)

    async def _listen():
        async for message in pubsub.listen():
            if stop.is_set():
                break
            if message["type"] != "message":
                continue
            # Fire-and-forget com isolamento de erro por invocação
            asyncio.create_task(_handle_invoke(client, message["data"], params))

    await asyncio.gather(_listen(), stop.wait())
    await pubsub.unsubscribe("system:invoke_kernel")
    await client.aclose()
    log.info("[kernel] daemon encerrado com sucesso.")


def main():
    parser = argparse.ArgumentParser(description="Kernel Python Daemon — Zona 3")
    parser.add_argument("--db",    default="data/matches.db")
    parser.add_argument("--redis", default="redis://localhost:6379")
    args = parser.parse_args()

    try:
        import redis.asyncio  # noqa: F401
    except ImportError:
        sys.exit("[kernel] redis[hiredis] não instalado. "
                 "Execute: pip install -r requirements-kernel.txt")

    asyncio.run(_run_daemon(str(_ROOT / args.db), args.redis))


if __name__ == "__main__":
    main()
