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
        if idx < 0:
            # negativo além do início: passado INEXISTENTE, não lookahead —
            # IndexError preserva o diagnóstico (LookaheadError é só p/ futuro).
            raise IndexError(
                f"índice {key} fora do range do passado (len={self._i + 1})")
        if idx > self._i:
            raise LookaheadError(
                f"acesso ao índice {key} (asof={self._i}) — lookahead barrado")
        return self._data[idx]


def replay(events, handler, *, key=None) -> list:
    """Reexecuta `events` (ORDENADOS NO TEMPO) ponto-a-ponto. Para cada asof, entrega ao
    handler uma PastView só do passado (<= asof) — ele não tem como consultar asof+1.

        handler(past: PastView) -> decisão | None

    Inversão de controle do LEAN: o motor alimenta, o sinal não consulta. Decisões
    não-None viram o ledger retornado (na ordem temporal).

    `key`: callable(evento) -> timestamp comparável. Se fornecido, a ordem temporal
    é VERIFICADA (não assumida): eventos fora de ordem levantam ValueError em vez de
    corromper a semântica de asof silenciosamente — ordem quebrada é leakage temporal.

    CONTRATO DE IMUTABILIDADE: a PastView devolve REFERÊNCIAS aos eventos originais
    (não cópias). O handler NÃO pode mutar `past.latest` nem itens fatiados — mutar um
    evento contamina todos os passos futuros (leakage por objeto compartilhado). Passe
    eventos imutáveis (tuplas/namedtuples/frozen) para que a regra seja estrutural.
    """
    data = tuple(events)
    if key is not None and len(data) > 1:
        ts = [key(e) for e in data]
        bad = next((i for i in range(1, len(ts)) if ts[i] < ts[i - 1]), None)
        if bad is not None:
            raise ValueError(
                f"replay: eventos não monotônicos no tempo (índice {bad}: "
                f"{ts[bad]!r} < {ts[bad - 1]!r}) — ordem quebrada é leakage temporal")
    ledger = []
    for i in range(len(data)):
        decision = handler(PastView(data, i))
        if decision is not None:
            ledger.append(decision)
    return ledger
