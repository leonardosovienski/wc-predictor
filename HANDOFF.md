> ## 🏁 STATUS: ENCERRADO (2026-07-19) — Copa 2026 completa, veredito emitido
>
> **Projeto formalmente encerrado.** A final (Spain 0-0 Argentina em 90min;
> Espanha campeã 1-0 na prorrogação) foi aferida (2/4), o banco foi
> congelado (`data/matches_copa2026_frozen_20260719.db`) e as métricas
> pré-registradas foram preenchidas com veredito final — ver
> `docs/POSTMORTEM_COPA_2026.md` (documento definitivo do encerramento).
> Síntese: o mercado vence no agregado (CLV −8,4% sig.); exceção comprovada
> OU2,5 (CLV +16,9% sig.), herdada pelo brasileirao-predictor; P&L real
> −5,84u, todo o prejuízo fora do funil validado. Legado inventariado no
> §7 do POSTMORTEM. O repo permanece PARKED como registro histórico —
> vendor congelado, nenhuma evolução funcional; GitHub: `wc-predictor`
> (privado). Bloco de encerramento-em-andamento abaixo é registro da época.

> ## STATUS: PARKED — ENCERRAMENTO EM ANDAMENTO (2026-07-19, falta só a final)
>
> Decisão humana explícita do operador (19/07): encerrar o projeto. Tudo que
> não depende da final já foi executado — ver `docs/POSTMORTEM_COPA_2026.md`:
> §4 fechado (causa raiz do truncamento provada por forense; ferramentas de
> relatório verificadas), §5 decidido (promoção SEM OBJETO — produção
> original deletada em 26/06, na Lixeira; v3 arquivada; reconciliações
> canceladas; H6 transferida como conhecimento ao brasileirão), 3º lugar
> aferido (France 4-6 England, 0/4), previsões dos 2 últimos jogos congeladas
> no ledger. Pendentes: resultado da final → checklist §0 (ingest, settle,
> backup congelado, selo) → métricas §1 → veredito final. Única outra decisão
> humana aberta: restaurar ou não a produção deletada da Lixeira. O bloco
> PARKED abaixo permanece válido (vendor congelado, sem evolução funcional —
> encerramento é settle+docs, não código).

> ## STATUS: PARKED (verificado 2026-07-18)
>
> Congelado. Vendor de `predictor_core` intencionalmente desatualizado
> (agregado `3445e37f43c458cc`, drift esperado e correto contra o
> canônico atual — `sync_core.py --check` confirma). **Proibido**: sync de
> vendor, atualização automática, migração, adaptação, evolução funcional.
> Consulta histórica é permitida. Motivo factual do congelamento: encerramento
> operacional da Copa (dado real-money irreproduzível). Um sync indevido
> ocorreu por engano em 2026-07-17 (`PARKED` vazio em `sync_core.py` por
> período) e foi revertido via `git revert` (commit `5efb129`) — nunca
> publicado. Condição formal para reabrir: decisão humana explícita
> documentando o motivo, seguida de `sync_core.py --write --target
> wc-predictor-v2` só depois de remover o nome de `PARKED`. Ver
> `ECOSYSTEM_HANDOFF.md` para o mapa completo do ecossistema.

