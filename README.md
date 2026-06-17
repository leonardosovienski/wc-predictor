# wc-predictor

Sistema de coleta e análise de dados para previsão de partidas internacionais de futebol (Copa do Mundo 2026).

## Métricas previstas (por jogo)

Todas derivam da grade de probabilidade de placares — uma única passada, sem dado
adicional: resultado 1X2, placar exato (top 5), total de gols esperado,
over/under (1.5/2.5/3.5) e ambos marcam (BTTS).

## Roadmap (incremental)

1. **[feito] Métricas por jogo** — 1X2, placar, over/under, BTTS.
2. **[feito] Motor estatístico** — Binomial Negativa (overdispersion) + correção
   Dixon-Coles (empates), calibrados por MLE via scipy.
3. **[feito] Cache de serving** — Elo e parâmetros materializados; a CLI lê em vez
   de recalcular (262× mais rápida). Atualizado pelo `cron_update_models`.
4. **[feito] Mercado (Shin)** — odds do Sofascore purificadas do overround; o
   painel compara modelo vs mercado e sinaliza divergência.
5. **[feito] Simulação de torneio** — Monte Carlo do bracket 2026 → P de avançar,
   chegar à final, ser campeã. Inclui fatores contextuais (incentivo, expulsão).
6. **[feito] Backtest (Quality Gate)** — engine de aposta de valor com stake fixo
   contra as odds históricas; ledger auditável + relatório de calibração por edge.
7. **[feito] CLV + significância** — abertura/fechamento com write-once, snapshots
   temporais, CLV vs Shin do fechamento como régua de baixa variância, bootstrap
   IC 95%, e suíte de pytest blindando os invariantes (24 testes).
8. **[em operação] Coleta pré-apito da Copa 2026** — cron em rede limpa capturando
   aberturas; é o que alimenta a população onde o CLV carrega sinal (até 19/07).
9. **[a fazer] Conectar dado de jogador** — xG e notas do Sofascore alimentando o
   ajuste de força. Pré-requisito cumprido: o backtest mede se a mudança paga.
10. **[v2.0, pós-Copa] Prior FIFA contra a inflação continental** — regularização
    dentro do MLE com A/B vs Elo cru, condicionada ao resultado da hipótese
    pré-registrada (ver Decisões e tradeoffs).

## Fontes de dado de jogador e mercado

**Sofascore (`python -m src.ingest_sofascore`)** é a fonte principal: placar, xG,
odds 1X2 e notas de jogador num lugar só, gravados em `sofascore_matches` e
`sofascore_player_ratings`. O acesso usa `curl_cffi` (impersonate de Chrome) —
leve, sem arrastar motor anti-bot tipo botasaurus/Selenium. Em rede corporativa
com inspeção TLS, o cliente exporta o cofre de certificados do Windows para o
`verify` do libcurl automaticamente. Competições/seasons em `config.yaml`
(`sofascore.competitions`); descubra ids com `--seasons UT_ID`. ToS e fragilidade
de endpoint não-oficial são tradeoffs aceitos para projeto pessoal.

**FBref (`python -m src.ingest_fbref`)** segue como coletor secundário de stats
agregadas (minutos, gols, assistências) em `player_comp_stats`. Contexto: o FBref
perdeu a licença Opta em jan/2026 e o xG sumiu de lá — o que tornou o Sofascore a
única fonte de xG do projeto e motivou a inversão de prioridade entre os dois.

## Pipeline

