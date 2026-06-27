# v2.0 — Blueprint: subir o teto do modelo com features point-in-time

> Origem: a avaliação walk-forward (ver [RELATORIO_VIABILIDADE.md](RELATORIO_VIABILIDADE.md))
> provou que o Elo puro tem **teto abaixo do mercado** no 1X2 de seleções, e que
> de-comprimir a probabilidade **não** resolve (sharpening ótimo a*≈1.05 — o modelo
> já é calibrado). A conclusão: o limite é a **informação de entrada**, não a
> matemática. Este documento fixa a arquitetura e a disciplina para testar
> features novas sem se enganar.

## Princípio nº1 — point-in-time ou nada

Toda feature precisa do valor **como era na data do jogo**, nunca o de hoje. Usar
o valor de elenco atual para um jogo de 2018 é lookahead puro. Isso **elimina**
features que só existem no presente, por mais preditivas que sejam.

| Feature | Sinal | Histórico point-in-time? | Veredito |
|---|---|---|---|
| **Fadiga (Δdias de descanso)** | médio | ✅ derivável das datas dos jogos (já temos) | 🟢 **PoC primeiro** |
| **Mando / sede** | baixo-médio | ✅ já no schema (`neutral`, host) | 🟢 barato |
| **Valor de elenco (Transfermarkt)** | alto | ⚠️ só valor ATUAL; snapshots históricos são raros | 🟡 difícil backtestar |
| **xG recente** | alto | ❌ coletado só a partir de 2026 (98 jogos); FBref perdeu Opta | 🔴 sem história = sem treino |

> O paradoxo: as features que mais vencem o Elo (xG, elenco) são as que menos
> temos historicamente. Por isso a PoC começa pela **fadiga** — sinal menor, mas
> 100% backtestável de graça.

## Princípio nº2 — arquitetura: injetar, não substituir

O motor atual é **Binomial Negativa + Dixon-Coles** sobre gols — precifica a
distribuição exata de placares (1X2 **e** Over/Under **e** placar exato). Trocá-lo
por uma regressão logística de 1X2 seria **regressão de capacidade** (perde O/U e
placares).

O motor já tem o **hook certo** na link function (`model.predict_match`):

```
λ_home = exp(a + b·Δelo/400 + θ·feature_home)
λ_away = exp(a − b·Δelo/400 + θ·feature_away)
```

A feature nova entra como `θ·feature`, calibrada por MLE junto com (a,b,α,ρ). Isso
**preserva** todos os mercados e só desloca a expectativa de gols pelo novo sinal.
Nenhum modelo paralelo é necessário.

> Nota técnica: scaling/StandardScaler é irrelevante aqui — não é regressão
> logística regularizada; a MLE acha o θ na escala certa. Centrar a feature
> (ex.: descanso − média) ajuda só a interpretabilidade do θ.

## Princípio nº3 — blindagem do test set (o mais importante)

A Copa 2026 tem **N=44** e é o mercado mais eficiente do mundo. Testar features ali
repete o erro que o peer-review apontou: variância domina, e contamina o set
reservado ao CLV. Split disciplinado:

| Conjunto | Janela | Papel |
|---|---|---|
| **Treino** | internacionais ~2010 → 2023-12-31 | calibra (a,b,α,ρ,θ) — **frozen** |
| **Holdout da PoC** | internacionais 2024-01 → 2026-05 (milhares) | Brier: NB+feature vs NB puro |
| **Copa 2026 + playoffs** | intocado | reservado ao veredito de **CLV** |

A pergunta da PoC **não** é "ajuda na Copa?" e sim "**bate o Elo puro no futebol
de seleções em geral?**" — com N nas milhares, há poder estatístico.

## Princípio nº4 — caveat de regime shift (honestidade)

Fadiga aprendida em **amistosos/eliminatórias** (treino) pode não transferir para o
**calendário comprimido de torneio** (teste real). Dois dias de descanso numa data
FIFA ≠ dois dias após as oitavas. Mesmo uma PoC positiva no holdout **subestima**
o quanto a fadiga pesa no torneio. Modelar fadiga não-linear (cap em ~5 dias +
flag para `<3 dias`) mitiga, mas não elimina, o shift.

## Roteiro de execução

1. ✅ Este blueprint.
2. ✅ **PoC fadiga** (`scripts/poc_fadiga.py`) — **RESULTADO: ~0 ganho** (ver abaixo).
3. ⬜ Atacar **valor de elenco** com snapshots point-in-time (a parte cara,
   "arqueologia de dados") — é a única feature de sinal alto restante.
4. ⬜ Ensemble só se 2+ features sobreviverem ao holdout — Elo como UMA feature.
5. ⬜ Promoção ao motor: regra do projeto — só vai se mover métrica out-of-sample,
   validado por CLV, **fora** do calor do torneio.

## Resultado da PoC de fadiga (2026-06-27)

Holdout de 2.424 internacionais (2024 → 2026-05), `θ` calibrado em 13.273 jogos
de treino (2010–2023):

| Modelo | Brier | Acerto |
|---|---|---|
| NB puro (Elo) | 0,53643 | 57,6% |
| NB + fadiga (θ=−0,031) | 0,53624 | 57,5% |

Ganho: **+0,04% de Brier**, e a fadiga melhorou só **43% dos jogos** (< metade =
ruído). **Veredito: a fadiga não agrega.**

**Causa (confirma o caveat #4):** o efeito de fadiga só existe no regime de
torneio (2–3 dias entre jogos), que mal aparece no treino (amistosos/eliminatórias
têm semanas de descanso). O feature não tem variância onde importa → o modelo não
aprende. Lição: **dado barato (fadiga histórica) não contém o sinal**; o sinal
mora no valor de elenco / xG, que exigem resolver point-in-time. Próximo passo só
vale o custo se houver apetite para a arqueologia de dados do item 3.
