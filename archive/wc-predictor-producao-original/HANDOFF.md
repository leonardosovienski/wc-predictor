# wc-predictor — Handoff de Contexto

Documento para retomar o desenvolvimento em um chat novo. Anexe o `wc-predictor.zip`
junto com este arquivo.

---

## O que é o projeto

Sistema CLI em Python que prevê resultados da Copa do Mundo 2026. Roda 100% local
(Python + SQLite, sem cloud). Idioma do projeto: português. Fonte de resultados:
`martj42/international_results` (~49k jogos desde 1872, inclui os fixtures de 2026).

Máquina do Leo: Windows, em `C:\Users\A538382\Downloads\wc-predictor\wc-predictor\`,
com venv `.venv`, atrás de proxy corporativo Volvo com inspeção TLS (resolvido no
código). O sandbox do Claude alcança só GitHub/PyPI — não alcança Sofascore/FBref,
então a coleta dessas fontes só roda na máquina do Leo.

## Tom e regras de trabalho (importante)

- Direto, técnico, sem preâmbulo. Nomear tradeoffs e deixar a decisão com o Leo.
- Honestidade de engenharia acima de tudo: nunca documentar como "feito" o que é
  plano; apontar quando a doc descreve algo que o código não faz.
- Pipeline como código, versionado. Sem governance debt. Idempotência por padrão.
  Segredos em env/secret manager, nunca hardcoded. Observabilidade desde o início.
- Arquitetura antes de implementação. Explicar o *porquê* das decisões.
- Quando o Leo manda um documento de "próximos passos", o padrão é: ler, separar o
  que é sólido do que é otimização prematura, propor a sequência por leverage/risco
  (não pela ordem do documento), e implementar só após o sinal verde.

---

## Estado atual: o que ESTÁ feito e validado

Arquitetura em camadas, toda testada com dados reais no sandbox:

**Coleta**
- `ingest.py` — resultados do martj42 (GitHub CSV), idempotente, com retry e
  fallback local. ~49.398 jogos + 72 fixtures de 2026.
- `sofascore.py` + `ingest_sofascore.py` — cliente curl_cffi (impersonate Chrome,
  contorna Cloudflare; exporta o cofre de certificados do Windows pro TLS
  corporativo). Coleta placar, xG, odds 1X2, **odds Over/Under 2.5** e notas de
  jogador. Suporta fixtures futuros (só odds). Na máquina do Leo, a Copa 2022 já
  foi coletada (64 jogos, xG 64/64, odds 64/64) — mas isso foi ANTES das colunas
  Over/Under, então precisa recoletar pra preencher odds_over/odds_under.
- `ingest_fbref.py` — coletor secundário de stats agregadas de jogador. NOTA: FBref
  perdeu a licença Opta em jan/2026, o xG sumiu de lá — por isso o Sofascore virou
  a fonte principal de xG.

**Motor estatístico** (`model.py`, `ratings.py`)
- Elo com decay por meia-vida (`form_half_life_years: 4`) + corte de janela
  (`window_years: 6`), home advantage +100. Elo é forward-only (sem lookahead).
- Gols por **Binomial Negativa** (overdispersion, Var=μ+αμ²) + correção
  **Dixon-Coles** (ρ nas 4 células de placar baixo). Calibração MLE dos 4
  parâmetros (a, b, α, ρ) via scipy.optimize, com região de validade e fallback.
  Calibrado nos dados: α≈0.159 (overdispersion confirmada), ρ≈−0.033 (sobe empates).
- `predict_match` expõe a grade bivariada inteira (`grid`) — usada pelo simulador e
  pelo backtest de Over/Under.

**Cache de serving** (`cron_update_models.py`, tabelas `current_elo` + `model_parameters`)
- Materializa Elo + params. A CLI lê em vez de recalcular: 257ms → 1ms (262×).
- Carimbo de `config_hash` + `n_matches` detecta staleness; a CLI avisa "rode o cron".
- REGRA OPERACIONAL: rodar `cron_update_models` após CADA `ingest`/`ingest_sofascore`.

**Mercado** (`math_utils.py`)
- Método de **Shin**: remove o overround das odds estimando z (dinheiro informado),
  corrige favorite-longshot bias melhor que normalização proporcional.
- `predict.py` compara modelo vs mercado purificado e sinaliza divergência ≥5pp.

**Simulador** (`simulator.py`)
- Monte Carlo do torneio. 12 grupos derivados do grafo de confrontos (sem hardcode).
  Amostra placares da NB. Módulo de incentivo (Vergonha de Gijón — corte de λ 35%
  quando empate classifica os dois) e de expulsão (versão pragmática por taxa-base).
- Aproximações conhecidas e documentadas: bracket por sorteio (não o chaveamento
  oficial 2026 dos melhores terceiros); expulsão sem dados de cartão por minuto.
- ~3000 sims/1.8s. Campeões sãos: Espanha ~16%, Marrocos ~14%, Argentina ~6%.

**Abertura/Fechamento + CLV** (`db.py`, `sofascore.py`, `ingest_sofascore.py`, `backtest.py`)
- Colunas `odds_*` = FECHAMENTO (última leitura sobrescreve); `*_open` = primeira
  odd observada PRÉ-apito, write-once via COALESCE no upsert. Jogo já encerrado na
  primeira observação ⇒ open=NULL (abertura desconhecida, nunca close disfarçado —
  evitaria CLV tautológico). Tabela `odds_snapshots` append-only (event, captured_at,
  market, selection, odd, pre_match) guarda a série temporal completa de cada coleta.
- Cache do Sofascore agora é condicional: `event_odds(eid, finished=...)` — odd de
  fixture futuro NUNCA passa pelo cache de disco (dado temporal); só evento finished
  é cacheado. MIGRAÇÃO ONE-TIME PENDENTE na máquina do Leo: apagar os
  `event_*_odds_1_all.json` dos fixtures 2026 (season 58210) em data/sofascore_cache/
  — foram gravados sob a regra antiga e virariam fechamento falso.
- Backtest aposta na ABERTURA quando existe (fallback close na base histórica;
  coluna `bet_at` separa as populações), liquida P&L no preço pactuado, e calcula
  `clv = odd_pactuada × p_shin_close − 1` + `beat_close`. Shin sempre no fechamento.
  Relatório separa CLV por população e avisa: bet_at='close' é tautologia (≈ −vig
  por construção; validado no sandbox: −6.07% médio, 0% beat) — sinal só em 'open'.
- `bootstrap.py` (novo): IC 95% percentílico, 1000 reamostragens (config
  `backtest.bootstrap_iterations`/`bootstrap_seed`), sobre ROI (total/mercado/faixa
  de edge) e sobre CLV restrito à população 'open'. `python -m src.bootstrap` após
  o backtest. Itens 1 e 2 da lista de prioridades anterior: FEITOS e validados
  end-to-end no sandbox (ingest real + odds sintéticas pra exercitar os caminhos).

**Backtest / Quality Gate** (`backtest.py`)
- Replica a passada forward do Elo e aposta valor com **stake fixo**.
- GATILHO = EV ao preço: `P_modelo > 1/odd` (implícita bruta, com vig). NÃO
  `P_modelo > Shin` (bater o Shin sem bater o preço = sangrar pro vig = falso
  positivo numérico). O ledger guarda os dois edges pra auditoria.
- **Janela de edge** `min_edge`/`max_edge` (config, default 2%/15%): estanca ruído
  (baixo) e informação ausente (alto). Validado: nenhuma aposta sai da janela.
- **Dois mercados**: 1X2 + Over/Under 2.5. Ledger marca `market` (`1x2`/`ou25`),
  relatório separa o P&L de gols do P&L de vencedor.
- Params em modo `frozen` (calibra só antes da janela de teste — corte de lookahead).
- Saída: tabela `backtest_bets` + CSV + relatório de calibração por faixa de edge.

**Suíte de testes** (`tests/`, `pytest`) — primeira leva, 20 testes verdes
- Cobre o que é silencioso e caro, não o trivial. `test_math.py`: Shin (overround
  removido, longshot bias penalizado, soma 1 em 2 e 3 saídas) + contabilidade do
  CLV/ledger (`_settle`: P&L no preço pactuado, `bet_at` open/fallback, CLV vs Shin
  do fechamento, rejeição fora da janela de edge). `test_model.py`: assíntota
  NB→Poisson (α→0 E rho=0 colapsa no Poisson clássico — rho=0 é obrigatório, senão
  Dixon-Coles desvia nos cantos). `test_db.py`: write-once da abertura (COALESCE) e
  idempotência do `odds_snapshots`, via `db.connect(":memory:")` real (schema +
  migração + upsert verdadeiros, sem disco). `test_simulator.py`: `derive_groups`
  acha componentes de 4 do grafo de fixtures (mock round-robin em :memory:).
- Tudo roda em ms, sem disco nem rede — RODA NA REDE DA VOLVO (não fala com Sofascore).
- `pytest.ini` trava descoberta em `tests/` (sem isso o pytest escaneia a máquina —
  foi o loop infinito da depuração). `conftest.py` injeta a raiz no sys.path (funciona
  sem .venv, que o EDR corporativo quarentenou). `pytest` em `requirements-dev.txt`
  separado do runtime (mesma regra que recusou loguru).
- Guard de odds AO VIVO (`is_pre_match` em ingest_sofascore): abertura e
  snapshot pre_match=1 só quando start_ts > now (estritamente pré-apito).
  "não terminou" era insuficiente — jogo em andamento também não terminou, e
  odd in-play gravada como open contaminaria a população do CLV. Sem start_ts,
  assume não-pré-jogo (conservador). Coberto por 4 testes (fronteiras incluídas).
  Import do cliente HTTP virou lazy dentro de run(): parsers/guard são puros e
  testáveis sem curl_cffi instalado.
- LIÇÃO REGISTRADA: a primeira tentativa (gerada de outro chat) inferiu nomes de
  função do README (`calculate_shin_probabilities`, `build_groups_from_fixtures`) que
  NÃO existem — deu ImportError. Nomes reais: `shin_probabilities` (tupla de 3),
  `predict_match` (α é params[2]), `_settle` (10 posicionais), `derive_groups`. Regra
  do projeto confirmada na prática: teste se escreve lendo o fonte, não a doc.

**Casca de estabilidade/observabilidade** (stdlib, sem dependência nova)
- `db.py`: WAL (`journal_mode=WAL` + `busy_timeout=30000`) — resolve `database is
  locked` entre leitor (CLI/simulador) e escritor (cron/ingest). Migração idempotente
  de schema (bancos antigos ganham colunas novas no `connect`, sem recriar).
- `net.py`: retry com backoff exponencial (decorator) no Sofascore e no download do
  ingest. 404 não re-tenta (resposta válida). Retry fica fora do cache.
- `obs.py`: logging estruturado (console INFO + `data/wc.log` rotativo DEBUG).
  Escolha consciente: stdlib `logging`, não loguru (evitar dep nova).

## Estado atual: o que NÃO está feito (decisões já tomadas, não implementadas)

Ordenado por prioridade já acordada com o Leo (por leverage/risco, não beleza).
NOTA: CLV, bootstrap E a primeira suíte de pytest estão FEITOS — ver seção acima.
Hipótese descartada com evidência: a rota `odds/1/all` do Sofascore NÃO traz
`initialFractionalValue` (verificado no cache do Leo) — abertura retroativa de
2022/2024 é impossível; abertura real só nasce do cron pré-apito.

1. **Operação do cron pré-apito (a abertura é a primeira foto que tiramos).**
   Agendar `ingest_sofascore` + `cron_update_models` em janela T-72h dos jogos de
   2026, com passadas adicionais até o apito (enriquecem o odds_snapshots). Antes
   da primeira rodada: a limpeza one-time do cache de odds 2026 (ver acima) e a
   recoleta de 2022 (agora re-busca odds da rede, ~96s — preenche Over/Under).
   RODA EM REDE LIMPA (ver Topologia de Rede): o Sofascore dá 403 atrás do proxy.
   Com o guard in-play, rodar durante uma partida não contamina abertura — mas a
   janela boa é manhã (jogos do torneio são tarde/noite nas Américas). URGÊNCIA:
   a Copa começou em 11/06/2026 — cada jogo iniciado sem coleta prévia é uma
   abertura perdida pra sempre; a primeira passada vira o open de todos os
   fixtures ainda não iniciados.

2. **Segunda leva de pytest — gaps mapeados (pós-coleta, ~1h):**
   `_find_odds`/`_canon` é o gap MAIS PERIGOSO: faz o casamento odds↔jogo e o
   SWAP de orientação quando home/away divergem entre fontes — um bug ali aposta
   na odd do time errado sem exceção nenhuma, ledger plausível e P&L/CLV lixo.
   Depois: `frac_to_decimal`/`parse_odds`/`parse_ou` (fronteira com formato
   externo: fração malformada, decimalValue ausente, linha OU inexistente),
   `ci_mean` (IC contém a média; amostra constante colapsa o IC), e Elo/ratings
   (conservação de pontos, decay regride à média). Tudo função pura, barato.

3. **Ampliar cobertura de odds históricas.**
   O config já tem o roteiro comentado (Euro 2024 ut_id=1, Copa América 2024
   ut_id=133) — descobrir season_id via `--seasons UT_ID`, descomentar, recoletar.
   64 jogos é ruído pro ROI; o CLV não depende disso (depende do cron de 2026).

4. **CI/CD com gate de teste (não de ROI).**
   A suíte de pytest já é o pré-requisito cumprido. Próximo passo natural: rodar
   `pytest` num gate antes de merge. Gate de ROI continua RECUSADO até o CLV
   acumular (o número ainda é ruidoso demais pra ser assertion).

## Estado validado na máquina do Leo (11/06/2026)

- Suíte: 24/24 verdes, Python 3.13.7 win32, pytest 9.0.3 (Camada 1 provada).
- `ingest`: 49.403 jogos (1872→2026-06-10), 72 fixtures futuros da Copa.
- `cron_update_models`: 262 times | a=0.224 b=1.060 alpha=0.1576 rho=-0.0350,
  6022 jogos na janela (params plausíveis pra futebol — referência de sanidade
  pra recalibrações futuras: desvio grande disso merece investigação).
- `predict`/`simulator`: rodaram coerentes; ranking exibiu o viés continental
  que motivou a Hipótese #1 abaixo.
- PENDENTE: `sofascore_matches` VAZIA — a coleta de odds (rede limpa) nunca
  rodou neste banco. Backtest/bootstrap end-to-end só foram validados em sandbox
  com odds sintéticas. O selo de integração real depende da primeira coleta.

---

Nota de auditoria (2026-06-18): ver `AUDIT_README.md` na raiz. Durante a sessão
de auditoria global foram confirmados cobertura de 2024 em `predictor-stocks` e
re-ingest de 2025 para completar o histórico; ver `predictor-stocks/check_db.py`
para inspeções rápidas do SQLite.

## HIPÓTESE PRÉ-REGISTRADA #1 — inflação continental do Elo (11/06/2026)

Registrada ANTES de qualquer jogo da Copa 2026 liquidar no ledger. O propósito do
pré-registro é metodológico: transformar a avaliação de julho de análise post-hoc
(achar padrões depois de ver os dados) em teste confirmatório (predição feita às
cegas, verificada depois). NÃO editar esta seção após o início da liquidação —
apêndices com a avaliação vão ABAIXO, nunca reescrevendo a predição.

**Contexto observado (pré-torneio, sem nenhuma odd no ledger):** o ranking Elo do
motor (`predict --rankings`, base de 11/06/2026, 6022 jogos na janela de
calibração) coloca Marrocos 2º, Nigéria 3º, Argélia 5º, com Brasil 18º e
Alemanha 17º. Causa suspeita: o Elo caseiro não pondera força de adversário —
seleções CAF/AFC acumulam pontos em eliminatórias continentais contra adversários
fracos; CONMEBOL/UEFA jogam contra adversários fortes e não inflam. Solução
arquitetural (prior FIFA como regularização DENTRO do MLE, nunca blend no
`_lambdas` — ver decisão recusada abaixo) adiada deliberadamente pra v2.0 pra
não trocar um viés mensurável por um motor não validado com a bola rolando.

**Predição direcional:** o modelo SUPERESTIMA seleções das confederações CAF e
AFC. Consequência observável: o backtest vai enxergar "valor" nas odds dessas
seleções, registrar apostas a favor delas, e o mercado não vai acompanhar.

**População de teste (definida agora, sem ver dados):** apostas do ledger
(`backtest_bets`) da Copa 2026 com `bet_at='open'`, mercado `1x2`, cuja seleção
(`selection`=home/away) aponta pra um time filiado à CAF ou à AFC (mapeamento
time→confederação feito na análise; filiação é fato público, não juízo).
População de controle: as demais apostas `1x2` `bet_at='open'` (UEFA/CONMEBOL/
CONCACAF/OFC).

**Métrica e critério de decisão (fixados agora):** CLV médio da população de
teste, IC 95% por percentile bootstrap (1000 reamostragens, seed 13 — os defaults
de `src/bootstrap.py`; usar `ci_mean` importado, filtrando o ledger por time).
- IC inteiro ABAIXO de zero → hipótese CONFIRMADA (viés provado fora da amostra).
- IC inteiro ACIMA de zero → hipótese REFUTADA (o Elo cru via valor real onde o
  mercado errava — resultado ainda mais interessante).
- IC cruzando zero → INCONCLUSIVO: "consistente com viés, amostra de uma Copa
  não basta pra cravar". Isto TAMBÉM é um resultado válido e é o mais provável
  dado n pequeno — declarar inconclusivo é obrigatório, não fraqueza. Não
  rebaixar o critério depois de ver os números.

**Observável secundário (não decisório):** concentração de `edge_vs_shin`
positivo em seleções CAF/AFC versus controle — mede onde o modelo "vê valor",
independente da liquidação.

**Decisão recusada que motivou isto:** blend de Elo com odds de outright
(vazamento de label: injeta o mercado no modelo e o CLV passa a medir o mercado
contra ele mesmo) e blend FIFA direto no `_lambdas` em tempo de inferência
(coeficientes b/alpha do MLE convergiram pra OUTRA distribuição de input —
descalibração silenciosa). Prior FIFA correto = regularização na perda do MLE,
com normalização de escala e validação de nomes contra o banco. Fica pra v2.0,
pós-Copa, com A/B contra o Elo cru.

## Roadmap de longo prazo (acordado, ordem por dependência)

- **Dividir o Elo em Ataque/Defesa** (dois vetores: λ cruza Elo_ataque_casa ×
  Elo_defesa_fora). É o projeto GRANDE — reescreve `ratings.py` e `model.py` e
  INVALIDA a calibração atual (α, ρ). Só fazer DEPOIS que o instrumento de medida
  estiver largo (Over/Under no backtest — FEITO) e a régua confiável (CLV). Princípio
  que guiou isso: "primeiro amplie o que você mede, depois mude o que você modela."
- **Features físicas no Elo**: rest advantage (dias de descanso, determinístico do
  calendário) e altitude (La Paz/Quito nas eliminatórias). Baratas, encaixam no Elo
  ataque/defesa depois.
- **Kelly fracionado**: sizing entra só DEPOIS que o CLV provar o edge. Kelly sobre
  edge não-validado acelera a quebra.
- **Conectar dado de jogador (Bottom-Up)**: xG/notas do FBref+Sofascore (ociosos no
  banco) ajustando a força. Resolve o sangramento da faixa >15% (informação ausente:
  lesão, time misto). Projeto grande, depende de lineup em tempo real.

## Coisas conscientemente RECUSADAS (não são esquecimento)

- **Docker**: problema de distribuição que não existe (roda só na máquina do Leo).
- **CI/CD com gate de ROI**: o número ainda é ruidoso demais pra ser assertion —
  viraria gerador de falso-vermelho. Só depois do CLV dar métrica confiável.
- **Pydantic / data contracts**: robustez contra evento raro, não estabilidade do
  dia a dia. Vem depois de rede+concorrência (os problemas frequentes).
- **loguru / tenacity**: dep nova é superfície de supply-chain quando a stdlib resolve.
- **Playwright / automação de browser pro Sofascore**: ver Topologia de Rede abaixo —
  custo de manutenção (seletores quebram a cada update) num projeto deliberadamente
  enxuto, pra contornar uma restrição de rede que tem solução operacional trivial.

## Topologia de Rede e Sincronização (decisão de arquitetura)

**O problema:** a rede corporativa da Volvo faz inspeção TLS (proxy descriptografa e
re-criptografa o tráfego). Isso reescreve o ClientHello, então o fingerprint JA3/JA4
do pacote deixa de bater com o do Chrome que resolveu o desafio Cloudflare e ganhou o
`cf_clearance`. O WAF do Sofascore cruza cookie válido + User-Agent de Chrome +
assinatura TLS de proxy corporativo e conclui session hijacking → 403 imediato.
`curl_cffi` não vence isso por construção: ele forja o fingerprint no socket, o proxy
o desfaz no salto seguinte. Diagnóstico fechado, não é bug do código.

**A decisão:** a coleta do Sofascore roda FORA da rede da Volvo (rede pessoal em
Araucária, ou tethering 4G com a VPN cliente comprovadamente desligada — testar com
`curl -v https://www.sofascore.com` e checar se o issuer do cert é CA pública, não CA
da Volvo; se for da Volvo, a VPN ainda está no caminho). Na rede limpa o `curl_cffi`
funciona como projetado, zero código novo.