```
ingest.py ──► SQLite (matches.db, WAL) ──► cron_update_models.py ──► cache (current_elo, model_parameters)
   │                │                          │  ratings.py (Elo+decay)        │
   │                │                          │  model.py (NB + Dixon-Coles)   ▼
   └ remota+retry   └ UPSERT idempotente       └ scipy MLE              predict.py / simulator.py
     +fallback local                                                   (leem o cache — serving instantâneo)

ingest_sofascore.py ──► odds (open/close + odds_snapshots) ──► math_utils.py (Shin) ──► predict.py (modelo vs mercado)
                          └────► backtest.py (Quality Gate: value bets, ledger, CLV, calibração)
                                    └────► bootstrap.py (IC 95% do ROI e do CLV — significância)

tests/ (pytest) ──► Shin · NB→Poisson · CLV/ledger · COALESCE write-once · derive_groups
                    (funções puras + SQLite :memory:, sem disco/rede — roda na Volvo)
```

## Setup local

Requer **Python 3.11+** (pandas 3.0 / numpy 2.4).

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m src.ingest            # baixa resultados (GitHub) e popula o SQLite
python -m src.predict --fixtures 8   # previsões dos próximos jogos
python -m src.ingest_fbref      # coleta stats de jogador (precisa alcançar fbref.com)
```

Tudo roda na sua máquina — Python + um arquivo SQLite, sem cloud. As fontes que
o sandbox bloqueia (FBref) funcionam normalmente aqui.

## Uso

```bash
pip install -r requirements.txt
python -m src.ingest                          # coleta/atualiza a base (re-rodável)
python -m src.cron_update_models              # materializa o cache (rode após cada ingest)
python -m src.predict Mexico "South Africa"   # partida avulsa (mando do 1º time)
python -m src.predict Brazil France --neutral # campo neutro
python -m src.predict --fixtures 8            # próximos jogos da Copa na base
python -m src.predict --rankings 20           # top 20 do Elo
python -m src.simulator 10000                 # Monte Carlo do torneio (N simulações)
python -m src.backtest                        # Quality Gate: P&L + CLV do modelo vs odds
python -m src.bootstrap                       # IC 95% (bootstrap) do ROI e do CLV do ledger
python -m src.status                          # painel do estado do banco e do cache

