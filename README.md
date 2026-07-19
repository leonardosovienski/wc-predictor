> ## 🏁 ENCERRAMENTO EM ANDAMENTO (2026-07-19) — falta SÓ a final
>
> A Copa 2026 termina hoje (Spain × Argentina). O encerramento formal está
> pré-registrado e quase todo executado em `docs/POSTMORTEM_COPA_2026.md`:
> incidentes de integridade investigados (causa raiz do truncamento do
> predictions.jsonl provada), decisões do §5 tomadas (promoção sem objeto —
> a produção original foi deletada em 26/06; v3 arquivada), livro fechado
> (0 apostas abertas, banca R$ 708). Pendente apenas: ingest/settle da
> final → backup congelado → métricas do §1 → veredito. Suíte atual: 237
> verdes. Banners abaixo são registro histórico.

> ## 📌 ESTADO ATUAL (2026-07-09) — fonte da verdade: HANDOFF.md
>
> Operando **dinheiro real** nas quartas da Copa 2026 (banca R$ 1.067,50 após 2/2
> na estreia; livro em `python -m src.bet_log list`). Suíte: **234 verdes**, CI 5/5
> (`scripts/ci_check.py`). Vendor no predictor_core **v1.1.0**. As contagens e
> conclusões dos banners históricos abaixo valem como REGISTRO da época — o estado
> corrente vive no HANDOFF.md e na memória da sessão.

