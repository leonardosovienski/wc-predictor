# Revisão Final do Estado Atual do wc-predictor-v2

> Registro definitivo da investigação causal (2026-06-27). Consolida e supera os
> docs de apoio: [CAUSA_RAIZ.md](CAUSA_RAIZ.md), [CONCLUSOES.md](CONCLUSOES.md),
> [VIES_ZEBRA.md](VIES_ZEBRA.md), [MAHER_RESULTADO.md](MAHER_RESULTADO.md),
> [RELATORIO_VIABILIDADE.md](RELATORIO_VIABILIDADE.md), [V2_BLUEPRINT.md](V2_BLUEPRINT.md).
> Experimentos reproduzíveis em `scripts/`.

## 1. Resumo executivo

O comportamento observado (apostas concentradas em azarões e empates, sem edge
contra o mercado) decorre de um **déficit de informação na entrada**: o sistema usa
exclusivamente ΔElo como preditor, impondo um teto estrutural. Nenhum módulo interno
(filtro, Dixon-Coles, forma do link) é defeituoso — todos operam corretamente sobre
a informação que recebem. As limitações são estruturais, não acidentais.

## 2. O que foi descoberto

1. **ROI +44% era variância** — walk-forward: acurácia 50%, Brier 0.570 vs 0.485 do
   mercado; bootstrap cruza zero. Sem edge demonstrável.
2. **Filtro de valor é passivo** — só seleciona divergência; não a cria (ruído
   simétrico e prob. de mercado confirmam).
3. **Dixon-Coles ρ inocente** — ρ=0 muda empate em 0.8pp.
4. **Forma do link (cosh) não é a restrição** — cosh-free (β1,β2 livres): Brier
   0.5467→0.5463, probMax 56.2%→56.5% (ruído).
5. **Empate bem calibrado** — holdout 2.424 jogos, desvios +0.2% a +1.7% por faixa.
6. **Favorito/azarão limitado pelo input escalar** — probMax ~56% vs ~66% do
   mercado; viés inevitável com ΔElo sozinho.
7. **Atk/def dos mesmos gols não agrega** — força-única (Brier 0.5131) supera Maher
   (0.5174). Reorganizar os mesmos placares não é informação nova.
8. **Estimador ridge batch supera o Elo online** — ΔBrier ≈ 0.034, real mas
   multi-confundido (janela/verossimilhança/cadência), não decomposto.

## 3. Gargalos

1. **Input restrito a um escalar (ΔElo)** — na transformação ΔElo→λ. Evidência:
   probMax nunca passa de ~56%; cosh-free não muda nada; reorganizar a mesma info
   (atk/def) não melhora.
2. **Esparsidade em seleções** (~40 jogos/time em 4 anos) — força-única (1 param)
   supera Maher (2 params). **Ressalva de rigor:** isso é *consistente* com
   esparsidade, mas **não isolado** de "atk/def dos mesmos gols é redundante com a
   força líquida, independente de N". Só testar em **clubes (dado denso)**
   distinguiria as duas explicações.
3. **Ausência de odds históricas de fechamento** — impede testar comportamento do
   mercado (draw-shading) com poder estatístico.

## 4. Hipóteses descartadas

| Hipótese | Por quê |
|---|---|
| Filtro EV cria o viés | Passivo (ruído simétrico + prob. mercado) |
| ρ infla empates | ρ=0 muda 0.8pp |
| Simetria/cosh causa achatamento | cosh-free não muda Brier/probMax |
| Escalar b resolve | Eleva probMax mas piora Brier e descalibra empate; b=1.065 é o ótimo MLE |
| Modelo superestima empates | Calibração condicional <2% |
| Atk/def (Maher) melhora | Força-única supera; ganho era do estimador |

## 5. Hipóteses em aberto (por falta de dado)

1. **Draw-shading do mercado** — N=51 (Copa) insuficiente; holdout sem odds.
2. **Features externas (xG, valor de elenco)** — não testadas; sinal que o Elo não vê.
3. **Decomposição do ganho do ridge batch** — falta experimento fatorial.
4. **Bater o mercado de seleções** — nenhuma config passou de probMax ~56%.

## 6. Mapa do pipeline

| Módulo | Estado |
|---|---|
| Atualização de Elo | Funciona |
| **Transformação Elo→λ** | **Limitação conhecida** (escalar único → probMax comprimido). Não é bug |
| Binomial Negativa | Funciona |
| Dixon-Coles (ρ) | Inocentado |
| **Probabilidades 1X2** | **Limitação conhecida** (viés favorito/azarão); empate calibrado |
| Filtro de valor | Inocentado (passivo) |
| Backtest/ROI | Funciona, mas ROI volátil — não usar como métrica primária |

## 7. Cadeia causal consolidada

**Demonstrado:** input só ΔElo (escalar) → λ_total função exclusiva do equilíbrio →
baixa variância de λ_total → entropia alta / probMax ~56% → sub-rateia favorito,
super-rateia azarão → filtro seleciona essas divergências → apostas em azarão/empate.
Empate isoladamente é calibrado → o excesso vem da divergência com o mercado.

**Evidência forte:** ridge batch > Elo online (ΔBrier ≈ 0.034), multi-confundido.

**Hipótese:** mercado subprecifica empate (draw-shading) — não demonstrado.

## 8. Erros de interpretação cometidos (e corrigidos)

1. Aceitar +44% como edge → era variância (walk-forward + bootstrap).
2. Suspeitar do filtro antes de isolá-lo → passivo.
3. Culpar Dixon-Coles → ρ=0 quase não muda.
4. Enquadrar como "só azarão" → eram 55% empates.
5. Dizer "NUNCA aposta favorito" → tendência de 88%, não lei.
6. Usar média agregada p/ acusar o mercado no empate → rebaixado a hipótese.
7. Concluir que atk/def ajuda → falso positivo; o controle de força-única falseou.
8. Prever falha do Maher, abandonar ao ver o Brier cair, e a previsão original
   estava certa → um confound enganou até a intuição correta. Lição: manter a
   hipótese nula até um controle adequado refutá-la.

## 9. Limites conhecidos

- **Teto de informação:** com só ΔElo, probMax ~56% e Brier > mercado — estrutural.
- **Teto de complexidade:** esparsidade impede >1 param/time confiável em seleções.
- **Limite de validação externa:** sem odds históricas, sem teste conclusivo de mercado.
- **Limite de generalização:** auditado em seleções; clubes não testados (e podem
  diferir por densidade de dado + mercado menos eficiente).

## 10. Estado atual e veredito

**Sabemos:** a causa raiz é déficit de informação no input; filtro/ρ/cosh inocentes;
empate calibrado; re-parametrizar os mesmos gols não agrega; ridge batch > Elo online
(não decomposto).

**Não sabemos (falta dado):** draw-shading sistemático; efeito de features externas;
decomposição do ganho do ridge batch.

**Veredito:** o problema nunca foi código — foi déficit de informação. O modelo fazia
o possível com ΔElo. O que falta para melhorar **não é conserto, é dado** (informação
externa) ou **arena** (clubes, onde o mesmo dado rende mais e o mercado é menos
eficiente). A missão era construir o sistema e entendê-lo com rigor — **cumprida.** A
fronteira está mapeada: o que está além dela não é questão de código, mas de dados.