pip install -r requirements-dev.txt           # pytest (dep só de desenvolvimento)
python -m pytest                              # suíte de testes (puros + SQLite :memory:)
```

O `predict` e o `simulator` leem do cache — instantâneos. Sempre que entrar dado
novo (`ingest`/`ingest_sofascore`) ou mudar o `config.yaml`, rode o
`cron_update_models`; a CLI avisa quando o cache está velho. Falhas de coleta e
retries ficam registrados em `data/wc.log` com hora e severidade.

## Decisões e tradeoffs

**Elo + Poisson em vez de ML.** Seleções jogam ~10 partidas/ano — amostra esparsa
demais para gradient boosting sem features premium (xG, valor de elenco). Elo
captura força relativa com decay de recência embutido; é o mesmo princípio do
ranking oficial da FIFA pós-2018. Tradeoff: teto de acurácia menor que modelos
com dados proprietários, mas interpretável e sem overfit.

**Elo variante eloratings.net:** K por importância do torneio (Copa=60,
amistoso=20), home advantage de +100 pontos, multiplicador de K por saldo de
gols. Tudo em `config.yaml`.

**Memória / forma recente (decay temporal).** A previsão deve refletir a forma
atual, não o que a seleção era há 20 anos. O Elo já decai naturalmente (cada
jogo move só ~K pontos, então o passado distante é "esquecido"), mas isso é
controlado explicitamente por `elo.form_half_life_years`: a cada jogo o rating
regride à média proporcionalmente ao tempo desde a última partida do time.
Meia-vida de 4 anos = resultado dessa idade pesa 50%.

**Viés conhecido: inflação continental (hipótese pré-registrada).** O Elo não
pondera força de adversário — seleções CAF/AFC acumulam pontos em eliminatórias
continentais contra adversários fracos e o ranking infla (snapshot 11/06/2026:
Marrocos 2º, Nigéria 3º, Brasil 18º). A correção (prior FIFA como regularização
DENTRO do MLE — nunca blend em tempo de inferência, que descalibraria b/alpha
silenciosamente; nunca odds de outright, que injetariam o mercado no modelo e
matariam o CLV por vazamento de label) foi deliberadamente adiada pra v2.0:
trocar um viés mensurável por um motor não validado com o torneio rolando seria
pior. Em vez disso o viés virou experimento: hipótese direcional, população,
métrica e critério de decisão (IC 95% do CLV por bootstrap) estão PRÉ-REGISTRADOS
no `HANDOFF.md` ("Hipótese pré-registrada #1"), fixados antes de qualquer jogo
liquidar — em julho a avaliação é confirmatória, não post-hoc.

Por que 4 e não 2: corte/janela curta **achata** os ratings (todos partem de
1500 e ~30 jogos em 2 anos não convergem — o Brasil cai a ~1660, colado na
África do Sul). E half-life de 2 anos super-pondera um único torneio recente
(Marrocos vira #1 do mundo). 4 anos reage a forma mantendo sanidade do ranking.
É 1 linha no config — `null` desliga o decay.

**Gols esperados (Binomial Negativa + Dixon-Coles):** a base é NB em vez de
Poisson — gols de seleção têm variância > média (goleadas), e o parâmetro de
dispersão α engorda a cauda sem distorcer placares comuns (Var = μ + αμ²; α→0
recai no Poisson). Sobre ela, a correção de Dixon-Coles (ρ) ajusta as quatro
células de placar baixo, devolvendo a massa de empate que a independência perde.
Calibração por MLE dos quatro parâmetros (a, b, α, ρ) via `scipy.optimize`, com
região de validade (τ>0) e fallback — o Newton manual de 2 parâmetros não escala
para isso. Nos dados recentes: α≈0.16 (overdispersion confirmada), ρ≈−0.03.

**Mercado purificado (Shin):** as odds do Sofascore convertidas em probabilidade
implícita somam >100% (overround da casa). O método de Shin estima z, a fração de
dinheiro informado, e remove a margem melhor que a normalização proporcional —
corrige o favorite-longshot bias. O painel do `predict` compara modelo vs mercado
e sinaliza divergência ≥5pp. Leitura honesta: o mercado é eficiente, então
divergência grande costuma acusar o modelo, não achar valor — é auditor tanto
quanto detector.

**Simulação de torneio (Monte Carlo):** o `simulator` monta a Copa a partir das
fixtures (grupos derivados do grafo de confrontos, sem hardcode), amostra placares
da NB e roda N torneios → P de avançar, chegar a cada fase, ser campeã. Fatores
contextuais: incentivo (Gijón — corte de λ quando o empate classifica os dois) e
expulsão (versão pragmática por taxa-base; a temporal minuto-a-minuto fica como
sub-projeto). O bracket usa emparelhamento sorteado, não o chaveamento oficial
2026 dos melhores terceiros.

**Backtest (Quality Gate).** Replica a passada forward do Elo (sem lookahead —
cada rating só vê o passado) e aposta valor com stake fixo. Gatilho =
`P_modelo > 1/odd` (o preço ofertado, com vig) — **não** `P_modelo > Shin`:
bater o Shin sem bater o preço é sangrar para a margem, o falso positivo
numérico clássico. Params em modo `frozen` (calibrados só com jogos anteriores à
janela de teste); walk-forward fica como evolução quando a cobertura justificar
o custo. Saída em duas camadas: ledger por aposta (tabela `backtest_bets` + CSV,
com os dois edges, λs, flags de longshot/big-edge e procedência dos params) e
relatório de calibração por faixa de edge — modelo genial é *calibrado*, não
sortudo. Stake fixo isola a variável: Kelly entraria depois, só para alavancar
um edge já provado. Regra de promoção: qualquer mudança no motor (xG incluso)
só vai pra main se mover o P&L na mesma amostra.

**Janela de edge apostável (`min_edge`/`max_edge`).** O backtest provou que o
modelo sangra nas duas extremidades: edge < `min_edge` (default 2%) é ruído
engolido pelo vig; edge > `max_edge` (default 15%) não é falha do mercado, é
informação ausente no modelo (lesão, time poupado). A aposta só entra na janela
do meio — o sweet spot. Ambos no `config.yaml` (`backtest`).

**Dois mercados (1X2 + Over/Under).** O motor já gera a matriz bivariada inteira,
então auditar só o vencedor desperdiçava a maior virtude da Binomial Negativa. O
backtest faz uma segunda passada no mercado de totais (linha 2.5, configurável) e
o ledger marca cada aposta com `market`, separando o P&L de gols do P&L de
vencedor. Mercados de totais em seleções costumam ser menos eficientes que o 1X2
— é onde a borda real tende a aparecer.

**Abertura, fechamento e CLV.** As colunas `odds_*` no `sofascore_matches` têm
semântica de *fechamento* (a última leitura sempre sobrescreve); as colunas
`*_open` guardam a *primeira odd observada pré-apito* e são write-once
(`COALESCE` no upsert — coleta posterior não destrói a foto). Jogo já encerrado
na primeira observação ⇒ abertura desconhecida (`NULL`), nunca o fechamento
disfarçado. Toda coleta também vira linha na tabela append-only `odds_snapshots`
(série temporal completa, pra plotar movimento de linha e validar contra sharp
books no futuro). O backtest aposta na abertura quando ela existe (fallback pro
fechamento na base histórica; `bet_at` marca a população) e liquida o P&L no
preço pactuado. A régua definitiva é o **CLV** = odd pactuada × probabilidade
Shin do fechamento − 1: variância baixíssima, atinge significância com dezenas
de apostas — é ela que decide se o modelo antecipa o mercado. Atenção: na
população `bet_at='close'` o CLV é tautológico (≈ −vig por construção); sinal
só na população `open`, que nasce do cron rodando nos fixtures de 2026.
Operacional: odds de fixture futuro NUNCA passam pelo cache de disco (dado
temporal — cache congelaria o preço de dias atrás e mataria a coleta em dois
tempos); só evento `finished` é cacheado. **Migração one-time:** se já houver
JSONs de odds de fixtures 2026 em `data/sofascore_cache/` coletados antes
dessa regra, apague-os (são fotos velhas que virariam fechamento falso).

**Bootstrap de significância (`src/bootstrap.py`).** Reamostra o ledger 1000×
com reposição e imprime o IC 95% da média (ROI por fatia; CLV só na população
`open`). IC que cruza o zero = ainda não há evidência — transforma história
convincente em decisão defensável. Knobs em `backtest.bootstrap_*`.

**Suíte de testes (`tests/`, `pytest`).** Cobre as peças onde um bug é silencioso
e caro, não o trivial: o método de Shin (overround removido, longshot bias
penalizado, soma 1 em 2 e 3 saídas), a assíntota do motor (Binomial Negativa com
α→0 e rho=0 colapsa na Poisson clássica — comprova o embasamento, não só a
calibração), a contabilidade do CLV/ledger (P&L no preço pactuado, `bet_at`
open/fallback, CLV vs Shin do fechamento), e os invariantes de banco que blindam
o CLV (write-once da abertura via COALESCE, idempotência do `odds_snapshots`).
Tudo roda em milissegundos sem tocar disco nem rede — os testes de banco usam
`db.connect(":memory:")`, exercitando schema/migração/upsert reais. Roda na rede
da Volvo sem bloqueio (não fala com o Sofascore). `pytest.ini` trava a descoberta
em `tests/` (sem isso o pytest escaneia a máquina inteira). Fora da suíte por ora:
walk-forward, gate de ROI em CI (o número ainda é ruidoso demais pra ser
assertion — só depois do CLV acumular).

**Cobertura honesta:** o ROI só significa algo nas centenas de apostas — com só
a Copa 2022 coletada (64 jogos), é ruído; engorde `sofascore.competitions`
(Euro, Copa América, eliminatórias) antes de lê-lo como veredito. O CLV inverte
essa economia: converge com dezenas de apostas, mas exige abertura capturada
pré-apito — ou seja, só nasce do cron rodando nos fixtures de 2026. Até lá, o
`bootstrap` vai mostrar os ICs do ROI cruzando o zero — isso é o esperado, não
um defeito.

**Storage SQLite:** arquivo único, UPSERT nativo, rodar a ingestão N vezes
produz o mesmo estado. O dataset fonte já traz os fixtures futuros (placar
NULL), que ficam separados do conjunto de treino pela própria query.

## Estabilidade e observabilidade

Camada de casca para operação contínua, toda em stdlib (sem dependência nova):

**Concorrência (WAL).** O `db.connect` ativa `PRAGMA journal_mode=WAL` +
`busy_timeout=30000`. Leitor (CLI, simulador) e escritor (ingest, cron) operam
em paralelo sem `database is locked` — o escritor espera em vez de abortar. É
permanente: fica gravado no arquivo do banco.

**Resiliência de rede (`net.py`).** Decorator de retry com backoff exponencial
no `_fetch` do Sofascore e no `_download` do `ingest`. Um timeout transitório de
madrugada é re-tentado (4×, espera dobrando) antes de desistir, em vez de matar a
coleta. O 404 não re-tenta — é resposta válida, não falha. O retry fica fora do
cache: cache hit nunca dispara rede.

**Logging estruturado (`obs.py`).** Logger `wc` com dois destinos: console limpo
(INFO) para o operador e `data/wc.log` rotativo (DEBUG, 3×1MB) para investigar a
falha das 3h da manhã com carimbo de hora e severidade. Substitui os `print`
espalhados — stdlib `logging`, não `loguru` (dep nova é superfície de
supply-chain à toa quando a stdlib resolve).

## Estrutura

```
config.yaml             parâmetros (fonte, K-factors, calibração, sofascore) — zero hardcode
src/db.py               schema + upsert idempotente + cache + WAL (concorrência)
src/net.py              retry com backoff exponencial (stdlib, sem dependência)
src/obs.py              logging estruturado: console + data/wc.log rotativo
src/ingest.py           download (com retry), normalização, carga (resultados)
src/sofascore.py        cliente Sofascore (curl_cffi + CA do Windows p/ TLS corporativo)
src/ingest_sofascore.py coletor Sofascore (xG, odds, notas; inclui fixtures futuros)
src/ingest_fbref.py     coletor FBref (stats agregadas de jogador)
src/ratings.py          engine de Elo com decay
src/model.py            Binomial Negativa + Dixon-Coles + calibração MLE (scipy)
src/math_utils.py       método de Shin (remoção de overround)
src/cron_update_models.py  batch: recalcula e materializa o cache
src/predict.py          CLI (lê cache; painel modelo vs mercado)
src/simulator.py        Monte Carlo do torneio + fatores contextuais
src/backtest.py         Quality Gate: value bets, ledger auditável, calibração, CLV
src/bootstrap.py        IC 95% por bootstrap sobre o ledger (ROI e CLV)
src/status.py           painel do estado do banco, do cache e do backtest
pytest.ini              escopo de descoberta travado em tests/ (sem escanear o disco)
requirements-dev.txt    pytest (separado do runtime, mesma regra que recusou loguru)
tests/test_math.py      Shin (overround, longshot bias) + contabilidade do CLV/ledger
tests/test_model.py     assíntota NB→Poisson (α→0, rho=0) + somas de probabilidade
tests/test_db.py        invariante COALESCE (write-once da abertura) + idempotência de snapshots
tests/test_simulator.py derive_groups: componentes de 4 do grafo de fixtures (sem hardcode)
```

Fonte de dados: [martj42/international_results](https://github.com/martj42/international_results)
(~49k partidas desde 1872, atualizado continuamente).