**Sync UNIDIRECIONAL casa→trabalho.** A máquina externa (casa) é a ÚNICA escritora de
`sofascore_matches` e `odds_snapshots`. A máquina da Volvo é leitora — backtest,
bootstrap, predict, análise. O `matches.db` flui casa→trabalho por cópia simples
(`Copy-Item` por cima). É seguro PORQUE é unidirecional.

**Por que não bidirecional:** o write-once da abertura (COALESCE no upsert) só vale
DENTRO de um banco. Dois bancos que se sobrescrevem não respeitam o COALESCE — copiar
o `.db` errado por cima reintroduz exatamente o bug de abertura que o COALESCE resolve.
Merge real exigiria um script reconciliando por `event_id` com a mesma lógica do
upsert: dívida de manutenção pura pra um ganho que o caso de uso real (casa coleta,
trabalho analisa) não precisa. Recusado a favor do unidirecional.

## Como rodar (Windows, na máquina do Leo)

CASA CANÔNICA DO REPO: `C:\Users\A538382\Downloads\wc-predictor-clv\wc-predictor`
(o banco real vive lá — o diretório antigo do projeto está DEPRECADO, não usar dois
bancos). SEM VENV: o EDR corporativo quarentenou a .venv; tudo roda no Python 3.13
global e está validado assim (suíte 24/24 verde no Py 3.13.7 win32). Se recriar
venv um dia, ok, mas não é pré-requisito.