> ## 🎫 SPAIN×BELGIUM LIQUIDADO + REVALIDAÇÃO COMPLETA + BETMGM (2026-07-10)
>
> **Revalidação comando-a-comando (manhã)**: checklist de 9 itens executado de
> verdade — CI 234/5-5 (3 WARNs conhecidos), higiene 6/6 (core v1.1.0), serving
> (1X2 soma 100%, live 1T/2T ok), livro-caixa exercitado em arquivos TEMP via env
> vars (todas as rejeições, late=True, duplicata, push em linha inteira via API,
> BETLOG_MAX_INFO_STAKE), painel real batendo ao centavo, odds via --from-file
> (nunca filtra frescor), aferição com orientação invertida ok, backtest regrava
> ledger. Zero chamada de API gasta na validação. **Veredito: apto às semis.**
> Nota: `sync_core --check` NÃO existe neste repo (mora no core upstream); o
> equivalente local é test_core_integrity.
>
> **FATO NOVO — casa real do operador é a BetMGM** (memória gravada): o line
> shopping é só referência; a odd REGISTRADA tem que ser a executada na BetMGM.
> As 4 apostas das quartas tinham sido registradas com odds de casas que o Leo
> não usa (Coolbet/BetOnline/NordicBet) — a de hoje foi corrigida no livro; as
> DUAS ABERTAS (Norway-England @2.21 "BetOnline", Argentina-Switzerland @2.30
> "NordicBet") ainda precisam da MESMA correção quando ele executar na BetMGM —
> perguntar odd real ANTES do apito.
>
> **Spain 2x1 Belgium (HT 1-1) liquidado**: Under 2.5 FT @2.15 BetMGM PERDEU
> (−1u, mas **CLV +1.53%** — processo certo, variância) + Under 1.5 1T @1.40
> BetMGM 0.5u PERDEU (−0.5u; pick ≥60%, modelo 74.8%). Dia: **−R$ 75**. Banca:
> **R$ 992,50** (−0.15u total, 4 fechadas, 2u em jogo). Aferição: 10 jogos,
> winner 6/10, ou25 4/10. Fechamento capturado pré-jogo via ingest_sofascore
> 15h08 BRT (Under @2.00, pre_match=1). Quota Odds API: 412 restantes.
>
> **Pendências pra próxima sessão**: (1) W2 bet_id de manhã entre jogos;
> (2) cron_update_models quando o 2x1 entrar em matches (antes das SEMIS —
> placeholder France×W98 14/07 já está no banco, W98 = Spain);
> (3) Norway×England 11/07 18h00 BRT: ingest_sofascore perto do apito, conferir
> odd BetMGM, corrigir livro com a odd real, settle duplo pós-jogo;
> (4) expectativa honesta dada ao operador: ~7 bilhetes restantes na Copa,
> EV ~R$ 20-40 — volume real só pós-Copa com mais ligas (backtest + registry).

> ## 💰 QUARTAS COM DINHEIRO REAL + AUDITORIA CRUZADA (2026-07-08/09)
>
> **Banca real aberta (def4c4a, 08/07)**: R$ 1.000, unidade R$ 50 (5% — acima do
> teto conservador de 2%, escolha consciente do operador; o painel avisa sempre).
> `python -m src.bet_log banca` / `list` / `settle` / `summary`. Livro append-only
> (`data/bets.jsonl` + `bankroll.jsonl`) com carimbo de aposta tardia, alerta de
> duplicata, HT>FT rejeitado, stake/placar negativos rejeitados (teste de fogo 08/07).
>
> **Primeira rodada liquidada (09/07)**: France 2x0 Morocco (HT 0-0) → **2/2 GANHAS,
> +R$ 67,50** (Under 2.5 @1.93 +0.93u, CLV −3,5%; Under 1.5 1T @1.42 +0.42u,
> informativa). Banca R$ 1.067,50; 3 apostas vivas (Spain-Belgium, Norway-England,
> Argentina-Switzerland). Regra inegociável: só O/U 2.5 tem CLV comprovado
> (+16,11% na população open); períodos = informativos com prob ≥60%; 1X2 nunca.
>
> **Auditoria cruzada (09/07, commits f413eec→6a14406)**: (1) bug do `data/`
> não-ancorado no .gitignore estava VIVO — engolia `vendor/predictor_core/data/`
> (7 .py do manifesto; clone fresco quebraria); corrigido + `test_repo_hygiene.py`
> portado do previsao-cripto. (2) W1: `_market_probs` casava odds só por nomes e a
> base tem confrontos repetidos (Argentina×Canada 2024/2026) — o CLV do settle podia
> usar o jogo errado; agora filtra por data ±3d (settle passa match_date/kickoff).
> (3) W5: odds_shop descarta casa com `last_update` >15min (feed morto = melhor
> preço fantasma; `--max-stale-min`). (4) W3/W6/W7: timestamps como datetime,
> barreira P3 varre scripts/ (diag_zebra virou dívida WARN), CLV loga causa de
> falha. (5) Trava opt-in `BETLOG_MAX_INFO_STAKE` (env var) limita stake de mercado
> sem CLV. **Suíte: 234 verdes, CI 5/5.**
>
> **Vendor no core v1.1.0** (registry com governança N+1 + trava de poder +
> `PredictionPoint`): nada consumido ainda — a adoção do TrialRegistry + harness
> (edge sintético: inflar λ e exigir detecção no funil O/U) é o passo OBRIGATÓRIO
> antes da melhoria do 2T condicionado ao HT (pós-Copa). Pendências: W2 (bet_id
> uuid no livro — schema aditivo, fazer entre jogos), `cron_update_models` quando
> o placar das quartas entrar em `matches` (antes das SEMIS).

