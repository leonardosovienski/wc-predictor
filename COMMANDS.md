# Comandos — wc-predictor-v2

Referência completa de tudo que se roda no projeto. Há **três formas** de rodar
cada comando — escolha a que preferir:

- **Direto:** `python -m src.<módulo>` (sempre funciona)
- **`tasks.py`** (Python puro, **não precisa de make** — recomendado no Windows):
  `python tasks.py <alvo> [args]`. Rode `python tasks.py` para listar os alvos.
- **`make <alvo>`** (só se tiver GNU make no PATH)

> **Windows/PowerShell:** ative o venv com `.venv\Scripts\activate`. O projeto usa
> **Python 3.12** como canônico (`py -3.12`); com o venv ativo, `python` já aponta pra ele.
> Como `make` normalmente não existe no Windows, prefira `python tasks.py <alvo>`.

---

## 1. Setup do ambiente (primeira vez)

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt      # runtime   | make install
pip install -r requirements-dev.txt  # dev/pytest | make install-dev
```

## 2. Pipeline de dados

| Comando | Make | O que faz |
|---|---|---|
| `python -m src.ingest` | `make ingest` | Baixa ~49k jogos (martj42) → SQLite (+ `data/wc.log`) |
| `python -m src.ingest_sofascore` | `make sofascore` | Coleta odds/xG/notas (rede limpa; sandbox dá 403) |
| `python -m src.ingest_sofascore --seasons 16` | `make seasons UT=16` | Descobre `season_id` de um `ut_id` (16=WC, 1=Euro, 133=Copa América) |
| `python -m src.ingest_fbref` | `make fbref` | Coleta stats de jogador (precisa alcançar fbref.com) |
| `python -m src.cron_update_models` | `make cron` | Elo + calibra params → cache. **Rode após CADA ingest** |

## 3. Previsão / serving

| Comando | Make | O que faz |
|---|---|---|
| `python -m src.predict Brazil France` | `make predict A=Brazil B=France` | Confronto com mando (grava no log) |
| `python -m src.predict Portugal Spain --neutral` | `make predict A=Portugal B=Spain NEUTRAL=1` | Campo neutro (Copa) |
| `python -m src.predict --fixtures 8` | `make fixtures N=8` | Próximos N fixtures da base |
| `python -m src.predict --rankings 20` | `make rankings N=20` | Top N do Elo |

> `predict` exige `TIME_A TIME_B` **ou** `--fixtures` **ou** `--rankings`. Nomes em inglês.
> Toda predição é gravada em `data/predictions.jsonl` (log append-only obrigatório).

## 4. Simulação da Copa

| Comando | Make | O que faz |
|---|---|---|
| `python -m src.simulator` | `make simulate N=10000` | Monte Carlo, 10.000 sims (default) |
| `python -m src.simulator 50000` | `make simulate N=50000` | N simulações |

## 5. Backtest / significância

| Comando | Make | O que faz |
|---|---|---|
| `python -m src.backtest` | `make backtest` | P&L + CLV vs odds → ledger `backtest_bets` + CSV |
| `python -m src.bootstrap` | `make bootstrap` | IC 95% do ROI e do CLV. **Rode após o backtest** |

## 6. Diagnóstico

| Comando | Make | O que faz |
|---|---|---|
| `python -m src.status` | `make status` | Painel: o que cada fonte coletou e o que o modelo usa |

## 7. Testes

```bash
py -3.12 -m pytest tests/ -q   # CANÔNICO do projeto (força Python 3.12)
python -m pytest               # usa pytest.ini (descoberta travada em tests/)
make test                      # atalho (usa $(PY), default python)
```

> O import `predictor_core` (vendor) exige rodar da **raiz do projeto**.
> Sobrescreva o interpretador no make: `make test PY="py -3.12"`.

## 8. Inspeção do banco (ad-hoc)

```bash
python - <<'PY'
from src import db
c = db.connect("data/matches.db")
print(c.execute("SELECT COUNT(*) FROM matches WHERE home_score IS NOT NULL").fetchone())
print(c.execute("SELECT home, away, selection, clv FROM backtest_bets WHERE bet_at='open'").fetchall())
PY
```

## 9. Variáveis de ambiente

| Variável | Efeito | Default |
|---|---|---|
| `PREDICTIONS_LOG_PATH` | Destino do log de predições | `data/predictions.jsonl` |
| `PREDICTOR_EVENTS_PATH` | Destino da telemetria JSONL (`backtest_completed`) | `./events.jsonl` |

## 10. Limpeza

```bash
make clean   # remove __pycache__ e .pytest_cache
```

---

## Ordem típica de uso

```bash
make install && make install-dev     # 1. setup (uma vez)
make ingest && make cron             # 2. dados + cache
make predict A=Brazil B=Norway NEUTRAL=1   # 3. prevê
make simulate N=10000                # 4. simula a Copa
make sofascore && make backtest && make bootstrap   # 5. quality gate (rede limpa)
make test                            # a qualquer momento
```