```powershell
pip install -r requirements.txt           # runtime
pip install -r requirements-dev.txt       # pytest (dev)

# --- NA REDE LIMPA (casa/4G), pois o Sofascore dá 403 atrás do proxy Volvo ---
python -m src.ingest                       # resultados martj42 + cria data/wc.log
python -m src.ingest_sofascore             # odds (Over/Under + xG) — escreve o .db
python -m src.cron_update_models           # materializa cache Elo/params (serving)
# valide aqui ANTES de voltar pra Volvo — here-strings abaixo na seção Verificação

# --- NA REDE VOLVO (só leitura do .db sincronizado) ---
python -m src.predict Brazil France --neutral
python -m src.predict --fixtures 8
python -m src.simulator 10000
python -m src.backtest
python -m src.bootstrap                    # IC 95% do ROI e do CLV (após o backtest)
python -m src.status
```

NOTA: `cron_update_models` materializa Elo/params do `matches`, NÃO as odds — estas já
ficam persistidas assim que `ingest_sofascore` termina. A ordem ingest →
ingest_sofascore → cron_update_models importa pro cache de serving, não pra coleta.

O banco migra sozinho no primeiro `connect` (colunas Over/Under e *_open + tabela
odds_snapshots). Sem recriar nada. One-time: apagar os JSONs de odds dos fixtures
2026 do cache (regra de cache mudou — ver seção Abertura/Fechamento).

