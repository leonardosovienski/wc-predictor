# Resultado: o ganho do "Maher" era ESTIMADOR, não ataque/defesa (CORRIGIDO)

> ⚠️ **CORREÇÃO (confound fechado, `scripts/confound.py`).** A versão anterior
> deste doc concluía que ataque/defesa (Maher) batia o Elo. **Estava errado** — era
> um confound de estimador/cadência. O controle de força-única (mesma máquina batch,
> 1 rating/time) **bate o Maher** (0.5131 vs 0.5174). **Ataque/defesa NÃO agrega** em
> seleções (esparsidade). O ganho real vinha do **estimador batch**, não do split.
> Reprodutível: `scripts/maher.py`, `scripts/maher_verif.py`, `scripts/confound.py`.

## Desenho

- **Link Maher** (substitui `exp(a±b·ΔElo/400)`):
  `λ_home = exp(μ + atk_home − def_away + γ·[não-neutro])`, `λ_away = exp(μ + atk_away − def_home)`.
- **NB(α) + Dixon-Coles(ρ) idênticos ao baseline** (isola a fonte do λ).
- **Regularização L2** (efeitos aleatórios gaussianos) sobre atk/def; `λ_reg=3`
  escolhido por validação nos últimos 6 meses do 1º treino.
- **Walk-forward:** 29 refits mensais, janela móvel de 4 anos, previsão estrita
  com dados até t−1. Holdout: 2.424 internacionais (2024 → 2026-05). Copa intocada.

## Resultado (significativo e estável)

| Modelo | Brier | LogLoss | probMax | gap empate |
|---|---|---|---|---|
| Baseline Elo | 0.5467 | 0.9235 | 56.2% | −0.7% |
| **Maher atk/def** | **0.5174** | **0.8823** | 55.3% | +0.5% |

- **Teste pareado:** ΔBrier +0.0293, SE 0.0035, **t=8.5**, IC95% [+0.023, +0.036]
  (não cruza zero). Maher melhor em 56% dos jogos.
- **Estabilidade temporal:** Δ positivo em 2024 (+0.033), 2025 (+0.023), 2026 (+0.038).

## Interpretação (calibrada)

- A melhora é de **discriminação/resolução** (acerta o favorito mais vezes), **não
  de nitidez** — probMax fica ~55%, ainda abaixo do mercado (66%). Logo o Maher é
  **melhor preditor**, mas provavelmente **ainda não bate o mercado** na Copa
  (gap de informação — escalação/lesão/dinheiro — persiste).
- **Refuta a premissa fundadora** ("dado de seleção esparso demais para mais que
  Elo"): atk/def regularizado extrai sinal incremental real mesmo com ~10 jogos/ano.

## O confound fechado (a correção, `scripts/confound.py`)

Controle: modelo de **força-única** (1 rating/time), MESMA máquina batch
(Poisson-ridge, refit mensal, janela 4a, mesma regularização) — isola atk/def vs
cadência. Holdout idêntico:

| Modelo | Brier |
|---|---|
| Elo congelado (original) | 0.5467 |
| **Força-única (batch)** | **0.5131** |
| Maher atk/def (batch) | 0.5174 |

- **Força-única − Maher = −0.0043** (SE 0.0013) → atk/def **não agrega** (piora um pouco).
- **Elo − força-única = +0.0336** (SE 0.0038) → o ganho veio do **estimador batch**.

## Conclusão corrigida

1. **Ataque/defesa NÃO ajuda em seleções** — a esparsidade derrota os 2 params/time.
   A previsão original do projeto ("Elo é o teto pra dado esparso") **se sustenta**
   quanto à *informação*; não há ganho de feature.
2. O ganho real (0.034) é do **estimador de força líquida** (Poisson-ridge batch >
   Elo online), mas é **multi-confundido** (batch-vs-online, janela 4a-vs-6a,
   verossimilhança-vs-heurística, refit-vs-congelado) — **não isolado**. Afirmar
   "qual" desses causa o ganho exigiria mais um experimento de isolamento.
3. **Lição:** a v1 deste doc transformou um confound em manchete. O experimento de
   controle (força-única) reverteu a conclusão. Sem ele, o projeto teria perseguido
   features (atk/def, xG, elenco) achando que "mais informação ajuda" — quando o
   sinal real estava no **estimador**, não na informação.
