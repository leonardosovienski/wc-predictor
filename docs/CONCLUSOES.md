# Conclusões — estado final da investigação (pós-confound)

> Capstone da investigação causal do wc-predictor. Consolida o que ficou
> demonstrado, o que é hipótese, e o que foi refutado — incluindo a retratação
> do resultado do Maher após o experimento de controle. Docs de apoio:
> [CAUSA_RAIZ.md](CAUSA_RAIZ.md), [VIES_ZEBRA.md](VIES_ZEBRA.md),
> [MAHER_RESULTADO.md](MAHER_RESULTADO.md), [RELATORIO_VIABILIDADE.md](RELATORIO_VIABILIDADE.md).

## O enigma e a resposta

**Pergunta:** por que o pipeline evita favoritos (6%) e concentra apostas em
empate (55%) e azarão (38%)?

**Resposta (demonstrada por eliminação + intervenção):**
- O **filtro de valor** é passivo (Exp B/C).
- **Dixon-Coles ρ** e a **forma do link (cosh)** são inocentes (Exp F, cosh-free).
- O **componente azarão** nasce no estágio **Elo→λ**: o input é um único escalar
  (ΔElo) que achata as probabilidades (probMax 56% vs 66% do mercado).
- O **componente empate** NÃO nasce no modelo — o modelo é **bem calibrado** no
  empate (calibração condicional, N=2.424). Nasce no `edge`, com o mercado
  precificando empate abaixo (hipótese de draw-shading, **bloqueada por dado**).

## O que ficou DEMONSTRADO

1. O +44% de ROI era variância (2 zebras; bootstrap cruza zero).
2. Walk-forward: o modelo bate o acaso mas **perde para o mercado** (Brier 0.57 vs 0.49).
3. As apostas de "valor" são as divergências do modelo, e na discordância o modelo
   acerta 8% vs 58% do mercado.
4. O achatamento favorito/azarão vem do **input escalar (Elo→λ)**, não da forma
   funcional nem dos módulos acessórios.
5. O modelo é **calibrado no empate** (gap ≤1.7% por faixa, N=2.424).
6. **Ataque/defesa (Maher) NÃO ajuda em seleções** — controle de força-única bate
   o Maher (0.5131 vs 0.5174). Re-parametrizar o mesmo dado de gols não cria info.

## O que é HIPÓTESE (não demonstrado)

- **Draw-shading sistemático do mercado** — sugestivo (Copa: 20% vs 25.5% real),
  mas N=51 e agregado. Exige odds históricas (de clube, mais baratas).
- **Features externas (xG, valor de elenco) ajudam** — plausível, **não testado**.
  São informação que o Elo NÃO vê (≠ atk/def, que é o mesmo dado reorganizado).

## Lead aberto (real, não-isolado)

- **Estimar força líquida por ridge batch pode bater o Elo online** (força-única
  0.513 vs Elo 0.547). Ganho de 0.034 **multi-confundido** (batch-vs-online,
  janela 4a-vs-6a, verossimilhança-vs-heurística). Vale um experimento de
  isolamento futuro — é a única pista positiva que sobreviveu.

## A lição metodológica (a entrega mais valiosa)

A v1 do `MAHER_RESULTADO.md` declarou que atk/def ajudava — **um confound virou
manchete**. O experimento de controle (força-única, mesma máquina) **reverteu a
conclusão**. Sem ele, o projeto perseguiria features de atk/def por meses achando
ter uma melhoria comprovada. **A disciplina de isolar pegou o próprio maior
falso-positivo da sessão.** É o tipo de erro que quebra projetos de aposta — e foi
morto primeiro.

## O caminho (sem dívida pendente)

1. **CLV dos playoffs** — observação forward passiva até 19/07/2026 (sem reaposta).
2. **Migrar para clubes** — football-data.co.uk (gols + odds de fechamento, grátis,
   décadas). Lá: (a) atk/def tem 38+ jogos/time → pode render onde em seleção não
   rendeu; (b) testar draw-shading com N robusto; (c) mercado historicamente menos
   eficiente. Reusar o estimador ridge batch que se mostrou promissor.
3. **Isolar o lead do estimador** (opcional) — batch vs online, controlando janela.

Não achamos um bug nem uma transformação mágica. Achamos o **limite exato** do
modelo atual e provamos, por experimento controlado, o que está além dele.
