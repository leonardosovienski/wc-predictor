# Por que o modelo aposta tanta zebra — diagnóstico

> Investigação feita em 2026-06-27 sobre o backtest da Copa 2026 (49 apostas,
> +44% ROI vindo de 2 zebras de odd alta). Pergunta: o modelo tem viés que o
> faz apostar azarão/empate demais? Resposta com dados abaixo.

## TL;DR

O viés **não é empate** (a P(empate) do modelo está calibrada: 24,1% previsto
vs 26,8% real). O viés é **compressão do Elo**: o modelo dá o favorito como
fraco demais (~54% de vitória), quando na Copa 2026 o favorito venceu ~88% dos
jogos decididos. Essa força que falta no favorito vira **probabilidade inflada
do azarão** (~22% no modelo vs ~9% real → **+13 pts de viés pró-zebra**). Como
o mercado precifica o favorito corretamente, a prob inflada do azarão no modelo
aparece como "valor" — e o gatilho `P_model > 1/odd` dispara a aposta na zebra.

## Os números (56 jogos disputados da Copa 2026)

| Métrica | Modelo | Realidade |
|---|---|---|
| P(empate) média | 24,1 % | 26,8 % (calibrado) |
| P(favorito vencer) média | **53,9 %** | favorito venceu **87,8 %** dos decididos |
| P(azarão vencer) implícita | ~22 % | ~9 % (**superestima ~13 pts**) |

Spread do Elo (262 seleções): média 1498, **desvio só 122 pts**, amplitude
top–bottom 679. Parâmetros do motor: `b=1.059`, `rho=-0.0373`, `alpha=0.155`.

Calibração do empate por faixa (sanidade — empate NÃO é o problema):

| Faixa do modelo | n | previu | real |
|---|---|---|---|
| 0–22 % | 15 | 19,6 % | 20,0 % |
| 22–26 % | 20 | 24,2 % | 15,0 % |
| 26–30 % | 21 | 27,1 % | 42,9 % |

## Mecânica da causa

```
Elo comprimido (Δelo pequeno)
        │
        ▼
λ_a = exp(a + b·Δelo/400)  ≈  λ_b = exp(a − b·Δelo/400)     ← λ colados
        │
        ▼
grid de placares quase simétrica → P(favorito) baixa, P(azarão) alta
        │
        ▼
mercado (eficiente) precifica o favorito alto; modelo discorda
        │
        ▼
P_model(azarão) > 1/odd(azarão) → gatilho de valor dispara → APOSTA ZEBRA
        │
        ▼
favorito vence ~88% → a aposta na zebra perde na maioria
```

A compressão tem dois suspeitos, ambos já citados no README/HANDOFF:
1. **Inflação continental** — seleções CAF/AFC acumulam pontos contra adversários
   fracos; o Elo não pondera força do oponente. Infla o rating dos médios e
   achata a distância pro topo.
2. **`b` baixo** — a sensibilidade gol↔Elo (`b≈1.06`) sai da MLE sobre o
   histórico de gols; se o futebol recente teve placares apertados, `b` encolhe
   e comprime ainda mais os λ.

## Por que NÃO vamos "consertar" agora (e o que seria legítimo)

⚠️ **Ajustar `b` ou de-comprimir o Elo olhando estes 56 jogos é overfitting** —
fitar o motor à amostra que já vimos. Três razões para NÃO hot-fixar no meio da
Copa:

1. **Amostra pequena.** O gap favorito (54% modelo vs 64% real não-condicional)
   é ~1,5 desvio em 56 jogos — direção real, magnitude incerta. Pode ser parte
   "Copa chalk" (favoritos em dia) e parte viés estrutural.
2. **Disciplina pré-registrada.** O README já fixou a correção de inflação
   continental (prior FIFA como regularização DENTRO da MLE) como hipótese
   **pré-registrada para a v2.0**, com critério de decisão por CLV — justamente
   para a avaliação em julho ser confirmatória, não post-hoc.
3. **Regra de promoção do projeto.** "Qualquer mudança no motor só vai pra main
   se mover o P&L na mesma amostra" — e mover o P&L na mesma amostra é a
   definição de se enganar. O juiz honesto é o **CLV out-of-sample**, que só
   nasce do cron coletando abertura pré-apito.

### Correção legítima (v2.0, fora do torneio)
- **Prior FIFA como regularização na MLE do Elo** (já pré-registrada) — puxa os
  ratings inflados de volta sem injetar o mercado.
- **Recalibrar `b` com walk-forward** e validar por CLV, não por ROI in-sample.
- **Encolher a prob do azarão** (shrinkage explícito) só se sobreviver a
  validação out-of-sample em vários torneios (Euro, Copa América).

## Experimento: `b` sozinho não conserta (prova que é compressão do Elo)

Varredura do `b` sobre os mesmos 56 jogos (alvo real: favorito 64,3%, empate
26,8%, azarão 8,9%):

| b | P(fav) | P(empate) | P(azarão) |
|---|---|---|---|
| **1,059** (atual) | 53,9 % | 24,1 % | 22,1 % |
| 1,300 | 57,6 % | 22,7 % | 19,7 % |
| 1,500 | 60,5 % | 21,5 % | 18,0 % |
| **1,800** | 64,5 % | 19,7 % | 15,8 % |
| 2,100 | 67,9 % | 18,0 % | 14,1 % |
| **alvo real** | **64,3 %** | **26,8 %** | **8,9 %** |

Leitura: para alinhar o **favorito** (64%) seria preciso quase **dobrar `b`**
(1,06 → 1,8). Mas mesmo aí o **azarão continua superestimado** (15,8% vs 8,9%
real) e o **empate despenca** abaixo do real (19,7% vs 26,8%). Ou seja, mexer só
no `b` rouba massa do lugar errado — **a doença não é o `b`, é o Elo comprimido**
(as distâncias de rating não refletem as distâncias reais de força). Confirma
que o fix certo é **de-comprimir o Elo** (prior FIFA na MLE), não cranguear `b`.

## Como reproduzir
`python scripts/diag_zebra.py` (cache atual + jogos disputados da Copa 2026). É
medida de **tendência do output**, não backtest sem-lookahead — suficiente para
expor o viés e dimensioná-lo, insuficiente para calibrar a correção (que precisa
de validação out-of-sample por CLV).
