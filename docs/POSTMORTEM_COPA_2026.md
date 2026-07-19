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

- [~] Último `python -m src.ingest` com o placar da final (e do 3º lugar) —
      **parcial (19/07 19:09 BRT)**: 3º lugar (France 4-6 England) ingerido da
      fonte; a FINAL (Spain 0-0 Argentina em 90min; 1-0 Espanha na prorrogação,
      campeã) ainda não publicada no martj42 — banco com 1 fixture pendente.
      **Reexecutar o ingest quando a fonte atualizar (~24h) e só então
      congelar.** A aferição oficial da final JÁ está gravada (ver abaixo) —
      o settle não depende do banco.
- [x] ~~Última aferição dos 2 jogos~~ **parcial (2026-07-19)**: 3º lugar já
      aferido — France 4-6 England, palpite 0/4 mercados, acumulado 14 jogos
      (winner 8/14, ou25 6/14, btts 6/14, exato 1/14). Falta só a final.
      Previsões dos 2 últimos jogos congeladas no ledger ANTES dos respectivos
      resultados chegarem ao repo (linhas 4-5 do `predictions.jsonl`,
      19/07 15:19Z e 15:21Z).
- [x] Última aferição: **FEITA (19/07)** — `settle Spain Argentina 0 0`
      (90min; Espanha campeã 1-0 na prorrogação). Palpite da final: **2/4**
      (Under 2,5 ✓ e BTTS Não ✓; vencedor nominal Spain ✗ em 90min = empate;
      placar exato 1×1 ✗ — o 0×0 real era o 2º mais provável do modelo,
      10,7%). **Aferição final da Copa, 15 jogos: winner 8/15 (53%),
      OU2,5 7/15 (47%), BTTS 7/15 (47%), placar exato 1/15 (7%).**
- [x] Backup datado: **FEITO** — `data/matches_copa2026_frozen_20260719.db`
      (13.631.488 bytes). Nota de desvio documentado: o placar da final
      (Spain 0-0 Argentina, 90min) foi inserido MANUALMENTE no banco por
      ordem explícita do operador ("fecha já"), porque a fonte martj42
      ainda não o havia publicado no momento do congelamento; valor
      idêntico ao aferido em `results.jsonl` e conferível contra a fonte
      quando ela atualizar.
- [x] Depois disso `matches.db` da Copa **não recebe mais escrita** —
      selado em 2026-07-19 ~19:15 BRT (artefatos derivados de pesquisa
      como `backtest_bets.csv`/`bootstrap_cache.json` não são o banco)
- [x] Liquidar apostas abertas remanescentes no livro — **nenhuma** (0 abertas,
      confirmado 19/07 via `bet_log banca`)

## 1. Métricas pré-registradas (playbook §4 — preencher pós-congelamento)

As fatias são SOMENTE as pré-registradas: total, 1X2, OU2.5. Fatia nova = exploratória,
fora do veredito. Expectativa declarada no playbook: **o mercado vence** (~0.57 vs ~0.49).

**PREENCHIDAS em 2026-07-19, pós-congelamento, com as ferramentas
pré-registradas** (`src.backtest` + `src.bootstrap`, banco congelado
`matches_copa2026_frozen_20260719.db`):

1. **Brier 1X2 modelo vs mercado**: não reduzido a um par único de números
   nesta execução (nenhuma ferramenta pré-registrada o imprime diretamente;
   criar análise nova no fechamento violaria o pré-registro). Evidência
   equivalente e conclusiva: CLV 1X2 **−15,77% [−20,65%, −10,95%]
   SIGNIFICATIVO** — o mercado vence no 1X2, exatamente a expectativa
   declarada do playbook. A tabela de calibração (item 4) mostra
   sobreconfiança crescente por faixa de edge.
2. **CLV população `open` (n=499 apostas, 130 jogos), IC por cluster**:
   total **−8,37% [−11,49%, −4,85%] SIGNIFICATIVO** (sem edge agregado);
   1X2 −15,77% (sig. negativo); **OU2,5 +16,92% [+11,55%, +22,77%]
   SIGNIFICATIVO** — o único edge comprovado do domínio sobreviveu à Copa
   inteira. Por faixa de edge: 0-5% −12,0% (sig.), 5-10% −10,2% (sig.),
   10-15% +7,2% (cruza zero).
3. **P&L real**: −5,84u = −R$ 292,00 em 10 apostas fechadas (banca
   R$ 1.000 → R$ 708; aposta anulada excluída; 0 abertas). Decomposição
   honesta: mercado validado OU2,5 **+1,14u (ROI +28,5%)**; todo o
   prejuízo veio de apostas fora do funil (placar exato −2,90u, SGP
   −4,00u, informativas 1T −0,08u). n pequeno demais para IC — reportado
   como contabilidade, não como inferência.
4. **Calibração por faixa de edge (backtest, paridade train/serve)**:
   0-5%: prob média 36,4% vs acerto real 32,2% (n=239); 5-10%: 42,5% vs
   32,8% (n=183); 10-15%: 44,8% vs 36,4% (n=77) — sobreconfiança em toda
   faixa, pior nas altas. ROI do backtest: todas as fatias com IC 95%
   cruzando zero (variância domina; sem significância econômica).
5. **Revalidação do `initialFractionalValue`**: NÃO reexecutada no
   fechamento — validação anterior (2026-07-10, revalidação de 9 itens)
   mantida como evidência; registrado como limitação honesta, não como
   confirmação nova.

### VEREDITO FINAL DA COPA 2026