---

## Verificação pós-coleta (here-strings PowerShell — @' ... '@ passa literal)

Abertura grudou? (cada linha = um open capturado, matéria-prima do CLV):
```powershell
@'
from src import db
c = db.connect("data/matches.db")
rows = c.execute("SELECT event_id, home_team, away_team, odds_home_open FROM sofascore_matches WHERE odds_home_open IS NOT NULL ORDER BY date LIMIT 10").fetchall()
print(*rows, sep="\n")
'@ | python -
```

Base honesta + snapshots + in-play:
```powershell
@'
from src import db
c = db.connect("data/matches.db")
q = lambda s: c.execute(s).fetchone()[0]
print("2022 close-only (open NULL, correto):", q("SELECT COUNT(*) FROM sofascore_matches WHERE odds_home IS NOT NULL AND odds_home_open IS NULL"))
print("fixtures com abertura:", q("SELECT COUNT(*) FROM sofascore_matches WHERE odds_home_open IS NOT NULL"))
print("snapshots:", q("SELECT COUNT(*) FROM odds_snapshots"))
print("snapshots in-play (pre_match=0):", q("SELECT COUNT(*) FROM odds_snapshots WHERE pre_match=0"))
'@ | python -
```

Write-once na prática (rodar a coleta 2x e conferir):
```powershell
@'
from src import db
c = db.connect("data/matches.db")
print("capturas/evento (esperado 2):", c.execute("SELECT event_id, COUNT(DISTINCT captured_at) FROM odds_snapshots WHERE market='1x2' GROUP BY event_id LIMIT 3").fetchall())
print("close descolou do open em:", c.execute("SELECT COUNT(*) FROM sofascore_matches WHERE odds_home_open IS NOT NULL AND odds_home_open != odds_home").fetchone()[0], "jogos")
'@ | python -
```

