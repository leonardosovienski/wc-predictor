# Análise de causa raiz — por que o modelo evita favoritos?

> Investigação causal (não exploratória) conduzida sob revisão científica rigorosa.
> Regra: separar fato demonstrado / correlação / hipótese; nunca transformar
> hipótese em conclusão; toda afirmação ligada a um experimento de intervenção.
> Reprodutível: `scripts/prova_mecanismo.py`, `scripts/experimentos_causa.py`,
> `scripts/exp_f_rho.py`.

## Correção da premissa

O fenômeno **não** é "o modelo só aposta em azarão". A distribuição real das
apostas-candidatas (filtro `0.02 < p−1/odd ≤ 0.15`, 51 jogos da Copa):

| Favorito | Empate | Azarão |
|---|---|---|
| **6%** | **55%** | **38%** |

O fenômeno correto é: **o modelo praticamente evita favoritos**, e o componente
**dominante é EMPATE**, não azarão. Toda a investigação foi reorientada por isso.

## Pipeline (o que cada módulo produz)

ingestão → Elo (decay+janela) → link `λ=exp(a+b·Δelo/400)` → NB+Dixon-Coles →
grade de placares → 1X2/O-U → de-vig (Shin) → `edge=p−1/odd` → filtro `]2%,15%]`.

## Experimentos de intervenção (um componente por vez)

| Exp | Intervenção | Resultado | Conclusão |
|---|---|---|---|
| **B** | p = mercado (Shin) exato | **0 apostas** | filtro não gera viés sozinho |
| **C** | p = Shin + ruído N(0,σ) simétrico | apostas ~⅓/⅓/⅓ (fav/emp/aza) | **filtro não amplifica** erro em odd alta |
| **A** | Elo de-comprimido (b×k: 1→2) | azarão 38%→22%, favorito 6%→27% | **compressão CAUSA o componente azarão** |
| **F** | ρ do Dixon-Coles → 0 (curva) | empate 55%→54% (não move) | **Dixon-Coles NÃO causa o empate** |

## Cadeia causal (com rótulos)

```
Modelo evita favoritos (fav 6%)
│
├── componente AZARÃO (38%)
│      └── DEMONSTRADO: compressão de Elo (Exp A, intervenção monotônica)
│
├── FILTRO de valor (edge = p − 1/odd)
│      └── INOCENTADO (Exp B e C — passivo, seleciona divergência pré-existente)
│
└── componente EMPATE (55%, dominante)
       ├── REFUTADO: Dixon-Coles ρ (Exp F)
       ├── REFUTADO: compressão como causa principal (Exp A mal move o empate)
       └── FORTEMENTE SUPORTADO (não provado a N alto): o MERCADO sub-precifica
           empate. Evidência: realidade 27% > modelo 24% > mercado 20% — o desvio
           (modelo > mercado) nasce do mercado estar mais longe da realidade, não
           de o modelo inflar empate (ele até sub-prevê vs a realidade).
```

## Causa raiz (resposta)

- **O filtro NÃO é a causa** (Exp B/C — demonstrado).
- A causa é a **divergência sistemática e direcional modelo−mercado**, que se
  decompõe em:
  - **Azarão (38%)** ← **compressão de Elo** (demonstrado por intervenção, Exp A).
  - **Empate (55%, dominante)** ← **sub-precificação de empate pelo mercado**
    (fortemente suportado; o modelo está mais perto da realidade que o mercado
    no empate). **Não** é Dixon-Coles (refutado) nem principalmente compressão.

## Inferência residual + experimento mínimo

**Não demonstrado a N alto:** "o mercado sub-precifica empate sistematicamente".
Evidência forte em N=51 (modelo<realidade<... mercado mais baixo).

**Exp G (mínimo):** curva de calibração de empate **do mercado** (P(empate)_Shin
vs taxa real) num conjunto grande de jogos com odds. **Limitação de dados:** só
há odds da Copa 2026 (51 jogos); N alto exigiria odds históricas de internacionais
que o projeto não coleta. Logo, hoje, esta é a fronteira honesta da investigação.

## Auditoria de inspeção + calibração por faixas (fecha a localização)

Inspeção (sem alterar o modelo, `scripts/auditoria.py`):
- **Sharpness:** 1X2 do modelo é achatado — prob máxima média 52% vs 66% do
  mercado; entropia 0.994 vs 0.814.
- **vs realidade (60 jogos):** modelo sub-rateia favorito (42% vs 50% real),
  super-rateia azarão (33.5% vs 23.3%), e é **acurado no empate** (24.5% vs 26.7%).
- λ_total: média 2.66 (dp só 0.18) vs gols reais 2.95 — separação fraca.

**Calibração de empate por faixas** (`scripts/calib_empate.py`):
- Modelo, holdout 2.424 jogos (sem odds, N alto): previu ≈ observado em TODA
  faixa (gap ≤ 1.7%). **Demonstrado: o modelo não tem defeito de empate.**
- Mercado, Copa N=51: empate mercado 20% vs observado 25.5% — sugestivo, mas
  **N pequeno + agregado ⇒ permanece HIPÓTESE** (não se conclui que o mercado
  erra com média de amostra pequena).

### Etapa 2.2 — λ_total é fixo pela FUNÇÃO, não pelos dados (`scripts/elasticidade.py`)
`λ_total = 2·exp(a)·cosh(b·Δelo/400)`. A previsão analítica bate **exata** com o
observado por faixa de |Δelo| (2.50/2.54/2.68/3.12/4.15). Para 76% dos jogos
(|Δelo|<200), λ_total ∈ [2.50, 2.69] — quase constante (cosh plano perto de 0).
O link **redistribui** gols (λ_diff +1254% na faixa) mas **mal muda o total** —
ignora qualidade de ataque/defesa por construção. **Demonstrado.** Ressalva:
P(empate) NÃO é constante (27%→8.6% por |Δelo|) e é calibrada — o modelo
discrimina empate; só o λ_total é estruturalmente fixo.

### Localização final (resposta ao protocolo)
- **Favorito/azarão** → nasce na **transformação Elo→λ** (achatamento). Demonstrado
  (inspeção + Exp A).
- **Empate (55%)** → **não nasce no modelo** (calibrado a N=2.424). Nasce no
  estágio `edge = modelo − mercado`; a causa market-side (sub-precificação de
  empate) é **hipótese bloqueada por dados** (faltam odds históricas).

## Quantificação (a ressalva do revisor)

A frase correta **não** é "a compressão é a causa". É: "a compressão é **uma**
causa demonstrada do **componente azarão (38%)**". O componente dominante (empate,
55%) tem outra origem (mercado), e a contribuição relativa de cada fator ao
comportamento global ainda não foi totalmente decomposta — só os sinais e as
direções estão estabelecidos por intervenção.