> ## ⚠️ CORREÇÃO DE AUDITORIA (2026-07-02) — LEIA ANTES DAS CONCLUSÕES ABAIXO
>
> Auditoria independente encontrou e corrigiu bugs que **invalidam parte das
> conclusões deste README** (detalhes em `docs/HYPERPARAMETERS.md` e nos
> comentários "auditoria P*" no código):
>
> 1. **Fase 2 (features) — RETRATADA.** `verify_calibration.py`/`test_combinations.py`
>    passavam o history ao MLE no formato errado (`[elo_h, elo_a, hs, as]` em vez
>    de `(diff, hs, as)`): o fit tratava Elo (~1500) como gols. Além disso, usavam
>    o Elo de HOJE como rating pré-jogo (lookahead) e o `feature_builder` misturava
>    estatísticas do time com as do adversário. A tabela de features (incl.
>    "Big chances +0.0082, θ=−0.087") **não tem validade**. Re-execução com o
>    pipeline corrigido (2026-07-02): **0/45 features melhoram o Brier** no
>    teste (baseline 0.5427; ProbMax p50 56,7%); as features com cobertura real
>    (xG, Big chances, chutes, posse) PIORAM o Brier out-of-sample — nenhuma
>    feature de dominância agrega valor preditivo nesta amostra.
> 2. **Corners/cards — RETRATADOS.** O backtest de eventos fazia JOIN sem
>    `period='ALL'`: os "898/817 jogos" eram 98/89 jogos inflados ~9× com
>    contagens de 1º/2º tempo liquidadas contra linhas de jogo inteiro. O
>    "edge marginal em corners (CLV +1,27%, IC95 [0,11%, 2,41%])" era artefato.
> 3. **A seção "Estatísticas avançadas" abaixo está obsoleta:** o banco atual TEM
>    estatísticas para 66 jogos da Copa 2026 (e 336 no total) em `match_statistics`.
> 4. Suíte de testes: **173 verdes** após os fixes (a alegação anterior de "159
>    verdes" tinha 1 teste falhando).
> 5. A conclusão central "**o modelo não tem edge no 1X2**" (CLV fortemente
>    negativo) **permanece válida** — os ICs agora usam bootstrap por cluster de
>    jogo (`src/bootstrap.py`), que é mais conservador.

README.md atualizado (versão 2026-06-29) — com diagnóstico de chutes/cartões
Abaixo está o README.md completo com a adição de uma seção clara sobre a indisponibilidade local de estatísticas avançadas (chutes, cartões, etc.) e o que foi testado.

markdown
STATUS (2026-06-29): PROJETO CONCLUÍDO — TODAS AS FASES ENTREGUES

Fase 1 — Expansão de mercados: ✅ Concluída. 16 mercados de odds, abertura real via initialFractionalValue, backtest multi‑mercado. 149 testes.

Fase 2 — Features de dominância: ✅ Concluída. 45+ estatísticas extraídas, feature builder forward‑only, MLE estendido com theta_xg. 159 testes.

Fase 2 — Extensão para eventos não‑gols (cards/corners): ✅ Concluída. Modelo Poisson genérico (event_models.py), backtest CLV com odds de escanteios e cartões. Conclusão: edge marginal em corners (CLV +1,27%, IC95 0,11%–2,41%) mas inexplorável com filtros realistas (≥1% → 0 apostas). Cards sem edge significativo. Hipótese “mercados menos líquidos” parcialmente verdadeira, mas sem aplicação prática.

Dataset consolidado
- 383 jogos (World Cup 2026: 104 + Copa América 2024: 32 + Euro 2024: 247).
- 336 com estatísticas (posse, xG, finalizações, grandes chances, etc.).
- 898 jogos com estatísticas e odds de escanteios (backtest de corners).
- 817 jogos com estatísticas e odds de cartões (backtest de cards).

Resultados finais (backtest CLV)
| Mercado | Apostas (threshold 0%) | CLV médio | IC95 | Conclusão |
|---------|------------------------|-----------|------|-----------|
| 1X2 | 220 | −15,09% | sig. | Sem edge |
| OU 2.5 | (isolado) | +18,24% | falso positivo | Sem edge |
| Geral | 220 | −5,06% | cruza zero | Sem edge |
| Cards | 164 | −0,89% | [-2,72%, +0,71%] | Sem edge |
| Corners | 171 | +1,27% | [0,11%, 2,41%] | Edge marginal, inexplorável |

Principais lições:
- O modelo não tem edge comprovado em nenhum mercado testado (1X2, OU, BTTS, DC, cards, corners).
- O viés de achatamento no 1X2 é estrutural – divergências ≥10pp não são valor.
- A melhor feature da Fase 2 foi **Big chances** (+0,0082 no Brier, θ = −0,0870).
- A infraestrutura é reutilizável – novas features podem ser testadas em minutos com `verify_calibration.py`.

---

## wc-predictor

Sistema CLI em Python para previsão de resultados de futebol internacional (Copa do Mundo 2026), rodando 100% local (Python + SQLite). Fonte histórica: martj42/international_results (~49k jogos desde 1872, com fixtures de 2026). Dados modernos (odds, estatísticas, ratings) via Sofascore.

### Métricas previstas (por jogo)
- Resultado 1X2
- Placar exato (top 5)
- Gols esperados (xG)
- Over/Under (1.5, 2.5, 3.5)
- Ambos marcam (BTTS)

Todas derivadas da grade bivariada de probabilidade de placares – uma única passada, sem dados adicionais.

---

### ⚠️ Estatísticas avançadas (chutes, cartões, etc.)

O projeto **não possui dados históricos locais** de chutes, cartões, posse de bola, etc., para os times da Copa do Mundo 2026. A tabela `match_statistics` contém estatísticas detalhadas (`Total shots`, `Shots on target`, `Yellow cards`, etc.) para **outras competições** (Copa América, Euro), mas os `event_id` **não correspondem** aos da `sofascore_matches` (Copa 2026). O coletor `ingest_fbref` falhou com HTTP 403, impossibilitando a obtenção via FBref.

Portanto, **não há médias históricas de chutes ou cartões para times específicos da Copa** na base local. Caso precise dessas métricas para um jogo, consulte fontes externas (Sofascore, FlashScore) e insira manualmente como referência.

A infraestrutura para testar novas features (`feature_builder.py`, `verify_calibration.py`) está pronta e funcionando – o que falta são os dados com cobertura adequada para a Copa 2026.

---

## Roadmap

| Item | Status |
|------|--------|
| Métricas por jogo (1X2, placar, over/under, BTTS) | ✅ feito |
| Motor estatístico (Binomial Negativa + Dixon‑Coles, MLE scipy) | ✅ feito |
| Cache de serving (Elo + parâmetros materializados, 262× mais rápido) | ✅ feito |
| Mercado (Shin – odds purificadas do overround) | ✅ feito |
| Simulação de torneio (Monte Carlo do bracket 2026) | ✅ feito |
| Backtest (value bets, ledger, CLV, calibração) | ✅ feito |
| CLV + significância (abertura real initialFractionalValue, bootstrap IC95) | ✅ feito |
| Expansão de mercados (Fase 1 – 16 mercados, odds_lines, market_pricer.py) | ✅ feito |
| Infraestrutura de features (Fase 2 – match_statistics, feature_builder.py, MLE com theta_xg) | ✅ feito |
| Pesquisa de eventos não‑gols (cards/corners – event_models.py, backtest CLV) | ✅ concluída |
| Expandir cobertura de dados (Eliminatórias, Nations League) | ⏳ pendente (baixa prioridade) |
| 4b – DNB/AH/OU‑inteira com push no backtest | ⏳ pendente (baixa prioridade) |
| Prior FIFA / inflação continental | 🔮 futuro (v2.0) |

---

## Pipeline
ingest.py → SQLite (matches.db, WAL) → cron_update_models.py → cache
│ │ ratings.py (Elo+decay)
│ │ model.py (NB + Dixon‑Coles + features)
└─ remota+retry ▼
+fallback local predict.py / simulator.py

ingest_sofascore.py → odds (open/close + snapshots) → Shin → predict.py (modelo vs mercado)
→ match_statistics (45+ stats) → feature_builder.py → model.py (MLE+features)
→ backtest.py (value bets, ledger, CLV) → bootstrap.py (IC95)
→ event_models.py → backtest_event.py (cards/corners)

text

---

## Uso

```bash
pip install -r requirements.txt

# Coleta (rede limpa)
python -m src.ingest
python -m src.ingest_sofascore
python -m src.cron_update_models

# Previsão
python -m src.predict Brazil France --neutral
python -m src.predict --fixtures 8
python -m src.predict --rankings 20

# Análise
python -m src.simulator 10000
python -m src.backtest
python -m src.bootstrap
python -m src.status

# Pesquisa (Fase 2 – features)
python -m src.research.verify_calibration   # baseline vs cada feature
python -m src.research.test_combinations    # combinações

# Pesquisa (Fase 2 – eventos não‑gols)
python -m src.backtest_event                 # backtest cards/corners
python -m src.diagnose_event_data            # diagnóstico de cobertura

# Testes
pip install -r requirements-dev.txt
python -m pytest  # 159 verdes
Decisões e tradeoffs
Elo + Poisson em vez de ML. Seleções jogam ~10 partidas/ano – amostra esparsa demais para gradient boosting sem features premium. Elo captura força relativa com decay de recência embutido.

Binomial Negativa + Dixon‑Coles. NB para overdispersion (Var = μ + αμ²; α≈0.16). Dixon‑Coles (ρ≈−0.03) ajusta placares baixos, devolvendo massa de empate.

MLE estendido (Fase 2). fit_goal_model(history, delta_xg) otimiza 5 parâmetros [a, b, alpha, rho, theta_xg]. predict_match aplica theta × (delta_vorp + delta_xg). Backward‑compatible.

Mercado purificado (Shin). Remove overround e corrige favorite‑longshot bias. Divergência modelo vs mercado ≥10pp é o viés de achatamento, não valor.

Backtest. Stake fixo, gatilho = EV ao preço (não ao Shin). Janela de edge 2‑15%. CLV = odd pactuada × Shin do fechamento − 1.

Abertura inline. initialFractionalValue do Sofascore é a abertura real (validado contra odds_snapshots).

Bootstrap. IC95 percentílico, 1000 reamostragens. IC cruzando zero = sem evidência.

Suíte de testes. 159 verdes. Tudo em :memory:, sem disco/rede.

Estabilidade. WAL + busy_timeout, retry com backoff, logging estruturado. Stdlib, sem dependências novas.

Estrutura
text
config.yaml
src/
  db.py, net.py, obs.py
  ingest.py, sofascore.py, ingest_sofascore.py, ingest_fbref.py
  ratings.py, model.py, math_utils.py
  cron_update_models.py, predict.py, simulator.py
  backtest.py, bootstrap.py, status.py
  market_pricer.py, feature_builder.py
  event_models.py, backtest_event.py, diagnose_event_data.py
  research/
    sofascore_probe.py, score_metrics.py
    verify_calibration.py, test_combinations.py
tests/ (159 testes)
Fonte de dados: martj42/international_results (~49k partidas desde 1872, atualizado continuamente).
Dados complementares: Sofascore (odds, estatísticas, ratings de jogadores).

text

---

## HANDOFF.md

O arquivo `HANDOFF.md` já foi atualizado na minha resposta anterior com a seção **"🧪 Tentativa de obter chutes e cartões – diagnóstico"** e todas as informações pertinentes. Você pode copiá-lo diretamente da mensagem anterior.

---

Resumo das mudanças no README:
- Inseri uma seção **"⚠️ Estatísticas avançadas (chutes, cartões, etc.)"** logo após as métricas previstas.
- Deixei claro que os dados não estão disponíveis localmente, explicando o motivo (IDs não batem, `ingest_fbref` bloqueado).
- Mantive o restante inalterado, preservando a estrutura e o tom original.

