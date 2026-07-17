"""predictor-core.kernel.jsonl_store — armazenamento JSONL iterável (Onda 1 da v1.3.0).

O padrão "um JSON por linha, append-only" já existia em dois lugares do
ecossistema (telemetria do obs, logs de eventos dos consumidores) sem uma
abstração comum. `JsonlStore` é o contrato mínimo: `append(record)` (escrita
atômica por linha, flush imediato), `__iter__` (leitura streaming — nunca
carrega o arquivo inteiro), `count()` e `tail(n)`.

Não é banco: sem índice, sem update, sem delete — coerente com a filosofia do
Ledger (correção é registro novo). Quem precisa de query estruturada usa o
SQLite do consumidor; isto é a camada de EVENTOS."""
from __future__ import annotations

import json
from pathlib import Path

__all__ = ["JsonlStore"]


class JsonlStore:
    """Arquivo JSONL append-only com leitura streaming.

    store = JsonlStore("events.jsonl")
    store.append({"kind": "bet", "stake": 10})
    for rec in store: ...
    """

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def append(self, record: dict) -> None:
        """Grava `record` como uma linha JSON (compacta, ensure_ascii=False).
        Cria diretórios. `record` precisa ser JSON-serializável — falha ANTES
        de abrir o arquivo (nunca deixa linha truncada para trás)."""
        # allow_nan=False: NaN/inf virariam literais fora do RFC 8259 — a linha
        # seria ilegível para parsers estritos (corrupção explícita > silenciosa).
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"),
                          allow_nan=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def __iter__(self):
        """Itera os registros em ordem de escrita, streaming (linha a linha).
        Arquivo inexistente = iterador vazio. Linha corrompida (JSON inválido)
        levanta ValueError com o número da linha — corrupção silenciosa é pior
        que falha explícita."""
        if not self.path.exists():
            return
        with open(self.path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except ValueError as exc:
                    raise ValueError(
                        f"{self.path}:{i}: linha JSONL corrompida — {exc}") from exc

    def count(self) -> int:
        return sum(1 for _ in self)

    def tail(self, n: int) -> list:
        """Últimos `n` registros (lê tudo — para arquivos de telemetria, ok;
        para logs gigantes o consumidor rotaciona antes)."""
        records = list(self)
        return records[-n:] if n > 0 else []
