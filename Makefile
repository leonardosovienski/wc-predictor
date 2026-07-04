# wc-predictor-v2 — atalhos dos comandos do projeto.
# Uso: `make <alvo>`. `make help` lista tudo. Precisa de GNU make no PATH.
# PY: sobrescreva o interpretador se precisar (ex.: `make test PY="py -3.12"`).
PY ?= python

.DEFAULT_GOAL := help
.PHONY: help install install-dev ingest sofascore fbref seasons cron \
        predict fixtures rankings simulate backtest bootstrap status test clean

help:  ## Lista os alvos disponíveis
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	 awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

# --- setup ---
install:      ## Instala dependências de runtime
	$(PY) -m pip install -r requirements.txt
install-dev:  ## Instala dependências de desenvolvimento (pytest)
	$(PY) -m pip install -r requirements-dev.txt

# --- pipeline de dados ---
ingest:    ## Baixa ~49k jogos (martj42) → SQLite
	$(PY) -m src.ingest
sofascore: ## Coleta odds/xG/notas do Sofascore (rede limpa)
	$(PY) -m src.ingest_sofascore
fbref:     ## Coleta stats de jogador do FBref
	$(PY) -m src.ingest_fbref
seasons:   ## Descobre season_id de um ut_id — uso: make seasons UT=16
	$(PY) -m src.ingest_sofascore --seasons $(UT)
cron:      ## Recalcula Elo + calibra params → cache (rode após cada ingest)
	$(PY) -m src.cron_update_models

# --- previsão / serving ---
predict:  ## Prevê um confronto — uso: make predict A="Brazil" B="France" [NEUTRAL=1]
	$(PY) -m src.predict $(A) $(B) $(if $(NEUTRAL),--neutral,)
fixtures: ## Prevê os próximos N fixtures — uso: make fixtures N=8
	$(PY) -m src.predict --fixtures $(N)
rankings: ## Top N do Elo — uso: make rankings N=20
	$(PY) -m src.predict --rankings $(N)

# --- simulação ---
simulate: ## Monte Carlo da Copa — uso: make simulate N=10000
	$(PY) -m src.simulator $(N)

# --- backtest / significância ---
backtest:  ## P&L + CLV vs odds → ledger backtest_bets
	$(PY) -m src.backtest
bootstrap: ## IC 95% do ROI e do CLV (rode após backtest)
	$(PY) -m src.bootstrap

# --- diagnóstico / testes ---
status: ## Painel do estado do banco e do cache
	$(PY) -m src.status
test:   ## Roda a suíte de testes
	$(PY) -m pytest tests/ -q

clean:  ## Remove caches de bytecode e do pytest
	rm -rf .pytest_cache $$(find . -type d -name __pycache__)
