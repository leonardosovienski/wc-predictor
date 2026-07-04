# Arquitetura — wc-predictor-v2

Mapa completo do que o projeto faz e como. CLI em Python que prevê partidas de
seleções e simula a Copa 2026 — 100% local, banco SQLite. Motor:
**Elo → modelo de gols (Binomial Negativa + Dixon-Coles) → previsão / simulação / backtest**.

> Este repositório é um **clone-sombra read-only** da produção. A verdade operacional
> sobre o clone está em [SHADOW.md](SHADOW.md); o handoff detalhado em [HANDOFF.md](HANDOFF.md).

## Fluxo de dados (pipeline inteiro)

```
FONTES                    INGESTÃO              CACHE (batch)          SERVING (instantâneo)
martj42 CSV  ─────────►  ingest.py        ┐
Sofascore    ─────────►  ingest_sofascore ├─► matches/         ┐
FBref        ─────────►  ingest_fbref     ┘   sofascore_*      │
                                              player_stats     │
                                                               ▼
                                              cron_update_models.py
                                              (Elo + calibra params)
                                                     │
                                              current_elo + model_parameters
                                                     │
                        ┌────────────────────────────┼────────────────────────────┐
                        ▼                             ▼                             ▼
                   predict.py                   simulator.py                  backtest.py
                 (1X2/gols/placar)          (Monte Carlo da Copa)         (P&L vs odds / CLV)
                        │                             │                             │
                 predictions.jsonl              ranking campeões            backtest_bets + bootstrap
                 (log obrigatório)
```

## Módulo por módulo — o que faz / como faz

| Módulo | O que faz | Como faz |
|---|---|---|
| `src/ingest.py` | Baixa ~49k jogos internacionais → banco | Download do CSV martj42 (fallback local), normaliza datas/placares, upsert idempotente |
| `src/ingest_sofascore.py` | Coleta placar, xG, **odds 1X2/OU**, nota de jogador | Parseia a API interna do Sofascore; guard `is_pre_match` protege a abertura; snapshots append-only |
| `src/ingest_fbref.py` | Stats agregadas de jogador por competição (xG/xAG/gols) | requests+pandas; "descomenta" tabelas escondidas em HTML |
| `src/sofascore.py` | Cliente HTTP do Sofascore | curl_cffi com impersonate do Chrome (fura Cloudflare); PEM de CAs para proxy corporativo |
| `src/ratings.py` | **Elo** de cada seleção | Forward-only (sem vazamento), janela 6 anos, meia-vida 4 anos, K por competição, multiplicador de goleada. Guarda o diff pré-jogo |
| `src/model.py` | **Motor de gols** — 1X2, over/under, BTTS, placares | Binomial Negativa (overdispersion, Var=μ+αμ²) + Dixon-Coles (ρ, devolve massa de empate). Calibra (a,b,α,ρ) por MLE (scipy L-BFGS-B) |
| `src/math_utils.py` | Limpa a margem das odds | Método de **Shin** (remove overround; corrige favorite-longshot bias melhor que normalização proporcional) |
| `src/cron_update_models.py` | Materializa o cache | Recalcula Elo + calibra params na janela; grava `config_hash`+`n_matches` para detectar staleness. Roda após cada ingestão |
| `src/predict.py` | **Serving da previsão** | Lê o cache; compara vs mercado (Shin) se houver odds; **grava o pacote completo no log** |
| `src/prediction_log.py` | **Registro obrigatório** das predições | Cada previsão → 1 linha JSONL append-only (`data/predictions.jsonl`), congelada no momento em que é feita |
| `src/simulator.py` | **Monte Carlo da Copa** | Deriva 12 grupos do grafo de confrontos, amostra placares da grid corrigida por DC, fatores humanos (Vergonha de Gijón, expulsão); estima P(fase)/P(título) |
| `src/backtest.py` | **Quality gate** — P&L vs odds reais | Aposta de valor `P_modelo>1/odd`, mede ROI e **CLV**; paridade train/serve; ledger `backtest_bets` + telemetria JSONL |
| `src/bootstrap.py` | Significância | Percentile bootstrap 1000× → IC 95% do ROI e do CLV; IC que cruza zero = sem evidência de edge |
| `src/status.py` | Painel do estado do banco | Conta o que cada fonte coletou e o que o modelo usa |
| `src/db.py` | Camada SQLite | Schema + upserts; **trava read-only** (`mode=ro` + `PRAGMA query_only`) do Shadow Deployment |
| `src/net.py` / `src/obs.py` | Infra | Retry com backoff exponencial / logging estruturado (console INFO + arquivo DEBUG) |
| `vendor/predictor_core` | Plataforma compartilhada (vendorizada) | `emit_event` (telemetria JSONL); v2 é o 3º consumidor da plataforma |

## Banco de dados (tabelas principais)

- `matches` — jogos históricos + fixtures futuros (placar NULL = não jogado)
- `sofascore_matches` — odds 1X2/OU (fechamento + `*_open`), xG
- `odds_snapshots` — série temporal append-only de cada coleta de odds
- `player_comp_stats` — stats agregadas de jogador (FBref)
- `sofascore_player_ratings` — nota por jogador por evento
- `current_elo` + `model_parameters` — cache de serving (materializado pelo cron)
- `backtest_bets` — ledger do backtest (P&L, CLV, edge por aposta)

## Saídas

- **Por confronto** (gravado em `data/predictions.jsonl`): gols esperados (λ), 1X2,
  over/under 1.5/2.5/3.5, BTTS (sim/não), 5 placares mais prováveis, params usados,
  e bloco de mercado (Shin + edge) quando há odds.
- **Torneio:** ranking Elo + P(avançar / quartas / semi / final / título).
- **Backtest:** ROI, CLV por população (open/close), calibração por faixa de edge, IC 95%.

## O que o sistema NÃO faz (limites atuais)

- **Não prevê escanteio, cartão, chute, falta, posse nem artilheiro.** O motor é
  **só de gol**: o dataset martj42 traz apenas placar, e não existe modelo desses
  mercados. Ampliar exige (1) ingerir o histórico via Sofascore *statistics* e
  (2) um modelo por mercado (Poisson/BN de escanteios, cartões, etc.).
- **Backtest ainda não rodou com dados reais úteis** — a coleta de odds do Sofascore
  exige rede limpa (o proxy corporativo dá 403); validado só em sandbox com odds sintéticas.
- **Simulador precisa das 48 fixtures da Copa** (12 grupos) no banco para rodar.

## Como rodar

```
python -m src.ingest                 # baixa o dataset → banco
python -m src.cron_update_models     # calcula Elo + calibra params (rodar após cada ingest)
python -m src.predict Brazil Norway --neutral   # prevê um confronto (e grava no log)
python -m src.predict --fixtures 9   # prevê os próximos N fixtures
python -m src.predict --rankings 15  # top N do Elo
python -m src.simulator 10000        # Monte Carlo da Copa
python -m src.ingest_sofascore       # coleta odds (rede limpa)
python -m src.backtest               # quality gate (P&L vs odds)
python -m src.bootstrap              # IC 95% do ROI e do CLV
pytest tests/ -q                     # suíte (84 testes)
```
