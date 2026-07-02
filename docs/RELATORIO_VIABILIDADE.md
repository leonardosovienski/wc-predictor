# Relatório de viabilidade — o modelo wc-predictor tem edge de aposta?

> **CONFIRMADO em 2026-06-28:** o veredito deste relatório ("sem edge") foi
> reconfirmado com a régua VÁLIDA — o open-CLV (220 apostas, abertura real via
> `initialFractionalValue`). 1X2 −15% CLV (sig); o "+18% em OU 2.5" era variância
> de teste múltiplo (diluiu no pool). Ver VEREDITO no topo do [`HANDOFF.md`](../HANDOFF.md).

> Investigação aprofundada, 2026-06-27. Pergunta central: depois de consertar a
> coleta e rodar o backtest da Copa 2026 (+44% ROI), o modelo realmente prevê
> melhor que o acaso e melhor que o mercado — ou o número bonito foi sorte?
> Método: avaliação **walk-forward sem lookahead** de 44 jogos disputados.

---

## Sumário executivo (o veredito)

**O modelo tem skill ABSOLUTO fraco, mas NÃO tem edge de aposta.** Em ordem:

1. ✅ **Bate o acaso** — Brier 0,589 vs 0,667 do chute aleatório. Sabe algo.
2. ❌ **Perde feio pro mercado** — Brier 0,570 vs **0,485** do mercado; acerto de
   palpite **50% vs 68,6%**. O mercado prevê muito melhor.
3. ❌ **As apostas de "valor" são os erros do modelo.** Quando o modelo discorda
   do mercado (= onde nasce a aposta de valor), ele acerta **8%**; o mercado,
   **58%**. Apostar a discordância é apostar contra quem está certo.
4. ⚠️ **O +44% foi sorte** — 2 zebras de odd alta (Spain–Cabo Verde 0-0 @15,
   Ecuador–Curaçao 0-0 @9) = +22u dos +21,58u líquidos. Tira as duas → ~0. O
   bootstrap já mostrava todo IC cruzando o zero.

**Conclusão (escopo restrito — ver §Limitações):** no **1X2 de fechamento da
Copa**, com N=44, não há evidência de edge — e há evidência consistente do
contrário. Isto **não** prova ausência de valor em outros mercados (ligas de
clubes com N alto, odds de abertura, O/U) — esses não foram testados aqui. Como
**ferramenta de previsão** o modelo é decente e interpretável.

---

## Metodologia (e por que ela corrige o diagnóstico anterior)

O diagnóstico rápido de mais cedo usou o **cache atual** do Elo — que já foi
calculado COM os resultados da Copa dentro (lookahead). Isso inflou
artificialmente a aparência de skill. Este relatório refaz tudo **walk-forward**:

- Elo reconstruído jogo a jogo na ordem cronológica; cada previsão usa só o
  rating **pré-jogo** (idêntico ao `src.backtest`, sem vazamento).
- Parâmetros de gol (a,b,α,ρ) **frozen**, calibrados só com jogos ANTES da Copa.
- 44 jogos da Copa 2026 avaliados; 35 com odds para comparar contra o mercado.

A diferença lookahead vs honesto é gritante e educativa:

| Definição de "favorito vence" | Resultado |
|---|---|
| Cache com lookahead (diagnóstico rápido) | 64% |
| **Walk-forward honesto (este relatório)** | **50% (cara ou coroa)** |

O Elo pré-jogo do projeto acerta o vencedor como **cara ou coroa**. O mercado, 69%.

---

## Achado 1 — skill absoluto: bate o acaso (mas pouco)

Brier score (0 = perfeito, 0,667 = chute 1/3-1/3-1/3):

| Preditor | Brier | Logloss |
|---|---|---|
| **Modelo** | 0,589 | 0,981 |
| Acaso | 0,667 | — |

O modelo carrega informação real — não é ruído puro. Mas a margem sobre o acaso
é modesta.

## Achado 2 — o juiz: modelo vs mercado (os mesmos 35 jogos)

