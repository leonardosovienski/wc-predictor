"""CircuitBreaker unificado — une as DUAS implementações que o cripto carregava.

Antes existiam `dpl/circuit_breaker.py` (API `allow()`, telemetria obs, relógio
injetável, estados minúsculos) e `v3/circuit_breaker.py` (API `can_attempt()`,
`data_quality_score`, logging, estados maiúsculos) — mesma máquina de estados, duas
implementações divergentes. Esta é a superset que serve os dois consumidores:

  - `allow()` E `can_attempt()` (aliases): a chamada pode prosseguir? OPEN dentro do
    timeout → False; passado o timeout → transiciona a HALF_OPEN e libera a sonda.
  - `data_quality_score`: CLOSED=1.0, HALF_OPEN=0.5, OPEN=0.0 (propaga degradação).
  - `state`: getter PURO (não auto-transiciona na leitura) — a transição OPEN→HALF_OPEN
    acontece só em allow()/can_attempt(), não ao ler o estado.
  - relógio injetável (`clock`) para testes determinísticos; telemetria de transição
    via obs (domínio injetável — a camada é multi-domínio, não se hardcoda "cripto").

Estado em memória por instância (suficiente para ingestão single-process). Estado
compartilhado multi-instância fica como evolução futura.
"""
from __future__ import annotations

import time
from typing import Callable

from predictor_core.kernel.obs import emit_event

# Default NEUTRO: a camada é compartilhada. O dono do domínio injeta o seu via `domain=`
# — senão a telemetria de ações/futebol sairia atribuída ao cripto.
_DEFAULT_DOMAIN = "data"


class CircuitOpenError(Exception):
    """Circuito aberto e a chamada foi bloqueada (fail-fast)."""


class CircuitBreaker:
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(self, name: str, failure_threshold: int = 3,
                 reset_timeout: float = 60.0, *,
                 clock: Callable[[], float] = time.monotonic,
                 domain: str = _DEFAULT_DOMAIN) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self._clock = clock
        self._domain = domain
        self._state = self.CLOSED
        self._failures = 0
        self._opened_at = 0.0
        self._probe_released = False  # HALF_OPEN libera UMA sonda por vez

    # --- estado -------------------------------------------------------------

    @property
    def state(self) -> str:
        """Estado bruto — NÃO auto-transiciona (a transição vive em allow/can_attempt)."""
        return self._state

    @property
    def data_quality_score(self) -> float:
        """Propaga a degradação para o contrato de dados downstream."""
        if self._state == self.CLOSED:
            return 1.0
        if self._state == self.HALF_OPEN:
            return 0.5
        return 0.0

    # --- controle -----------------------------------------------------------

    def can_attempt(self) -> bool:
        """True se a chamada pode prosseguir agora. OPEN dentro do timeout → False;
        passado o timeout, transiciona a HALF_OPEN e libera UMA sonda — chamadas
        seguintes em HALF_OPEN retornam False até record_success/record_failure
        resolver a sonda em voo (senão N chamadas concorrentes bombardeariam a
        fonte convalescente de uma vez)."""
        if self._state == self.CLOSED:
            return True
        if self._state == self.OPEN:
            if (self._clock() - self._opened_at) >= self.reset_timeout:
                self._transition(self.HALF_OPEN)
                self._probe_released = True
                return True
            return False
        # HALF_OPEN: uma sonda por vez
        if self._probe_released:
            return False
        self._probe_released = True
        return True

    # Alias de compatibilidade com o consumidor da dpl (router).
    def allow(self) -> bool:
        return self.can_attempt()

    def record_success(self) -> None:
        self._failures = 0
        self._probe_released = False
        if self._state != self.CLOSED:
            self._transition(self.CLOSED)

    def record_failure(self) -> None:
        self._failures += 1
        self._probe_released = False
        # Falha durante a sonda (HALF_OPEN) OU ao atingir o limiar → abre.
        if self._state == self.HALF_OPEN or self._failures >= self.failure_threshold:
            self._opened_at = self._clock()
            self._transition(self.OPEN)

    def _transition(self, new_state: str) -> None:
        if new_state == self._state:
            return
        old = self._state
        self._state = new_state
        emit_event(self._domain, "circuit.transition",
                   metrics={"failures": self._failures},
                   metadata={"breaker": self.name, "from": old, "to": new_state})
