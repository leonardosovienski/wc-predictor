"""predictor-core.measurement.ordinal — camada ordinal (Plackett-Luce, choix-like).

Motivação (masterplan de agosto/2026): quando o resultado observado é um
RANQUEAMENTO de N itens (não um par, não uma classe única) — grid de largada e
chegada de F1, standings de LoL, ranking de ativos por retorno — o modelo
correto é Plackett-Luce: cada item `i` tem uma força latente `w_i > 0`, e a
probabilidade de uma ordem completa é o produto sequencial de
"escolher o 1º entre os restantes" via Luce's choice axiom. Este módulo estima
`w` a partir de rankings observados (MM algorithm de Hunter 2004 — a mesma
base do `choix.ilsr`) e expõe `rank_probabilities` para decompor uma corrida em
probabilidade por posição, consumível por `measurement.metrics.rps`.

Zero dependências externas. `EloEngine` (kernel.rating) modela força via
atualização incremental par-a-par; este módulo modela força via MLE batch sobre
um conjunto de rankings — pares distintos de ferramenta para o mesmo domínio
ordinal, intercambiáveis conforme o caso de uso do consumidor."""
from __future__ import annotations

import math

__all__ = ["plackett_luce_prob", "fit_plackett_luce", "rank_probabilities"]

# Piso das forças estimadas: o MLE de um item que NUNCA vence posição alguma
# diverge para 0 no limite, mas w=0 violaria o contrato w>0 que o próprio
# plackett_luce_prob exige (o fit produziria saída que o módulo rejeita).
_MIN_STRENGTH = 1e-12


def plackett_luce_prob(ranking: list, strengths: dict) -> float:
    """P(ranking) sob Plackett-Luce dado `strengths` = {item: w > 0}.

    `ranking`: lista de itens do melhor (índice 0) ao pior. Fórmula:
    Π_{k=0}^{N-1} w_{rank[k]} / Σ_{j>=k} w_{rank[j]} — a cada posição, a força
    do escolhido sobre a soma das forças ainda "na disputa"."""
    n = len(ranking)
    ws = [strengths[item] for item in ranking]
    if any(w <= 0 for w in ws):
        raise ValueError("strengths devem ser > 0 para todo item do ranking")
    prob = 1.0
    remaining = sum(ws)
    for k in range(n):
        prob *= ws[k] / remaining
        remaining -= ws[k]
    return prob


def fit_plackett_luce(rankings: list, *, items: list | None = None,
                      iterations: int = 200, tol: float = 1e-9) -> dict:
    """MLE das forças latentes via MM algorithm (Hunter 2004, "MM algorithms for
    generalized Bradley-Terry models") — o mesmo princípio do `choix.ilsr`/`choix.mm_pl`.

    `rankings`: lista de rankings completos (cada um: lista de itens, melhor→pior).
    `items`: universo de itens; default = união observada nos rankings.
    Retorna {item: w}, normalizado para média geométrica 1 (identificação —
    Plackett-Luce só define as forças a menos de um fator de escala comum).

    Ponto fixo MM: para cada item `i`,
      w_i <- (nº de vezes que i NÃO é o último entre os itens ainda na disputa
              quando i está presente)
             / Σ (1 / soma_de_forças_do_conjunto_remanescente em cada posição
                  onde i ainda está competindo, excluindo i mesmo do denominador
                  quando i já venceu aquela posição)
    Implementação direta por iteração sobre as posições de cada ranking."""
    universe = items if items is not None else sorted({it for r in rankings for it in r})
    if len(universe) < 2:
        raise ValueError("fit_plackett_luce exige >= 2 itens distintos")
    w = {it: 1.0 for it in universe}

    for _ in range(iterations):
        wins = {it: 0.0 for it in universe}
        denom = {it: 0.0 for it in universe}
        for ranking in rankings:
            ws = [w[it] for it in ranking]
            n = len(ranking)
            suffix_sum = [0.0] * (n + 1)
            for k in range(n - 1, -1, -1):
                suffix_sum[k] = suffix_sum[k + 1] + ws[k]
            for k in range(n - 1):  # último item de cada ranking não "vence" posição nenhuma
                item = ranking[k]
                wins[item] += 1.0
                for j in range(k, n):
                    denom[ranking[j]] += 1.0 / suffix_sum[k]
        new_w = {}
        for it in universe:
            new_w[it] = wins[it] / denom[it] if denom[it] > 0 else w[it]
        # normaliza para média geométrica 1 (evita drift de escala/overflow)
        logs = [math.log(v) for v in new_w.values() if v > 0]
        if logs:
            shift = math.exp(sum(logs) / len(logs))
            new_w = {k: v / shift for k, v in new_w.items()}
        # piso APÓS a normalização — garante o contrato w>0 mesmo p/ nunca-vencedor
        new_w = {k: max(v, _MIN_STRENGTH) for k, v in new_w.items()}
        delta = max(abs(new_w[it] - w[it]) for it in universe)
        w = new_w
        if delta < tol:
            break
    return w


def rank_probabilities(strengths: dict) -> dict:
    """P(cada item termina em 1º) sob Plackett-Luce — normalização direta de Luce.

    Não é a distribuição completa por posição (isso exigiria somar sobre todas
    as N! ordens restantes); é a probabilidade de vitória, a projeção mais usada
    (ex.: probabilidade de pole/campeão) e insumo direto para `rps` tratando
    "1º/2º/.../último" como classes ordinais via ranking esperado."""
    total = sum(strengths.values())
    if total <= 0:
        raise ValueError("strengths devem somar > 0")
    return {item: w / total for item, w in strengths.items()}