> ## 🔗 ONDA 5 (2026-07-03) — reintegração ao predictor_core (DESPARKADO)
>
> O wc-predictor-v2 agora **consome o predictor_core via vendor** (`vendor/predictor_core/`,
> 32 arquivos; `tests/test_core_integrity.py` protege contra drift). Foi desparkado porque a
> **coleta** (`ingest`→`matches.db`) é independente da **análise**: criar o vendor é aditivo
> e não toca o SQLite congelado nem o config pré-registrado.
>
> **Removidos** (scratch mortos, importados por nada — NÃO eram duplicatas do core):
> `stats.py`, `stats_corrigido.py`, `stats_final.py` (diagnósticos one-off de chutes/cartões).
>
> **NÃO migrados de propósito** (honestidade de engenharia): `src/bootstrap.py` (CLI numpy
> nos comandos do playbook pré-registrado; RNG numpy ≠ stdlib do core → golden bit-a-bit
> impossível, mudaria o IC de CLV pré-registrado mid-torneio) e `src/research/score_metrics.py`
> (métricas de tensores de placar N×G×G, ontologia de futebol, usado por `survival_test.py`).
> Ambos **congelados até o post-mortem** (mandato do `docs/COPA_2026_PLAYBOOK.md`), a
> reconciliar então com o core por validação de TOLERÂNCIA (não bit-a-bit — a RNG difere).
>
> Suíte: **177 verdes** (173 + 4 de integridade). `sync_core --check`: 3/3 OK, sem PARKED.

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
🔍 Resultados finais (backtest CLV)
Mercado	Apostas (threshold 0%)	CLV médio	IC95	Conclusão
1X2	220	−15,09%	sig.	Sem edge
OU 2.5 (isolado)	+18,24%	falso positivo	Sem edge	
Geral	220	−5,06%	cruza zero	Sem edge
Cards	164	−0,89%	[-2,72%, +0,71%]	Sem edge
Corners	171	+1,27%	[0,11%, 2,41%]	Edge marginal, inexplorável
Principais lições:

O modelo não tem edge comprovado em nenhum mercado testado.

O viés de achatamento no 1X2 é estrutural – divergências ≥10pp não são valor.

A melhor feature da Fase 2 foi Big chances (+0,0082 no Brier, θ = −0,0870).

A infraestrutura é reutilizável – novas features podem ser testadas em minutos.

📦 Dependências
Listadas em requirements.txt (padrão, sem dependências pesadas). Use Python 3.10+.

text

---

## HANDOFF.md atualizado

Adicionei ao final a seção "Tentativa de obter chutes/cartões – diagnóstico" para deixar claro o que foi tentado e o resultado.