Cache condicional (fixture futuro NÃO pode ter JSON de odds cacheado):
```powershell
Get-ChildItem data\sofascore_cache\event_*_odds_1_all.json | Measure-Object
# esperado: só jogos ENCERRADOS (~64 de 2022), não ~136
```

Avaliação da Hipótese #1 (julho, após liquidação — adaptar o filtro de times CAF/AFC):
```powershell
@'
import numpy as np
from src import db
from src.bootstrap import ci_mean
CAF_AFC = {"Morocco","Nigeria","Algeria","Senegal","Egypt","Ivory Coast","Japan","Iran","Australia","South Korea","Saudi Arabia","Qatar"}  # completar com os classificados reais
c = db.connect("data/matches.db")
rows = c.execute("SELECT home, away, selection, clv FROM backtest_bets WHERE bet_at='open' AND market='1x2'").fetchall()
test = [clv for h,a,sel,clv in rows if (sel=='home' and h in CAF_AFC) or (sel=='away' and a in CAF_AFC)]
ctrl = [clv for h,a,sel,clv in rows if not ((sel=='home' and h in CAF_AFC) or (sel=='away' and a in CAF_AFC))]
rng = np.random.default_rng(13)
for nome, pop in (("CAF/AFC", test), ("controle", ctrl)):
    if len(pop) >= 2:
        m, lo, hi = ci_mean(pop, 1000, rng)
        v = "CONFIRMADA" if hi < 0 else ("REFUTADA" if lo > 0 else "INCONCLUSIVA")
        print(f"{nome}: n={len(pop)} CLV {m:+.2%} IC95[{lo:+.2%},{hi:+.2%}] -> {v}" if nome=="CAF/AFC" else f"{nome}: n={len(pop)} CLV {m:+.2%} IC95[{lo:+.2%},{hi:+.2%}]")
'@ | python -
```