**A expectativa pré-registrada do playbook confirmou-se: o mercado vence
no agregado.** CLV total significativamente negativo; 1X2 com viés de
achatamento estrutural confirmado do primeiro ao último jogo. **A exceção
real, comprovada e sustentada é o Over/Under 2,5** (CLV +16,9%
significativo, n=78 em 78 jogos) — edge de preço genuíno, mas sem volume
suficiente na Copa para significância econômica (ROI com IC cruzando
zero; P&L real do funil +1,14u). A herança científica é exatamente essa
população, já transferida como base da H1 do brasileirao-predictor (§7).
O prejuízo real da banca (−5,84u) veio integralmente de apostas fora do
funil validado — a lição operacional definitiva do projeto.

**wc-predictor: ENCERRADO em 2026-07-19.**

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
  ~~Recuperação total: impossível (a cópia destruiu o único original); as
  mitigações acima são o que existe.~~ **ATUALIZAÇÃO (2026-07-19): RECUPERADO
  EM GRANDE PARTE.** A restauração da Lixeira (decisão §5) revelou um backup
  integral do v2 em `E:\wc-predictor-v2` (deletado 12/07 23:47 BRT, restaurado
  19/07) cujo `data/predictions.jsonl` preserva **28 predições de 04/07 a
  07/07 23:11Z** — incluindo o pacote completo pré-jogo de Norway×England
  (2 registros, 07/07). Cópia versionada em
  `docs/recovered_predictions_backup_e_20260707.jsonl`. Perda líquida final:
  apenas o refresh de 11/07 20:45Z pré-apito (Elo pós-2-quartas), cujo
  envelope 1X2 sobrevive na telemetria. O ledger atual (pós-clobber) NÃO foi
  tocado — os dois arquivos coexistem, cada um com sua proveniência.
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
- **Restauração da produção deletada (Lixeira)** — **DECIDIDA E EXECUTADA
  (2026-07-19, ordem do operador)**: os 3 itens `wc-predictor*` da Lixeira
  foram restaurados. Resultado: (a) `Downloads\wc-predictor` (a "produção")
  revelou-se um snapshot SÓ de código de ~06/2026, sem `.git` e sem `data/` —
  o mito do "banco de odds do cron na produção" está desfeito; snapshot
  preservado versionado em `archive/wc-predictor-producao-original/`;
  (b) `wc-predictor-final.zip` restaurado em Downloads;
  (c) **`E:\wc-predictor-v2` (331 MB, backup integral de ~07/07)** — o achado
  real: recuperou o ledger de predições perdido (ver §4). Backup mantido em
  E:\ como arquivo morto adicional.

## 6. Só DEPOIS do post-mortem

Sensibilidade de hiperparâmetros (`docs/HYPERPARAMETERS.md`) e eventual expansão de
dados (Eliminatórias, Nations League), se ainda fizer sentido.

## 7. Inventário de legado — o que deste projeto serve às outras (2026-07-19)

Auditado antes do selo para nada se perder. Verificação factual: o diff de
`src/` WC × brasileirão é **vazio no sentido WC→brasileirão** — o herdeiro
direto carrega 100% dos módulos (motor NB+Dixon-Coles, Shin, CLV com
bootstrap por cluster, bet_log/banca, settle, odds_shop, market_pricer,
event_models) e adicionou os seus próprios. Nenhum código se perde com o
encerramento.

**Já transferido e vivo no ecossistema:**
- Motor estatístico completo + livro-caixa + aferição → brasileirão (herança
  integral, confirmada por diff).
- Conhecimento negativo virou regra: "1X2 nunca" (CLV −16% estrutural),
  aposta real só em mercado com CLV comprovado do domínio, log append-only
  ANTES do jogo, pesquisa read-only — são as "Regras inegociáveis" do
  README do brasileirão. Corners/cards sem edge explorável e features de
  dominância retratadas (0/45) idem.
- `initialFractionalValue` como abertura real do Sofascore + janela de edge
  2-15% (a população OU2.5 com CLV +16% validado aqui é a base da H1 do
  brasileirão).
- H6 (modelo de intervalo/entrada no HT) → transferida como conhecimento ao
  brasileirão (§5).

**Registrado como candidato, aguardando o gatilho certo (nada a fazer agora):**
- Shin, cliente curl_cffi+impersonate, Platt, motor prequential, harness
  Brier+DM → candidatos ao core (INC-2 de `PENDENCIAS_ABERTAS.md`, roadmap
  de agosto), cada um já duplicado em 2-3 domínios.
- Disciplina de odds snapshot/settlement/CLV → CS/LoL (T02 da auditoria
  cross-domain, "testar em shadow"): bloqueada por ausência de fonte de odds
  de e-sports (SCI-7). O dia em que houver fonte, a referência de
  implementação é ESTE repo.

**Legado que só existe aqui (preservado no repo PARKED, não replicado):**
- **Playbook de dinheiro real** — a experiência operacional única do
  ecossistema: odd registrada = odd executada na casa real (lição BetMGM),
  carimbo de aposta tardia, alerta de duplicata, tratamento de push, a lição
  da SGP +EV que perdeu (processo certo, variância) e o resultado-síntese:
  mercado validado +1,14u vs. apostas fora do funil −5,84u. O brasileirão
  DEVE reler os banners do HANDOFF daqui antes de sair do modo sombra.
- **Simulador de bracket Monte Carlo** (mata-mata de torneio) — único no
  ecossistema; se um domínio futuro precisar (Copa 2030, playoffs), está aqui.
- **Dados irreproduzíveis**: martj42 ~49k jogos + odds da Copa 2026 com
  snapshots de abertura em `matches.db` (backup congelado no selo) + a
  produção deletada na Lixeira (decisão §5 pendente).
- **Lição operacional ecossistêmica** (do §4): nunca servir de worktree;
  dado gitignored não existe em checkout; "sincronizar" JSONL append-only
  por cópia inteira é proibido — append é a única operação legítima. Vale
  para TODOS os projetos com `data/` gitignored.