```markdown
# HANDOFF.md — wc-predictor-v2

> ## ⚠️ ADENDO DE AUDITORIA (2026-07-02)
> Bugs corrigidos que invalidam parte deste documento — ver banner no README.md:
> **(a)** a tabela de features da Fase 2 e a conclusão "Big chances é a melhor
> feature" estão RETRATADAS (history no formato errado no MLE + Elo com lookahead
> + feature_builder misturando os dois times) — re-execução corrigida: **0/45
> features melhoram o Brier** (baseline 0.5427); **(b)** o backtest de corners/cards
> e o "edge marginal +1,27%" estão RETRATADOS (JOIN sem period='ALL' inflava a
> amostra ~9× com dados de 1º/2º tempo — os "898/817 jogos" eram 98/89);
> **(c)** há SIM estatísticas locais para 66 jogos da Copa 2026 na
> `match_statistics` (a seção "não há dados locais" ficou obsoleta);
> **(d)** suíte agora com 173 testes verdes; bootstrap por cluster de jogo;
> warnings de convergência no MLE. A conclusão "sem edge no 1X2" permanece.

Documento para retomar o desenvolvimento em um chat novo. Anexe o wc-predictor.zip junto com este arquivo.

---

## O que é o projeto
Sistema CLI em Python que prevê resultados da Copa do Mundo 2026. Roda 100% local (Python + SQLite, sem cloud). Idioma do projeto: português. Fonte de resultados: martj42/international_results (~49k jogos desde 1872, inclui os fixtures de 2026).

Máquina do Leo: Windows, em C:\Claude-projetos\Claude\wc-predictor-v2, com venv .venv, atrás de proxy corporativo Volvo com inspeção TLS (resolvido no código). O sandbox do Claude alcança só GitHub/PyPI — não alcança Sofascore/FBref, então a coleta dessas fontes só roda na máquina do Leo.

---

## Tom e regras de trabalho
Direto, técnico, sem preâmbulo. Nomear tradeoffs e deixar a decisão com o Leo.

Honestidade de engenharia acima de tudo: nunca documentar como "feito" o que é plano; apontar quando a doc descreve algo que o código não faz.

Pipeline como código, versionado. Sem governance debt. Idempotência por padrão. Segredos em env/secret manager, nunca hardcoded. Observabilidade desde o início.

Arquitetura antes de implementação. Explicar o porquê das decisões.

Quando o Leo manda um documento de "próximos passos", o padrão é: ler, separar o que é sólido do que é otimização prematura, propor a sequência por leverage/risco (não pela ordem do documento), e implementar só após o sinal verde.

---

## 📊 VEREDITO FINAL (2026-06-29) — PROJETO CONCLUÍDO

### Fase 1 — Expansão de mercados
**Status:** ✅ Concluída. 149 testes.

- `market_pricer.py` — precifica DC, BTTS, OU multi-linha, handicap asiático (split de quarto), placar exato, a partir da grade que `model.predict_match` já expõe.
- `ingest_sofascore.parse_all_odds` — extrai 16 mercados do payload (1X2, DC, DNB, BTTS, OU 0.5–9.5, AH).
- Schema: tabela `odds_lines` (OU+AH, linha variável) + colunas flat (DC/DNB/BTTS) + migração aditiva.
- `backtest.py` estendido: aposta BTTS, DC, OU meia-linha (sem push). DNB/AH/OU-inteira (com push) = não implementado.
- `initialFractionalValue` → população open real — a odd de abertura vem inline no payload. Régua validada: cruzamento com `odds_snapshots` confirmou que `initialFractionalValue` é a abertura real. Open-CLV é legítimo, não tautológico.
- **Open-CLV — 220 apostas**

| Mercado | open-CLV | Veredito |
|---------|----------|----------|
| 1X2 | −15.09% (sig) | Modelo perde |
| OU 2.5 | +18.24% (sig isolado) | Falso positivo (teste múltiplo) |
| OU 1.5 | −13.59% (sig) | Vizinho perde |
| OU 0.5 | −36.90% (sig) | Vizinho perde feio |
| OU baixos (pool) | −1.21% (inconclusivo) | Diluiu |
| **GERAL** | **−5.06% (inconclusivo)** | **Sem edge comprovado** |

---

### Fase 2 — Features de dominância
**Status:** ✅ Infraestrutura concluída. 159 testes.

- Tabela `match_statistics` (EAV) — 45+ estatísticas do Sofascore por evento, time e período.
- Parser `parse_statistics` — extrai todas as estatísticas do `event_statistics`.
- `feature_builder.py` — médias móveis forward-only de qualquer estatística por time.
- MLE estendido — `fit_goal_model` e `predict_match` aceitam `delta_xg` via parâmetro `theta_xg`.
- Scripts: `verify_calibration.py` (testa as 45 features individualmente) e `test_combinations.py` (combinações). **Não existe `test_all_features.py`** — essa função É o `verify_calibration.py`.
- **Resultado** (336 jogos COM estatísticas, 268 treino / 68 teste). Base: 383 jogos — World Cup 2026 (104) + Copa América 2024 (32) + Euro 2024 (247, o rótulo inclui a qualificação). A Euro **entrou** na base e nos 336 (foi a maior fonte de stats); ela domina a tabela de calibração abaixo:

| Feature | theta | Melhora Brier | ProbMax p50 | ProbMax max |
|---------|-------|---------------|-------------|-------------|
| Baseline (só Elo) | — | 0.5176 | 59.83% | 89.82% |
| Big chances | -0.0870 | +0.0082 | 57.92% | 90.11% |
| Shots inside box | -0.0097 | +0.0016 | 58.98% | 89.85% |
| Expected goals | -0.0493 | +0.0012 | 59.42% | 89.87% |
| Shots on target | -0.0094 | +0.0010 | 59.54% | 89.84% |
| Touches in penalty area | -0.0029 | +0.0007 | 58.94% | 89.83% |
| Total shots | -0.0042 | +0.0007 | 59.23% | 89.83% |

**Conclusões:**
- **Big chances** é a melhor feature — +0.0082 no Brier, θ = -0.0870.
- O achatamento **NÃO** se confirma na base completa — ProbMax baseline: 59.83% (p50), 89.82% (max). Próximo do mercado (57-85%). O diagnóstico inicial (42-46%) foi distorcido pela amostra pequena de 66 jogos.
- Features de dominância ajudam marginalmente — +0.0082 no Brier. O Elo já captura a maior parte da informação preditiva.
- 41/45 features não têm sinal — a maioria não varia entre times ou tem cobertura insuficiente.

**Lições registradas:**
- Pré-checagem: sempre medir cobertura na tabela que a feature consome (`match_statistics`), não na base de resultados (`matches`).
- Amostra importa: 66 jogos da Copa não são representativos. Com 336 jogos, o diagnóstico muda completamente.

**Consequências:**
- O modelo **não tem edge comprovado** — open-CLV geral -5.06%, IC cruza zero.
- **Big chances** é a feature a usar se for expandir o modelo.
- Infraestrutura reutilizável — qualquer feature nova pode ser testada em minutos.
- Uso legítimo: referência de probabilidade de-vigada do mercado (Shin) e sanity-check.

---

### Fase 2 — Extensão para eventos não‑gols (cards/corners)
**Status:** ✅ Concluída. Pesquisa realizada, resultados documentados.

- `src/event_models.py` — modelo Poisson genérico (com suporte a NB) para eventos contábeis (escanteios, cartões). Funções `fit_event_model` e `predict_event`.
- `src/backtest_event.py` — backtest CLV para mercados de cards e corners usando `odds_lines` e `match_statistics`.
- `src/diagnose_event_data.py` — diagnóstico de cobertura cruzada entre odds e estatísticas.
- Correção em `ingest_sofascore.py` e `db.py` para capturar `marketId` 20 (cards) e 21 (corners) e popular `odds_lines`.

**Dados utilizados:**
- Corners: 898 jogos com estatística `Corner kicks` e odds de escanteios.
- Cards: 817 jogos com estatística `Yellow cards` e odds de cartões.
- Divisão treino/teste: 80/20 por data.

**Resultados (backtest CLV com threshold 0% — forçando todas as apostas):**

| Mercado | Apostas | CLV médio | IC95 | Conclusão |
|---------|---------|-----------|------|-----------|
| Corners | 171 | +1.27% | [0.11%, 2.41%] | Edge marginal, estatisticamente significativo |
| Cards | 164 | -0.89% | [-2.72%, 0.71%] | Sem edge (IC cruza zero) |

**Teste com thresholds realistas (min_edge ≥ 1% ou ≥ 2%):**
- Com `min_edge=0.01` (1%) → 0 apostas para corners.
- Com `min_edge=0.02` (2%) → 0 apostas para corners.

**Interpretação:**
- O modelo tem poder preditivo marginal para escanteios — o CLV positivo e significativo indica que o modelo captura informação que o mercado não precifica completamente.
- Porém, o edge é muito pequeno (concentrado entre 0% e 1%) — não é explorável com filtros realistas, pois o overround e os custos de transação consomem essa margem.
- Conclusão prática: a hipótese "mercados menos líquidos são menos eficientes" é parcialmente verdadeira (há sinal em corners), mas não justifica integração no sistema de apostas ou no pipeline principal.

---

### 🧪 Tentativa de obter chutes e cartões – diagnóstico (29/06/2026)

Durante a interação, tentamos extrair médias de chutes e cartões para Alemanha e Paraguai a partir da tabela `match_statistics`. Constatamos:

- A tabela `match_statistics` contém estatísticas detalhadas (`Total shots`, `Shots on target`, `Yellow cards`, etc.) para **outras competições** (Copa América, Euro), mas os `event_id` **não correspondem** aos da `sofascore_matches` (Copa do Mundo 2026).
- O coletor `ingest_fbref` falhou com HTTP 403, impossibilitando a obtenção via FBref.
- Portanto, **não há dados locais** de chutes/cartões para os jogos da Copa 2026.

**Conclusão:** O projeto não oferece médias históricas de chutes ou cartões para times específicos da Copa. Caso o usuário queira essas métricas para um jogo, deve consultar fontes externas (Sofascore, FlashScore) e inserir manualmente como referência.

---

## Estado atual: o que ESTÁ feito e validado

### Coleta
- `ingest.py` — resultados do martj42 (GitHub CSV), idempotente, com retry e fallback local. ~49.398 jogos + 72 fixtures de 2026.
- `sofascore.py` + `ingest_sofascore.py` — cliente curl_cffi. Coleta placar, xG, odds, estatísticas (45+), notas de jogador.
- `ingest_fbref.py` — coletor secundário de stats agregadas de jogador (atualmente bloqueado).

### Motor estatístico (`model.py`, `ratings.py`)
- Elo com decay (half-life 4 anos) + corte de janela (6 anos), home advantage +100, forward-only.
- Binomial Negativa (overdispersion) + Dixon-Coles (empates), calibração MLE via scipy.
- `predict_match` expõe grade bivariada completa (grid).
- MLE estendido: `fit_goal_model(history, delta_xg)` otimiza 5 parâmetros [a, b, alpha, rho, theta_xg].

### Cache de serving (`cron_update_models.py`)
- Elo + params materializados. 257ms → 1ms (262×).
- Carimbo de `config_hash` + `n_matches` detecta staleness.

### Mercado (`math_utils.py`)
- Método de Shin: remove overround, corrige favorite‑longshot bias.
- `predict.py` compara modelo vs mercado purificado.

### Simulador (`simulator.py`)
- Monte Carlo do bracket 2026. Grupos derivados do grafo de confrontos (sem hardcode).
- Fatores contextuais: incentivo (Gijón), expulsão (taxa‑base).
- ~3000 sims/1.8s.

### Backtest / Quality Gate (`backtest.py`)
- Passada forward do Elo (sem lookahead), stake fixo.
- Gatilho: P_modelo > 1/odd (EV ao preço).
- Janela de edge `min_edge`/`max_edge` (2%/15%).
- Múltiplos mercados: 1X2, OU 2.5, BTTS, DC, OU multi-linha meia.
- CLV = odd pactuada × Shin do fechamento − 1.

### Abertura/Fechamento + CLV
- `odds_*` = fechamento (última leitura sobrescreve); `*_open` = abertura (write‑once via COALESCE).
- `odds_snapshots` append‑only (série temporal).
- `initialFractionalValue` — abertura inline da casa, população open real.
- `bootstrap.py` — IC 95% percentílico, 1000 reamostragens.

### Market Pricer (`market_pricer.py`)
- DC, BTTS, OU multi-linha, AH (split de quarto), placar exato — funções puras sobre a grade.

### Feature Builder (`feature_builder.py`)
- Médias móveis forward-only de qualquer estatística por time.
- Features padrão: `Expected goals`, `Big chances`, `Total shots`, `Shots on target`, `Shots inside box`, `Touches in penalty area`, `Ball possession`.

### Event Models (`event_models.py`)
- Modelo Poisson genérico para eventos não‑gols.
- `fit_event_model(history, event_name, features=None)` — MLE Poisson (ou NB).
- `predict_event(elo_a, elo_b, params, features=None)` → λ + probs Over/Under.

### Scripts de pesquisa (`src/research/`)
- `sofascore_probe.py` — sonda de diagnóstico do Sofascore.
- `score_metrics.py` — Brier Score, Log‑Loss, Diebold‑Mariano.
- `verify_calibration.py` — teste barato: roda baseline vs CADA uma das 45 features individualmente (É o script que gera a tabela de calibração da Fase 2).
- `test_combinations.py` — testa combinações de features.

### Scripts de diagnóstico e backtest (eventos não‑gols)
- `src/backtest_event.py` — backtest CLV para cards e corners.
- `src/diagnose_event_data.py` — diagnóstico de cobertura cruzada.

### Suíte de testes — 159 verdes
- Cobre: Shin, NB→Poisson, CLV/ledger, COALESCE write‑once, derive_groups, MarketPricer, parse_all_odds, parse_statistics, feature_builder, MLE+delta_xg, event_models (básico). Tudo em `:memory:`, sem disco/rede.

### Estabilidade/observabilidade (stdlib, sem dependência nova)
- WAL + `busy_timeout` — leitor e escritor concorrem sem lock.
- Retry com backoff exponencial (404 não re‑tenta).
- Logging estruturado (console + rotativo).

---

## O que NÃO está feito (e por quê)

| Item | Status | Motivo |
|------|--------|--------|
| 4b (DNB/AH/OU‑inteira push‑aware no backtest) | ⏳ Pendente (baixa prioridade) | Mais N do mesmo viés; não mudaria a conclusão de "sem edge". |
| Expandir cobertura de dados (Eliminatórias, Nations League) | ⏳ Pendente (baixa prioridade) | A pesquisa já mostrou que o sinal é marginal; mais dados podem ser úteis, mas o ROI é baixo. |
| Prior FIFA / correção de inflação continental | 🔮 Futuro (v2.0) | Pós‑Copa; não interfere nas conclusões atuais. |
| Integração de corners no `predict.py`/`simulator.py` | ❌ Não será feito | O edge é inexplorável com thresholds realistas; integrar seria enganoso. |
| Dados de chutes/cartões para times específicos | ❌ Não disponível localmente | `match_statistics` não cobre Copa 2026; `ingest_fbref` bloqueado. |

---

## Coisas conscientemente RECUSADAS
- Docker, CI/CD com gate de ROI, Pydantic, loguru/tenacity, Playwright.
- Integração de corners/cards no pipeline principal (após verificar que o edge é inexplorável).

---

## Topologia de Rede
- Coleta do Sofascore roda FORA da rede Volvo (rede pessoal/4G com VPN desligada).
- Sync UNIDIRECIONAL casa→trabalho. `matches.db` flui por `Copy-Item`.

---

## Como rodar

**CASA CANÔNICA:** `C:\Claude-projetos\Claude\wc-predictor-v2`

```powershell
# Rede limpa (coleta)
python -m src.ingest
python -m src.ingest_sofascore
python -m src.cron_update_models

