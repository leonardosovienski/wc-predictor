"""predictor-core.obs — observabilidade: logging estruturado + telemetria JSONL.

Sem Kubernetes/dashboard gerenciado, a saúde da plataforma é reconstruível lendo os
eventos estruturados que cada domínio emite. `emit_event` crava um ENVELOPE RÍGIDO de
7 chaves obrigatórias (timestamp, domain, run_id, event, code_version, metrics,
metadata) — invariante por máquina, não por disciplina.
"""
import json
import logging
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def setup_logging(level: str = "INFO", fmt: str | None = None) -> None:
    fmt = fmt or "%(asctime)s %(levelname)-8s %(name)s — %(message)s"
    logging.basicConfig(stream=sys.stdout, level=getattr(logging, level.upper()),
                        format=fmt, datefmt="%Y-%m-%dT%H:%M:%S")


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


# --- Telemetria JSONL: o sistema nervoso da plataforma ----------------------

EVENTS_ENV = "PREDICTOR_EVENTS_PATH"
_DEFAULT_EVENTS = "events.jsonl"

# As 7 chaves obrigatórias do envelope, em ordem canônica.
ENVELOPE_KEYS = ("timestamp", "domain", "run_id", "event",
                 "code_version", "metrics", "metadata")


def emit_event(domain: str, event: str, *, run_id: str | None = None,
               code_version: str | None = None, metrics: dict | None = None,
               metadata: dict | None = None, path=None, timestamp: str | None = None) -> dict:
    """Emite UM evento estruturado como uma linha JSONL (append-only).

    Envelope RÍGIDO — sempre as 7 chaves: timestamp, domain, run_id, event,
    code_version, metrics, metadata.
      - metrics  = payload NUMÉRICO flexível ({"psr": 0.96, "bootstrap_ic_lower": 0.02})
      - metadata = payload de CONTEXTO flexível ({"status": "ok", "rows": 150})
    run_id/code_version podem ser None, mas a CHAVE existe sempre (envelope fixo).
    `timestamp`/`path` injetáveis para teste; destino default = $PREDICTOR_EVENTS_PATH
    ou ./events.jsonl. Retorna o dict emitido.
    """
    if not domain or not isinstance(domain, str):
        raise ValueError("emit_event: 'domain' obrigatório (string não-vazia)")
    if not event or not isinstance(event, str):
        raise ValueError("emit_event: 'event' obrigatório (string não-vazia)")
    metrics = metrics or {}
    metadata = metadata or {}
    nao_numericos = [k for k, v in metrics.items() if not isinstance(v, (int, float))]
    if nao_numericos:
        raise TypeError(f"emit_event: 'metrics' aceita só números; não-numéricos: "
                        f"{nao_numericos} — use 'metadata' para contexto não-numérico")
    # NaN/inf não existem em JSON (RFC 8259): json.dumps os emitiria como literais
    # que parsers estritos rejeitam — a linha inteira da telemetria viraria lixo.
    nao_finitos = [k for k, v in metrics.items()
                   if isinstance(v, float) and not math.isfinite(v)]
    if nao_finitos:
        raise ValueError(f"emit_event: 'metrics' com valor não-finito (NaN/inf): "
                         f"{nao_finitos} — JSON não representa NaN/inf; trate antes de emitir")
    record = {
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "domain": domain,
        "run_id": run_id,
        "event": event,
        "code_version": code_version,
        "metrics": metrics,
        "metadata": metadata,
    }
    # allow_nan=False: backstop p/ NaN escondido no metadata (dict livre).
    # Serializa ANTES de abrir: falha de serialização não pode criar/tocar o arquivo.
    line = json.dumps(record, ensure_ascii=False, allow_nan=False)
    target = Path(path or os.getenv(EVENTS_ENV) or _DEFAULT_EVENTS)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    return record


def read_events(path) -> list[dict]:
    """Lê um JSONL de eventos (base do futuro painel). Linhas vazias ignoradas."""
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
