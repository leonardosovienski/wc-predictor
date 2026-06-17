"""predictor-core.replay — anti-lookahead ESTRUTURAL ("feed, don't query").

Lição medida do LEAN (Common/Data/Slice.cs): o motor EMPURRA o corte de tempo atual
para o algoritmo; o futuro simplesmente não existe na memória do passo. Em vez de o
sinal consultar `df.loc[:hoje]` (onde o lookahead entra por um off-by-one), ele RECEBE
uma janela read-only do passado. Espiar o amanhã levanta LookaheadError — o lookahead
vira IMPOSSÍVEL, não "proibido por convenção".

É a primitiva que o backtest do stocks (M4) e do wc devem adotar: o handler de sinal
deixa de consultar a série inteira e passa a receber só o passado.
"""


class LookaheadError(Exception):
    """Tentativa de acessar dado posterior ao asof — o defeito capital, barrado."""


class PastView:
    """Janela read-only dos eventos 0..asof (inclusive). Acesso a índice futuro levanta
    LookaheadError; slices clampam ao passado (nunca vazam o futuro)."""
    __slots__ = ("_data", "_i")

    def __init__(self, data: tuple, i: int):
        self._data = data
        self._i = i

    @property
    def latest(self):
        """O evento do asof — o 'agora'."""
        return self._data[self._i]

    @property
    def asof_index(self) -> int:
        return self._i

    def __len__(self) -> int:
        return self._i + 1

    def __iter__(self):
        return iter(self._data[: self._i + 1])

    def __getitem__(self, key):
        if isinstance(key, slice):
            start, stop, step = key.indices(self._i + 1)   # .indices clampa ao passado
            return self._data[start:stop:step]
        idx = key + (self._i + 1) if key < 0 else key
        if not (0 <= idx <= self._i):
            raise LookaheadError(
                f"acesso ao índice {key} (asof={self._i}) — lookahead barrado")
        return self._data[idx]


def replay(events, handler) -> list:
    """Reexecuta `events` (ORDENADOS NO TEMPO) ponto-a-ponto. Para cada asof, entrega ao
    handler uma PastView só do passado (<= asof) — ele não tem como consultar asof+1.

        handler(past: PastView) -> decisão | None

    Inversão de controle do LEAN: o motor alimenta, o sinal não consulta. Decisões
    não-None viram o ledger retornado (na ordem temporal).
    """
    data = tuple(events)
    ledger = []
    for i in range(len(data)):
        decision = handler(PastView(data, i))
        if decision is not None:
            ledger.append(decision)
    return ledger
