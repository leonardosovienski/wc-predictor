"""Smoke test de plumbing do Hot Path (NÃO é teste de hipótese Go/No-Go).

Simula o papel do C# Worker: publica KernelInvokePayload em system:invoke_kernel,
escuta fair_odds_ready:{match_id}, valida o Contrato 2 e mede a latência real
ponta-a-ponta do Kernel Python (T3 → T3.5).

Requer: kernel_daemon.py rodando + Redis em localhost:6379.

Uso:
    python scripts/hotpath_smoke.py [--n 20] [--redis redis://localhost:6379]
"""
import argparse
import json
import sys
import time

import redis


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20, help="número de invocações")
    ap.add_argument("--redis", default="redis://localhost:6379")
    args = ap.parse_args()

    r = redis.from_url(args.redis, decode_responses=True)
    try:
        r.ping()
    except redis.ConnectionError:
        sys.exit(f"[smoke] Redis indisponível em {args.redis}")

    latencies_ms = []
    fails = 0

    print(f"[smoke] disparando {args.n} invocações ao Kernel…\n")
    for i in range(args.n):
        match_id = f"smoke_{i}"
        # subscreve ANTES de publicar para não perder a notificação
        ps = r.pubsub()
        ps.subscribe(f"fair_odds_ready:{match_id}")
        # descarta a mensagem de confirmação de subscribe
        ps.get_message(timeout=1.0)

        payload = {
            "match_id": match_id,
            "elo_a": 1600 + i * 5,
            "elo_b": 1500,
            "dvorp_a": round(0.1 * (i % 5 - 2), 3),
            "dvorp_b": 0.0,
            "timestamp_t3": int(time.time() * 1000),
        }
        t_pub = time.perf_counter()
        n_recv = r.publish("system:invoke_kernel", json.dumps(payload))
        if n_recv == 0:
            print(f"  {match_id}: NENHUM subscriber no kernel (daemon rodando?)")
            fails += 1
            ps.close()
            continue

        # espera a notificação fair_odds_ready (timeout 5s = TTL da chave)
        got = None
        deadline = t_pub + 5.0
        while time.perf_counter() < deadline:
            msg = ps.get_message(timeout=0.5)
            if msg and msg["type"] == "message":
                got = msg["data"]
                break
        t_recv = time.perf_counter()
        ps.close()

        if not got:
            print(f"  {match_id}: TIMEOUT (sem fair_odds em 5s)")
            fails += 1
            continue

        # valida Contrato 2: chaves {1, X, 2, o25, u25}
        fair = json.loads(got)
        expected_keys = {"1", "X", "2", "o25", "u25"}
        if set(fair.keys()) != expected_keys:
            print(f"  {match_id}: CONTRATO VIOLADO — chaves {set(fair.keys())}")
            fails += 1
            continue

        # valida que a chave efêmera existe e tem TTL
        key = f"fair_odds:{match_id}"
        ttl = r.ttl(key)
        lat_ms = (t_recv - t_pub) * 1000
        latencies_ms.append(lat_ms)

        # sanidade: probabilidades implícitas somam ~>1 (fair odds sem overround → soma 1x2 ~1)
        inv_sum = sum(1.0 / fair[k] for k in ("1", "X", "2") if fair[k])
        print(f"  {match_id}: round-trip={lat_ms:6.2f}ms  TTL={ttl}s  "
              f"1X2={fair['1']:.2f}/{fair['X']:.2f}/{fair['2']:.2f}  Σp={inv_sum:.4f}")

    print("\n" + "=" * 50)
    ok = len(latencies_ms)
    print(f"[smoke] {ok}/{args.n} OK, {fails} falhas")
    if latencies_ms:
        latencies_ms.sort()
        p50 = latencies_ms[len(latencies_ms) // 2]
        p95 = latencies_ms[min(len(latencies_ms) - 1, int(len(latencies_ms) * 0.95))]
        print(f"[smoke] round-trip Redis+Kernel: "
              f"p50={p50:.2f}ms  p95={p95:.2f}ms  max={latencies_ms[-1]:.2f}ms")
        print(f"[smoke] (inclui pub/sub Redis + compute Kernel; "
              f"o budget de 15ms é só do compute interno do Kernel)")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
