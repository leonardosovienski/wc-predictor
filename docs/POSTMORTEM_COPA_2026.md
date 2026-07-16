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
- [ ] Última aferição: `python -m src.settle <home> <away> <hs> <as>` dos 2 jogos
      (placar de **90min** no mata-mata, como nos demais)
- [ ] Backup datado: `Copy-Item data/matches.db data/matches_copa2026_frozen_YYYYMMDD.db`
- [ ] Depois disso `matches.db` da Copa **não recebe mais escrita**
- [ ] Liquidar apostas abertas remanescentes no livro (hoje: nenhuma)

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

`python -m src.bet_log banca`: saldo **R$ 908,00** (inicial R$ 1.000, unidade R$ 50),
**−1,84u = −R$ 92,00** em 9 apostas fechadas, 0 abertas. Drawdown máximo R$ 200
(placar exato França×Espanha, stake 4u — decisão do operador sem edge pré-calculado).
Casa real de execução: BetMGM (odds registradas = as executadas, não as do line shopping).

## 4. Incidentes de integridade a reportar no relatório final

- **`data/predictions.jsonl` foi truncado entre 11 e 12/07/2026** (mtime 15/07, só 3
  linhas restantes, a partir de 12/07). Violação do append-only do registro obrigatório.
  Mitigação: as predições das oitavas + 3 quartas sobrevivem embutidas em
  `data/results.jsonl`; o envelope 1X2 de todas está na telemetria (`events.jsonl`).
  Perda real: o palpite completo pré-jogo de Norway×England (grade de placares/OU).
  Causa raiz: _TODO investigar_ (nenhuma rotação de predictions.jsonl existe no código).
- Apostas de placar exato registradas manualmente com `"market": "correct_score"`
  (fora do enum do `bet_log`); `banca` funciona, `list`/`summary` podem quebrar
  (KeyError 'line') — checar antes de usar no relatório.
- Registro original Argentina×Switzerland (Over 2.5 @2.30 "NordicBet") era placeholder,
  ANULADO com settlement profit=0 — excluir do ROI (nota na própria linha).

## 5. Decisões a tomar no post-mortem

- **Promoção do shadow** (SHADOW.md): promover os fixes (simulador DC-grid + seed,
  paridade train/serve no backtest, telemetria) à produção `../wc-predictor` e
  descomissionar o v2. Mandato libera após ~19/07.
- **Go/No-Go da v3** — critérios em `docs/V3_READINESS.md`.
- Reconciliar `src/bootstrap.py` e `src/research/score_metrics.py` com o core por
  validação de TOLERÂNCIA (congelados até aqui por mandato do playbook).
- Adoção do TrialRegistry + harness do core v1.3.0 (edge sintético no funil O/U) —
  passo obrigatório antes do modelo de 2T condicionado ao HT.
- Candidata H6 (modelo de intervalo / entrada no HT) — ver HANDOFF 2026-07-11.

## 6. Só DEPOIS do post-mortem

Sensibilidade de hiperparâmetros (`docs/HYPERPARAMETERS.md`) e eventual expansão de
dados (Eliminatórias, Nations League), se ainda fizer sentido.
