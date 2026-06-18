# wc-predictor-v2 — Shadow Deployment (NÃO é a produção)

> Este repositório é um **clone-sombra** do `wc-predictor` de produção, criado em
> 2026-06-16 para aplicar os fixes da auditoria **sem tocar na produção** enquanto o
> cron da Copa 2026 coleta aberturas de odds (dado irreproduzível, até ~19/07).
> O README.md herdado é o do projeto original — **a verdade sobre este clone está aqui.**

## Por que existe
A produção (`../wc-predictor`) está **PARKED**: mexer no `db.sqlite` enquanto o cron
escreve seria catastrófico. Este shadow permite implementar e testar as melhorias
matemáticas consumindo os dados vivos **em modo somente-leitura**, sem a menor chance
física de corromper o arquivo de produção.

## Trava de segurança
`src/db.py` → `connect(db_path, read_only=True)` monta o banco em `mode=ro` (URI SQLite)
+ `PRAGMA query_only=ON`: **fisicamente incapaz de escrever**. Ao rodar ao vivo, aponte
para `../wc-predictor/data/matches.db` com `read_only=True`.
⚠️ Ressalva operacional: ler um banco WAL **com escritor ativo** em `mode=ro` tem
caveats (acesso ao `-shm`); validar ao apontar para a produção viva.

## Fixes da auditoria aplicados aqui (não na produção)
- **Simulador (`simulator.py`):** `seed` (reprodutibilidade) + amostragem da **grid
  corrigida por Dixon-Coles** (antes: duas NB independentes, perdia massa de empate).
- **Backtest (`backtest.py`):** **paridade train/serve** — aplica a mesma janela do cron
  (`window_years` no Elo, `calibration_window_years` nos params); antes media um modelo
  diferente do servido.
- **Telemetria:** `emit_event` (predictor_core) emite `backtest_completed` (ROI/CLV).
- Consome o `predictor_core` via `vendor/` (3º consumidor da plataforma).

**Suíte: 81 testes verdes** (`python -m pytest tests/ -q`), incluindo o teste de
rejeição de escrita read-only e os fixes acima.

## PROMOÇÃO (pendente — pós-Copa)
Depois de ~19/07/2026 (fim da coleta da Copa), com o mandato de auditoria suspenso:
promover estes fixes à produção `wc-predictor` (merge/replace) e descomissionar o shadow.
**Enquanto a Copa rolar, NÃO promover.**
