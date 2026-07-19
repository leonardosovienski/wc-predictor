# POSTMORTEM — Copa 2026 (EM CONSTRUÇÃO)

> **Status: esqueleto pré-registrado, iniciado em 2026-07-16 (antes da final).**
> Congelamento da coleta: fim da Copa (~19/07/2026). Janela de análise: até
> **2026-08-02** — o que não entrar até lá, não entra (playbook §5).
> Nada nas seções de veredito pode ser preenchido antes do congelamento.

Jogos restantes no momento da criação deste esqueleto:
- 2026-07-18 — France × England (3º lugar)
- 2026-07-19 — Spain × Argentina (FINAL)

---

## 0. Checklist do congelamento (executar após a final, ~19/07)

- [ ] Último `python -m src.ingest` com o placar da final (e do 3º lugar)
- [x] ~~Última aferição dos 2 jogos~~ **parcial (2026-07-19)**: 3º lugar já
      aferido — France 4-6 England, palpite 0/4 mercados, acumulado 14 jogos
      (winner 8/14, ou25 6/14, btts 6/14, exato 1/14). Falta só a final.
      Previsões dos 2 últimos jogos congeladas no ledger ANTES dos respectivos
      resultados chegarem ao repo (linhas 4-5 do `predictions.jsonl`,
      19/07 15:19Z e 15:21Z).
- [ ] Última aferição: `python -m src.settle Spain Argentina <hs> <as>`
      (placar de **90min**, como nos demais)
- [ ] Backup datado: `Copy-Item data/matches.db data/matches_copa2026_frozen_YYYYMMDD.db`
- [ ] Depois disso `matches.db` da Copa **não recebe mais escrita**
- [x] Liquidar apostas abertas remanescentes no livro — **nenhuma** (0 abertas,
      confirmado 19/07 via `bet_log banca`)

## 1. Métricas pré-registradas (playbook §4 — preencher pós-congelamento)

As fatias são SOMENTE as pré-registradas: total, 1X2, OU2.5. Fatia nova = exploratória,
fora do veredito. Expectativa declarada no playbook: **o mercado vence** (~0.57 vs ~0.49).

1. **Brier 1X2 / log-loss** modelo vs mercado Shin do fechamento, nos 104 jogos: _TODO_
2. **CLV** da população `bet_at='open'` com IC por cluster de jogo (`python -m src.bootstrap`): _TODO_
3. **P&L real** (`data/bets.jsonl` + `live_decisions.csv`): n, stake total, IC — sem recorte a posteriori: _TODO_
4. **Calibração** por faixa de probabilidade (tabela do backtest) + curva do simulador (qualitativo): _TODO_
5. Revalidação do `initialFractionalValue` contra os snapshots `pre_match=1` acumulados: _TODO_

## 2. Aferição parcial (fotografia de 2026-07-16, PRÉ-congelamento — não é veredito)

`python -m src.settle --summary` com 13 jogos aferidos:

| Mercado | Acerto |
|---|---|
| winner | 8/13 (62%) |
| over/under 2.5 | 6/13 (46%) |
| btts | 6/13 (46%) |
| placar exato | 1/13 (8%) |

Norway×England (quartas) está registrado como **não avaliado**: o palpite completo
congelado se perdeu no truncamento do `predictions.jsonl` (ver §4). A telemetria
(`events.jsonl`, 2026-07-11T20:45Z, pré-apito) preserva o envelope 1X2:
Norway 28,25% / empate 26,79% / England 44,96% — England era o pick e o 90min
terminou 1×1 (England avançou na prorrogação).

Convenção usada em TODO o mata-mata: aferição e liquidação pelo **placar de 90min**.

## 3. P&L real parcial (fotografia de 2026-07-16)

`python -m src.bet_log banca`: saldo **R$ 708,00** (inicial R$ 1.000, unidade R$ 50),
**−5,84u = −R$ 292,00** em 10 apostas fechadas, 0 abertas. Drawdown máximo R$ 400 —
dois bilhetes de R$ 200 (4u) perdidos em sequência: placar exato 1×1 França×Espanha
@5.00 (sem edge pré-calculado) e SGP Empate+Under 2.5 England×Argentina @5.10 (este
**+EV pelo modelo**: P(0-0)+P(1-1) = 21,94% da grade congelada, odd justa 4.56,
EV +11,9% — processo certo, variância; 90min 1-2). Casa real de execução: BetMGM
(odds registradas = as executadas, não as do line shopping).

## 4. Incidentes de integridade a reportar no relatório final