| Métrica | Modelo | **Mercado (Shin)** |
|---|---|---|
| Brier (↓ melhor) | 0,570 | **0,485** |
| Logloss (↓ melhor) | 0,981 | **0,822** |
| Acerto do palpite | 50,0% | **68,6%** |

O mercado vence em **todas** as métricas, por margens grandes. Como a régua de
aposta é o preço de fechamento (= o mercado), bater o mercado é a única forma de
ter edge. O modelo não chega perto.

## Achado 3 — por que as apostas de valor perdem (o golpe de misericórdia)

Uma aposta de "valor" nasce quando o modelo **discorda** do mercado. Dos 35 jogos:

| | n | % |
|---|---|---|
| Modelo e mercado **concordam** no palpite | 23 | 66% |
| **Discordam** (= onde a aposta de valor nasce) | 12 | 34% |

E nos 12 jogos de discordância:

- Modelo acertou: **1 de 12 (8%)**
- Mercado acertou: **7 de 12 (58%)**

Ou seja: exatamente onde o modelo "vê valor", ele está quase sempre **errado** e o
mercado está certo. A aposta de valor é, na prática, **apostar nos erros do
próprio modelo** contra um mercado eficiente.

## Achado 4 — causa raiz: ordenação de força errada (compressão + inflação)

O modelo não só é incerto demais (probabilidades achatadas) — ele **escolhe o
favorito errado**. O Elo comprimido e inflado continentalmente coloca times na
ordem errada (Japão 1771 > Brasil 1745; Marrocos 3º; Colômbia acima de Portugal).
Quando o Elo aponta o favorito errado, o modelo herda o erro e ainda o transforma
em "valor" contra o mercado. Detalhe mecânico em [VIES_ZEBRA.md](VIES_ZEBRA.md).

## Achado 5 — o +44% revisitado

| | |
|---|---|
| P&L total | +21,58u |
| 2 maiores ganhos (Spain–CV, Ecuador–Curaçao, ambos empate 0-0) | +22u |
| P&L sem esses 2 outliers | ≈ −0,4u |
| Bootstrap IC 95% do ROI total | [−27%, +127%] (cruza zero) |

O lucro inteiro é **dois empates azarões de odd alta** que entraram. É variância,
não edge — e o teste de significância concorda.

---

## Pode ser consertado?

**Parcialmente, mas não vira uma máquina de bater o mercado.**

- O fix pré-registrado da v2.0 (**prior FIFA de-comprimindo o Elo na MLE**) deve
  melhorar a **ordenação de força** (parar de pôr Japão sobre Brasil) — isso
  ataca o Achado 4 e provavelmente sobe a acurácia do palpite.
- **Mas o muro é a eficiência do mercado.** O mercado de fechamento de Copa do
  Mundo é dos mais líquidos e eficientes do mundo. Mesmo um modelo bem calibrado
  raramente o bate de forma consistente no 1X2. O CLV — quando a população
  `open` acumular nos playoffs — é o juiz final, mas a expectativa honesta é
  CLV ≤ 0 no 1X2 da Copa.
- Onde poderia haver edge real (não testado): **mercados menos eficientes** —
  totais/handicaps de seleções pequenas, props de jogador, ou competições
  obscuras onde o mercado precifica pior. Nada disso está validado aqui.

## Vale a pena continuar?

Análise honesta de três caminhos:

| Caminho | Veredito |
|---|---|
| **Apostar 1X2 da Copa com o modelo atual** | ❌ Não. Sem edge; você sangra pro vig apostando os erros do modelo. |
| **Usar como preditor/ferramenta de estudo** | ✅ Sim. Bate o acaso, é interpretável, bom para entender jogos e treinar intuição — sem dinheiro em risco. |
| **Pesquisar edge de verdade (v2.0 + mercados ineficientes)** | 🟡 Talvez. Caminho longo: de-comprimir o Elo, deixar o CLV `open` acumular, e CAÇAR mercados menos eficientes. Só promover o que sobreviver ao CLV out-of-sample. |

