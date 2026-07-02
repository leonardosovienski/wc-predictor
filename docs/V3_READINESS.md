# V3 Readiness — inventário honesto (2026-07-02)

> Levantamento pós-auditoria dos componentes da v3 (VORP + Hot Path). Cada
> afirmação abaixo vem de leitura do código e de consulta ao banco real —
> nada foi assumido a partir de docstrings. Regra herdada da auditoria:
> **nenhuma conclusão da v3 é citável antes de os itens "bloqueadores" serem
> resolvidos.**

## Resumo executivo

A v3 tem engenharia adiantada e pesquisa atrasada — a ordem inversa da
saudável. O hot path (Redis + Numba + C#) está funcional em protótipo e resolve
um problema de latência que **ainda não existe**, enquanto a fonte do suposto
edge (VORP) **não roda com os dados atuais** e o teste de sobrevivência tem um
bug que impede exatamente o modo híbrido que ele existe para medir.

| Componente | Estado | Bloqueadores |
|---|---|---|
| `src/research/vorp_ridge.py` | **Não executável com o banco atual** | dados de 2021/2022 inexistentes; lookahead de Elo |
| `src/research/survival_test.py` | **Quebrado no modo híbrido** | `TypeError` na chamada; lookahead de Elo; seasons parciais |
| `src/kernel_daemon.py` | Protótipo funcional | duplica a matemática do model.py; zero testes; deps pesadas |
| `dotnet/LineupWorker` | Protótipo compilado | sem testes; depende do kernel; não auditado em detalhe |

---

## 1. `src/research/vorp_ridge.py` — extração de VORP

**O que faz:** regressão Ridge esparsa (via LSQR, sem sklearn) do xG diferencial
por partida sobre indicadores de presença de jogador (+1 home, −1 away) com
`elo_diff/400` como controle. Produz artefato JSON com `beta_players`,
`replacement_levels` por posição (média dos 20% inferiores × 0.8) e
`beta_elo`. Código limpo e legível.

**Estado real: não executável.**
- `TRAIN_SEASONS = {"2021", "2022"}` (linha 169), mas `sofascore_matches` só
  contém seasons **{2024, 2026}** (verificado no banco em 2026-07-02). O script
  morre no `sys.exit` da linha 177 antes de treinar qualquer coisa. Ou seja:
  **nenhum artefato VORP legítimo pode ter sido gerado com este banco.**
- `player_comp_stats` (posições, para o replacement level) depende do
  `ingest_fbref`, que está bloqueado (HTTP 403) — cobertura de posição incerta.

**Lookahead a remover:** `_load_matches` (linhas 34-49) lê `db.load_elo`
(= `current_elo`, o rating de HOJE) como controle das partidas de treino.
Trocar por `ratings.ratings_asof(matches, cfg_elo, dates)` — o helper já
existe desde a auditoria. Monitorado pelo `scripts/ci_check.py` (WARN).

**Testes que faltam:** nenhum teste existe. Mínimo: (a) β recupera sinal em
dados sintéticos (jogador bom → coeficiente positivo); (b) replacement level
por posição; (c) fallback de estreante.

## 2. `src/research/survival_test.py` — Go/No-Go da v3

**O que faz:** compara Elo puro vs Elo+VORP na temporada de teste com
Diebold-Mariano/HLN, Brier/BSS, curva de calibração do Over 2.5, CLV simulado
e PSR com Kelly fracionado. É o quality gate desenhado para decidir a v3.

**Estado real: quebrado no caminho que importa.**
- `_predict_hybrid` (linhas 66-73) chama `predict_match(..., theta=theta)` —
  **`theta` não é kwarg de `predict_match`** (θ vai DENTRO de `params`, tupla
  de 5 ou dict). O modo híbrido levanta `TypeError` na primeira partida.
  Conclusão forte: **o survival test nunca completou uma execução híbrida.**
  Qualquer decisão de v3 "baseada" nele é vazia.
- `TEST_SEASONS = {"2023", "2024"}`: o banco só tem 2024 → o teste rodaria com
  metade da reserva planejada (Copa América + Euro 2024, sem 2023).
- `db.load_elo` na linha 172 — mesmo lookahead do vorp_ridge (Elo de hoje
  aplicado a partidas de 2024). Monitorado pelo ci_check (WARN).

**Correções antes de qualquer uso:** (1) passar θ dentro de `params`
(`(a, b, alpha, rho, theta)`); (2) `ratings_asof` por data; (3) redefinir as
seasons de teste para o que existe no banco; (4) cuidado com a chamada
posicional de `predict_match` (P5) — usar sempre kwargs.

## 3. `src/kernel_daemon.py` — serving quente (Zona 3)

**O que faz:** daemon asyncio residente; recebe pedidos via canal Redis
`system:invoke_kernel`, computa a grade NB+Dixon-Coles com função Numba
`@njit(cache=True)` (fallback NumPy/scipy sem Numba) e publica fair odds em
`fair_odds:{match_id}` (TTL 5s). Hiperparâmetros carregados uma vez no boot.

**Estado real: protótipo funcional (há `scripts/hotpath_smoke.py`), mas:**
- **Duplica a matemática de `model.py`** (grade NB + 4 células DC) em uma
  segunda implementação. A versão JIT clampa células DC negativas a 0 — o
  `model.py` faz `np.clip` equivalente, ok hoje, mas qualquer fix futuro no
  kernel purista precisa ser replicado aqui À MÃO. Risco de drift silencioso.
  Mínimo obrigatório: teste de paridade `_compute_grid_jit == model.predict_match`
  para uma malha de (λa, λb, α, ρ).
- Zero testes na suíte (o smoke é manual).
- Dependências pesadas fora do requirements principal (numba ~500 MB com LLVM,
  redis server) — decisão consciente (`requirements-kernel.txt`), mas amplia a
  superfície operacional.

## 4. `dotnet/LineupWorker` — worker C# (Zona 1/2)

**O que faz (leitura superficial da estrutura):** worker .NET 8 com serviços
`MarketStateEngine`, `MarketOddsCache`, `VorpStateService`, `LatencyAuditService`
— consome eventos de escalação, mantém estado de mercado e invoca o kernel via
Redis (contratos em `Models/KernelContracts.cs`). Compilado (bin/Debug net8.0).

**Estado real:** protótipo compilado, sem testes, dependente do kernel_daemon e
de um artefato VORP que hoje não pode ser gerado (ver §1). **Não auditado em
profundidade** — os ~10 arquivos C# não passaram por revisão linha a linha.

---

## 5. Custo-benefício: a v3 se justifica?

**Não agora.** O argumento em três linhas:

1. **O modelo atual não tem edge** (CLV open −8,7% [−12,4%, −4,4%], cluster
   bootstrap, pipeline corrigido). Latência de serving <15ms não transforma
   um modelo perdedor em vencedor — acelera a chegada de um preço ruim.
2. **A única fonte plausível de edge novo da v3 (VORP/escalações) está
   bloqueada por dados**: treino exige seasons 2021-2022 que o banco não tem,
   e o gate estatístico (survival_test) nunca rodou de verdade.
3. A infra (Redis/Numba/C#) é a parte cara de manter e a parte barata de
   refazer depois. O caminho racional é: **primeiro provar o sinal do VORP em
   batch** (vorp_ridge corrigido + survival_test corrigido, com Elo
   forward-only e DM/HLN), **só então** pagar o custo do hot path.

**Ordem de trabalho recomendada, se a v3 for retomada (pós-Copa):**
1. Coletar seasons históricas (2021-2023) via ingest_sofascore para viabilizar
   o treino do VORP — sem isso, nada anda.
2. Corrigir os 3 defeitos do survival_test (θ, ratings_asof, seasons) e criar
   testes para vorp_ridge/survival_test.
3. Rodar o Go/No-Go honesto. **No-Go → arquivar a v3 sem culpa.**
4. Só com Go: teste de paridade do kernel JIT vs model.py e integração do
   LineupWorker.
