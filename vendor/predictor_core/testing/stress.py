"""predictor-core.testing.stress — telemetria de estresse (Hypothesis-like, stdlib puro).

Motivação (masterplan de agosto/2026): as réguas do core (`measurement.stats`,
`measurement.metrics`, `measurement.ordinal`, `kernel.rating`) são testadas hoje
com exemplos fixos — cobrem o caso feliz mas não o caso extremo que ninguém
pensou em escrever (série de 1 ponto, todas as probabilidades no mesmo bin,
rating negativo). O padrão "property-based testing" do Hypothesis resolve isso
gerando entradas ALEATÓRIAS dentro de uma estratégia e verificando uma
PROPRIEDADE (não um valor fixo) — mas o core é stdlib-first (zero dependências
além de httpx/pydantic), então este módulo reimplementa o subconjunto mínimo:
estratégias (`floats`, `integers`, `lists_of`) + runner (`check_property`) que
amostra `trials` vezes com `random.Random(seed)` e relata o PRIMEIRO
contraexemplo (sem shrinking sofisticado — o objetivo é achar a falha, não
minimizá-la ao byte)."""
from __future__ import annotations

import random

__all__ = ["floats", "integers", "lists_of", "PropertyFailure", "check_property"]


class PropertyFailure(AssertionError):
    """Uma amostra gerada violou a propriedade — carrega os args que reproduzem.

    A amostra fica em `failing_args` (NÃO em `args`: esse nome é o atributo
    especial de BaseException que carrega a mensagem — sobrescrevê-lo apagaria
    o diagnóstico do str(exc))."""

    def __init__(self, message: str, failing_args: tuple, seed: int):
        super().__init__(message)
        self.failing_args = failing_args
        self.seed = seed


def floats(lo: float = -1e6, hi: float = 1e6, *, allow_nan: bool = False):
    """Estratégia: float uniforme em [lo, hi]. `rng` é injetado por `check_property`."""
    def draw(rng: random.Random):
        return rng.uniform(lo, hi)
    return draw


def integers(lo: int = -1000, hi: int = 1000):
    def draw(rng: random.Random):
        return rng.randint(lo, hi)
    return draw


def lists_of(element_strategy, *, min_size: int = 0, max_size: int = 20):
    """Estratégia: lista de tamanho aleatório em [min_size, max_size], cada
    elemento amostrado por `element_strategy`."""
    def draw(rng: random.Random):
        n = rng.randint(min_size, max_size)
        return [element_strategy(rng) for _ in range(n)]
    return draw


def check_property(property_fn, *strategies, trials: int = 100, seed: int = 0) -> int:
    """Amostra `trials` tuplas de entrada (uma por estratégia posicional) e chama
    `property_fn(*sample)`. `property_fn` deve levantar (ou retornar False, que é
    convertido em AssertionError) se a amostra violar a propriedade esperada —
    exceções esperadas do próprio contrato (ex.: ValueError de guard de invariante)
    devem ser tratadas DENTRO de `property_fn` (try/except) já que aqui contam
    como falha do teste de estresse.

    Determinístico: mesma `seed` produz a mesma sequência de amostras — uma
    falha é reproduzível chamando `property_fn(*exc.failing_args)` no `PropertyFailure`.
    Retorna o nº de trials executados com sucesso (== `trials` se nenhuma
    falha for encontrada)."""
    rng = random.Random(seed)
    for i in range(trials):
        sample = tuple(strategy(rng) for strategy in strategies)
        try:
            result = property_fn(*sample)
        except Exception as exc:
            raise PropertyFailure(
                f"trial {i}/{trials}: {property_fn.__name__} levantou "
                f"{type(exc).__name__}: {exc} para args={sample!r}",
                failing_args=sample, seed=seed) from exc
        if result is False:
            raise PropertyFailure(
                f"trial {i}/{trials}: {property_fn.__name__} retornou False "
                f"para args={sample!r}", failing_args=sample, seed=seed)
    return trials