- **`data/predictions.jsonl` foi truncado entre 11 e 12/07/2026** (mtime 15/07, só 3
  linhas restantes, a partir de 12/07). Violação do append-only do registro obrigatório.
  Mitigação: as predições das oitavas + 3 quartas sobrevivem embutidas em
  `data/results.jsonl`; o envelope 1X2 de todas está na telemetria (`events.jsonl`).
  Perda real: o palpite completo pré-jogo de Norway×England (grade de placares/OU).
  **Causa raiz (investigada e confirmada em 2026-07-19, evidência forense em
  transcripts/telemetria/reflog):** não foi truncamento — foi **sobrescrita por
  cópia**. Em 2026-07-12T08:14:24Z, uma sessão de assistente que servia previsões
  de dentro do worktree `.claude/worktrees/wc-predictor-betting-4d2eaf` (que não
  tinha `data/` — gitignored não vem no checkout; a sessão criou `data/` do zero
  às 07:56:18Z e o `prever.py` de lá gerou um `predictions.jsonl` novo com 2
  linhas) executou `cp <worktree>/data/predictions.jsonl <principal>/data/predictions.jsonl`
  ("synced"), clobberando o arquivo principal com todo o histórico. O worktree
  foi removido às 10:10:41Z da mesma sessão. O código é inocente (só abre em
  `"a"`); git é inocente (reflog silencioso na janela; arquivo nunca rastreado);
  o operador é inocente (histórico do PowerShell sem deleções). Mesma classe do
  incidente de 07/07 ("dado ignorado tratado como descartável"), mas o guard
  `test_repo_hygiene.py` protege código do `.gitignore`, não dados de fluxos
  com worktree. Lição estrutural: servir SEMPRE do repo principal (ou apontar
  `PREDICTIONS_LOG_PATH` para o arquivo principal); nunca "sincronizar" um
  JSONL append-only por cópia inteira — append é a única operação legítima.
  Recuperação total: impossível (a cópia destruiu o único original); as
  mitigações acima são o que existe.
- **Achado lateral da mesma investigação**: a produção original
  (`C:\Users\Superleo13\Downloads\wc-predictor`) foi deletada para a Lixeira do
  Windows em **2026-06-26T17:56Z** e ainda estava lá em 19/07 — potencialmente
  restaurável (incluindo o `data/matches.db` do cron de odds). Isso explica a
  contradição histórica do SHADOW.md: a promoção pós-Copa planejada ficou sem
  objeto porque a produção deixou de existir em 26/06; o v2 é o único
  sobrevivente. Decisão sobre restaurar ou deixar expirar: humana, no
  encerramento (§5).
- Apostas de placar exato registradas manualmente com `"market": "correct_score"`
  (fora do enum do `bet_log`); `banca` funciona, `list`/`summary` podem quebrar
  (KeyError 'line') — **checado em 2026-07-19: NÃO quebram.** `list` e `summary`
  retornam exit 0; o `summary` classifica corretamente `correct_score` (3
  apostas, −2,90u) e `sgp_draw_under25` (1 aposta, −4,00u) como INFORMATIVO
  (sem odd de fechamento). Ferramentas aptas para preencher o §1 sem correção.
- Registro original Argentina×Switzerland (Over 2.5 @2.30 "NordicBet") era placeholder,
  ANULADO com settlement profit=0 — excluir do ROI (nota na própria linha).

## 5. Decisões do post-mortem (TOMADAS em 2026-07-19, exceto onde indicado)

- **Promoção do shadow** — **SEM OBJETO.** A investigação forense do §4 provou
  que a produção `../wc-predictor` (na verdade `Downloads\wc-predictor`) foi
  deletada para a Lixeira em 2026-06-26T17:56Z. Não há para onde promover nem
  o que descomissionar: o v2 é o herdeiro único e permanece como registro
  histórico PARKED do ecossistema. O plano do SHADOW.md fica marcado como
  histórico.
- **Go/No-Go da v3** — **NÃO RETOMADA; arquivada com o projeto.** O gate
  estatístico nunca pôde rodar (seasons 2021-22 inexistentes no banco,
  survival_test quebrado no modo híbrido — ver `docs/V3_READINESS.md`, que
  permanece como registro honesto). Retomada futura exigiria decisão humana
  explícita + hipótese formalizada, o padrão do ecossistema.
- **Reconciliação bootstrap/score_metrics × core** — **NÃO REALIZADA, por
  decisão.** Só se justificaria com projeto vivo; o encerramento a torna sem
  benefício. O código local permanece congelado como está.
- **TrialRegistry + harness (pré-requisito do modelo de 2T)** — **SEM OBJETO**
  com o encerramento; não haverá modelo de 2T neste repo.
- **Candidata H6 (modelo de intervalo / entrada no HT)** — **não aberta aqui;
  conhecimento transferido.** A ideia sobrevive no ecossistema: o
  brasileirao-predictor já trabalha mercados de 1T (H2 informativa) e é o
  destino natural se a hipótese for formalizada um dia.
- **Restauração da produção deletada (Lixeira)** — **DECISÃO HUMANA PENDENTE**
  (única além da final): restaurar `Downloads\wc-predictor` da Lixeira como
  arquivo morto (preserva o `matches.db` do cron de odds) ou deixar expirar.
  Registrar a escolha aqui quando tomada.

## 6. Só DEPOIS do post-mortem

Sensibilidade de hiperparâmetros (`docs/HYPERPARAMETERS.md`) e eventual expansão de
dados (Eliminatórias, Nations League), se ainda fizer sentido.