# Rede Volvo (leitura)
python -m src.predict Brazil France --neutral
python -m src.predict --fixtures 8
python -m src.simulator 10000
python -m src.backtest
python -m src.bootstrap

# Pesquisa (Fase 2 – features)
python -m src.research.verify_calibration   # baseline vs cada uma das 45 features
python -m src.research.test_combinations    # combinações de features

# Pesquisa (Fase 2 – eventos não‑gols)
python -m src.backtest_event                 # backtest CLV para cards/corners
python -m src.diagnose_event_data            # diagnóstico de cobertura

# Testes
pip install -r requirements-dev.txt
python -m pytest  # 159 verdes
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
Resumo Executivo (para retomar)
Onde estamos: Projeto concluído. Todas as fases entregues. O modelo não tem edge explorável em nenhum mercado testado.

O que funciona: Infraestrutura completa de coleta, modelagem, backtest, simulação e previsão. 159 testes verdes.

O que não funciona: O modelo 1X2 perde dinheiro (CLV -15%). O edge em corners é marginal e inexplorável. Não há dados locais de chutes/cartões para a Copa 2026.

Uso legítimo: Referência de probabilidade (Shin), sanity‑check contra o mercado, simulação de torneio com viés conhecido.

Próxima ação (se houver): Expandir cobertura de dados (Eliminatórias, Nations League) para testar se o sinal em corners aumenta com amostra maior — mas isso é pesquisa adicional, não correção.

## 2026-07-11 — Oportunidade identificada: modelo de intervalo

**Contexto:** Norway 1×1 England (quartas de final). No pré‑jogo, o modelo indicava
Under 2.5 FT (edge +7,2%, confiança ALTA) e Under 1.5 1T (confiança 75,5%). Ambos
os picks foram lucrativos (+1,41u combinado).

**Observação:** No intervalo (1×0), a odd para o Under 2.5 e para o Under 1.5 do
segundo tempo disparou (o mercado passou a temer mais gols na etapa final). Se o
modelo tivesse uma segunda entrada ali, o retorno teria sido 5–6× maior. O
`prever.py --segundo-tempo` calculou corretamente as probabilidades condicionais,
mas não há backtest para apostas in‑play — qualquer entrada no intervalo seria
fora do protocolo.

**Encaminhamento:** Registrada como candidata a H6 no backlog. Para se tornar uma
hipótese testável, será necessário:
- Uma série histórica de placares de intervalo + odds ao vivo (fonte a definir).
- Um backtest walk‑forward que simule entradas no intervalo com stake controlado.
- Registro no `TrialRegistry` e validação com DSR.

Até lá, o `prever.py --segundo-tempo` segue como ferramenta informativa, sem
capacidade de gerar apostas reais.