## PROMPT PARA O CHAT NOVO

Cole isto no início do chat novo, junto com o `wc-predictor.zip` (o HANDOFF.md já
vai dentro dele, em `wc-predictor/HANDOFF.md`):

> Estou continuando o desenvolvimento do meu projeto wc-predictor (previsão da Copa
> 2026, Python + SQLite, roda local na minha máquina Windows com proxy corporativo
> TLS). Anexei o projeto completo (`wc-predictor.zip`); dentro dele há o
> `HANDOFF.md` com o estado completo, decisões tomadas e roadmap.
>
> Leia o HANDOFF inteiro primeiro — ele tem o tom de trabalho, o que está feito e
> validado, o que falta, e o que foi conscientemente recusado (pra você não me
> sugerir Docker/CI-CD/Pydantic, que já descartamos com motivo).
>
> Tom: direto, técnico, sem preâmbulo. Nomeie tradeoffs e deixe a decisão comigo.
> Honestidade de engenharia acima de tudo — se a doc disser que algo está feito e o
> código não fizer, me avise. Arquitetura antes de implementação.
>
> CLV, bootstrap e a primeira suíte de pytest já estão implementados e validados
> (abertura write-once via COALESCE, snapshots append-only, cache condicional por
> estado do evento, aposta na abertura com fallback, CLV vs Shin do fechamento,
> IC 95%, 20 testes verdes cobrindo Shin/NB-Poisson/CLV/COALESCE/derive_groups). O
> próximo passo acordado NÃO é mais código de feature: é OPERACIONAL — agendar o
> cron de coleta pré-apito (T-72h) dos jogos de 2026, rodando em REDE LIMPA (o
> Sofascore dá 403 atrás do proxy da Volvo; ver Topologia de Rede). Antes da
> primeira rodada: limpeza one-time do cache de odds 2026 e recoleta de 2022.
>
> Antes de codar qualquer coisa: releia os módulos relevantes no zip pra não
> trabalhar em cima da minha memória do código, valide com dados reais quando der, e
> me entregue os arquivos alterados + o zip atualizado no fim. Não precisa me
> perguntar a cada passo — leva o tempo que precisar e calcula bem.
