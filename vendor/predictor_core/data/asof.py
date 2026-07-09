"""asof — reconstrução forward-only de estado ("o que eu sabia em t").

Generaliza o `ratings_asof` do wc-predictor (Elo pré-jogo sem lookahead) para qualquer
domínio: dado um fluxo de eventos ordenado no tempo e um `reducer`, devolve o estado
agregado visto ANTES de cada data de consulta. O padrão existe em três domínios (Elo da
Copa, z-scores do cripto, universo point-in-time do stocks) e cada um o resolveu ad-hoc.

Anti-lookahead ESTRUTURAL: para cada data, o reducer só recebe eventos anteriores a ela
— o futuro não entra na memória do passo (mesma filosofia do replay, para snapshots em
datas específicas em vez de passo-a-passo).
"""
from __future__ import annotations


def _ts(event, key):
    return key(event) if key is not None else event[0]


def state_asof(events, reducer, dates, *, key=None, window=None,
               inclusive: bool = False) -> dict:
    """Para cada data em `dates`, aplica `reducer` aos eventos ANTERIORES a ela.

        reducer(prefixo_de_eventos) -> estado

    Retorna {data: estado}. Forward-only: o prefixo de cada data contém apenas eventos
    com timestamp < data (ou <= se `inclusive=True`).

    key      : callable(evento) -> timestamp comparável (default: evento[0]).
    window   : se dado, só entram eventos com ts >= (data - window) — janela relativa
               (ex.: Elo dos últimos 6 anos). Exige que `data - window` seja válido
               (datetime-timedelta, número-número, etc.).
    inclusive: False (default) = ts < data (anti-lookahead pré-decisão, como o
               ratings_asof); True = ts <= data.

    Custo O(D·N) — adequado a pesquisa (D = dezenas de datas). Para D grande, ordene os
    eventos e faça busca binária no chamador."""
    evs = list(events)
    out = {}
    for d in sorted(set(dates)):
        if inclusive:
            prefix = [e for e in evs if _ts(e, key) <= d]
        else:
            prefix = [e for e in evs if _ts(e, key) < d]
        if window is not None:
            cut = d - window
            prefix = [e for e in prefix if _ts(e, key) >= cut]
        out[d] = reducer(prefix)
    return out