## Recomendação

1. **Não apostar 1X2 da Copa** com o modelo atual — a evidência é clara.
2. **Deixar o CLV `open` acumular** nos playoffs (coletar pré-apito) — é o único
   juiz que falta e fecha a tese com rigor estatístico em julho.
3. **Tratar o fix do Elo (prior FIFA) como pesquisa de v2.0**, validada por CLV,
   fora do calor do torneio — exatamente como o projeto já tinha pré-registrado.
4. **Reposicionar a expectativa:** o valor entregue aqui não é "ganhar dinheiro
   na Copa" — é uma plataforma honesta que **sabe medir quando não tem edge**.
   Isso é raro e é o que separa método de aposta no escuro.

---

## Anexo A — Calibração (1X2) e Over/Under (resposta ao peer-review)

**Diagrama de calibração 1X2** (pool das 3 saídas, 44 jogos):

| Faixa prevista | n | previu | real | viés |
|---|---|---|---|---|
| 10–20% | 14 | 15,7% | 14,3% | ok |
| 20–30% | 58 | 25,1% | 25,9% | ok |
| 30–45% | 31 | 37,1% | 29,0% | super-confiante |
| 45%+ | 27 | 57,6% | 66,7% | **sub-confiante** |

O modelo é tímido nos favoritos fortes (diz 57,6% → acontece 66,7%) e confiante
demais no meio — probabilidades **achatadas para o centro**, a assinatura da
compressão de Elo vista por calibração.

**Over/Under 2.5** (35 jogos com odds), a hipótese "mercado menos eficiente":

| | Modelo | Mercado |
|---|---|---|
| Brier | 0,511 | **0,460** |
| Acerto | 45,7% | **51,4%** |

O mercado ainda bate, mas o gap (0,051) é **menor** que no 1X2 (0,085) — não
confirma a hipótese nesta amostra, mas é a direção menos desfavorável.

## Limitações (incorporando peer-review)

1. **N microscópico (44 jogos).** Variância domina; sem poder estatístico para
   afirmar ausência de edge fora deste escopo. A robustez vale só para
   "1X2 fechamento Copa".
2. **Viés de arena.** A Copa é um dos mercados mais eficientes e líquidos do
   mundo, e Elo de seleções é inerentemente comprimido (poucos confrontos
   diretos). O modelo foi julgado no pior cenário possível.
3. **CLV não medido.** Faltou o teste definitivo: o modelo bate a linha de
   **abertura**? Só nasce com a população `open` dos playoffs (coleta pré-apito).
4. **O teste de discordância (8% vs 58%) tem N=12** — heurística forte na
   direção (binomial sugere p≈0,003 de ser ≤1/12 por acaso a 50%), mas com odds
   desiguais o rigoroso seria McNemar, e com N=12 o poder é baixo.

## Roadmap — onde o "termômetro" pode achar água navegável

A infraestrutura walk-forward é o ativo. Próximos testes, por ordem de valor:

1. **CLV vs odds de abertura** — o juiz de skill que falta (playoffs).
2. **Ligas de clubes (N alto)** — Premier/Brasileirão: 380 jogos/temporada dão
   poder estatístico que 44 jogos de Copa nunca darão.
3. **De-comprimir o Elo** (prior FIFA / re-tunar K para maximizar Brier) —
   ataca a sub-confiança nos favoritos vista no Anexo A. Validar out-of-sample.
4. **Ensemble** — Elo como UMA feature dentro de Gradient Boosting (xG, fadiga,
   desfalques), não o modelo inteiro.
5. **Kelly fracionado + Monte Carlo de ruína** — controle de banca quando (se)
   um edge real for provado.

## Reprodutibilidade
`python scripts/eval_walkforward.py` (walk-forward + modelo vs mercado +
discordância). `python scripts/calib_ou.py` (calibração + O/U). Diagnóstico do
viés: `python scripts/diag_zebra.py`.
