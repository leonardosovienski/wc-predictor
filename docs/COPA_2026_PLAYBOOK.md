# Playbook — Copa 2026 (congelado em 2026-07-02)

> Regras de operação do wc-predictor-v2 durante e depois da Copa. O objetivo é
> chegar ao pós-torneio com uma avaliação **pré-registrada** — decidida ANTES
> dos resultados — imune a cherry-picking e a recalibração oportunista.
> Contexto: o modelo NÃO tem edge comprovado (CLV open −8,7%, IC cluster
> [−12,4%, −4,4%]); o uso legítimo é referência de probabilidade (Shin),
> sanity-check e simulação de torneio com viés conhecido.

## 1. Antes de cada rodada (rede limpa, máquina do Leo)

```powershell
python -m src.ingest                   # resultados/fixtures martj42
python -m src.ingest_sofascore        # odds (abertura/fechamento/snapshots) + stats
python -m src.cron_update_models      # recalcula Elo/params e materializa o cache
python scripts/ci_check.py --fast     # barreiras estáticas (pesquisa ro, lookahead)
python -m src.predict --fixtures 8    # previsões da rodada
```

Checks de sanidade a cada coleta:
- O `cron_update_models` NÃO pode emitir `RuntimeWarning` de convergência/bound
  (alarme novo do MLE). Se emitir, algo mudou nos dados — investigar antes de usar.
- `python -m src.status` — conferir contagens de odds/snapshots crescendo.
- Validação da abertura: os snapshots `pre_match=1` acumulados pelo cron são a
  única régua que valida `initialFractionalValue` como abertura real (hoje ~26
  eventos — fraco). Guardar; a revalidação é tarefa do post-mortem.

## 2. O que NÃO fazer durante a Copa (anti-overfitting)

- **NÃO recalibrar hiperparâmetros** (K-factors, janelas, half-life, edge
  window, ρ/α bounds) com jogos da própria Copa. O `config_hash` do cache
  existe para detectar mudança de config — ele mudar durante o torneio é
  sinal de contaminação, não de melhoria.
- **NÃO reotimizar/adicionar features** com dados da Copa. A Fase 2 corrigida
  já mostrou 0/45 features úteis; qualquer "descoberta" mid-tournament com
  n<104 jogos é ruído com história boa.
- **NÃO integrar corners/cards** — amostra real de 98/89 jogos, 14 apostas de
  teste; inconclusivo por construção.
- **NÃO promover o shadow à produção** enquanto o cron da Copa coleta
  (mandato do SHADOW.md: promover só após ~19/07/2026).
- **NÃO mexer no `data/matches.db` da produção** (`../wc-predictor`) — o v2 lê
  em `mode=ro`.

## 3. Registro de decisões em tempo real (separado do backtest)

O ledger do backtest (`backtest_bets`) é RETROSPECTIVO — apostas hipotéticas
liquidadas em lote. Decisão tomada em tempo real vai em um log próprio,
**escrito no momento da decisão**, nunca depois do jogo:

- Arquivo: `data/live_decisions.csv` (append-only, uma linha por decisão),
  colunas mínimas:
  `timestamp_utc, match, market, selection, odd_disponivel, p_modelo, p_shin,
  edge, decisao (bet/no-bet), stake, motivo`
- Registrar também os **no-bets relevantes** (edge > 2% que você decidiu não
  seguir) — sem eles o P&L realizado vira amostra selecionada.
- A previsão de cada jogo já é registrada automaticamente pela telemetria
  (`emit_event "prediction"` → `events.jsonl`) — serve de carimbo de que a
  probabilidade foi gerada ANTES do apito (o timestamp é do envelope).
- Nunca editar linha antiga; correção = nova linha com `motivo=correcao`.

## 4. Avaliação pós-Copa (pré-registrada AGORA)

Métricas, no conjunto COMPLETO dos 104 jogos da Copa (sem exclusões):
1. **Brier 1X2** e **log-loss** do modelo vs mercado Shin do fechamento —
   a comparação primária. Expectativa honesta declarada hoje: o mercado vence
   (walk-forward histórico: ~0.57 vs ~0.49).
2. **CLV** da população `bet_at='open'` com IC por **cluster de jogo**
   (`python -m src.bootstrap`) — nunca o IC i.i.d.
3. **P&L** do `live_decisions.csv` (se houver apostas reais) — reportado com
   n, stake total e IC; sem recorte por mercado a posteriori.
4. **Calibração** por faixa de probabilidade (a tabela que o backtest já
   imprime) e a curva do simulador (P(título) vs resultado — 1 amostra, só
   qualitativo).

Regras anti-cherry-picking:
- As fatias de análise são SOMENTE as pré-registradas acima (total, 1X2,
  OU2.5). Qualquer fatia nova descoberta depois é EXPLORATÓRIA e vai rotulada
  como tal, fora do veredito.
- Vale a correção informal de teste múltiplo já usada no projeto: 1 mercado
  positivo cercado de vizinhos negativos = falso positivo até prova em
  contrário (caso OU2.5, +17% isolado).
- O veredito compara com a expectativa declarada AQUI, não com a esperança.

## 5. Post-mortem — congelamento

- **Data de congelamento da coleta:** fim da Copa (~19/07/2026). Depois disso,
  `matches.db` da Copa não recebe mais escrita (backup datado do arquivo).
- **Janela de análise:** até **2026-08-02** (duas semanas). O que não entrou
  até lá, não entra no relatório final — análise aberta indefinidamente é
  fábrica de cherry-picking.
- **Entregável:** `docs/POSTMORTEM_COPA_2026.md` com: métricas da seção 4,
  revalidação do `initialFractionalValue` contra os snapshots pré-jogo
  acumulados, decisão sobre promoção do shadow (fixes → produção,
  descomissionar o v2 conforme SHADOW.md) e decisão Go/No-Go da v3
  (critérios em `docs/V3_READINESS.md`).
- Só DEPOIS do post-mortem: análise de sensibilidade dos hiperparâmetros
  (`docs/HYPERPARAMETERS.md`) e eventual expansão de dados (Eliminatórias,
  Nations League), se ainda fizer sentido.
