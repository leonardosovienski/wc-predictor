"""predictor-core.measurement.trials — registro de tentativas + Deflated Sharpe Ratio.

Promovido do previsao-cripto (analyzers/trials.py). Governança contra data-snooping:
cada configuração avaliada contra os dados (ativo, horizonte, prompt, feature, fonte)
é uma TENTATIVA. Avaliar N configurações e reportar a melhor infla o Sharpe esperado
por pura sorte — E[max SR] cresce com N mesmo sem skill. O DSR (Bailey & López de
Prado, 2014) desconta isso: é o PSR calculado contra E[max SR | H0, N] em vez de zero.

O arquivo de tentativas é VERSIONADO de propósito: o desconto só é honesto se o
denominador (quantas tentativas houve) sobreviver ao esquecimento seletivo. Registrar
é barato; não registrar fabrica significância.

Unidades: os `sharpe` registrados e o DSR operam POR-PERÍODO (a mesma unidade que o
PSR observa internamente), NÃO anualizada. Misturar unidades invalida o benchmark.

O caminho do arquivo é do DOMÍNIO (o core não presume onde ele mora): passe `path`
explicitamente ou use o default `./trials.json` no diretório de trabalho.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist, variance

from predictor_core.measurement.stats import probabilistic_sharpe_ratio

_EULER = 0.5772156649015329  # γ de Euler–Mascheroni
_DEFAULT_PATH = Path("trials.json")


# ---------- registro ----------

def load_trials(path: Path | str | None = None) -> list[dict]:
    p = Path(path or _DEFAULT_PATH)
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8"))


def register_trial(name: str, *, params: dict, sharpe: float | None = None,
                   notes: str = "", path: Path | str | None = None,
                   now: str | None = None) -> list[dict]:
    """Registra (ou atualiza) uma tentativa. `name` é a identidade da CONFIGURAÇÃO:
    reexecutar a mesma configuração NÃO é tentativa nova — atualiza a existente
    (preservando o registered_at original). Retorna a lista completa após a escrita.
    `now` injetável para teste determinístico."""
    p = Path(path or _DEFAULT_PATH)
    trials = load_trials(p)
    stamp = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = {"name": name, "registered_at": stamp, "params": params,
             "sharpe": sharpe, "notes": notes}
    for i, t in enumerate(trials):
        if t.get("name") == name:
            entry["registered_at"] = t.get("registered_at", stamp)
            trials[i] = entry
            break
    else:
        trials.append(entry)
    p.write_text(json.dumps(trials, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return trials


# ---------- Deflated Sharpe Ratio ----------

def expected_max_sharpe(n_trials: int, var_trials_sr: float) -> float:
    """E[max SR] sob H0 (nenhuma tentativa tem skill) para N tentativas.

    Aproximação de máximo de gaussianas (López de Prado 2014):
    sqrt(V[SR]) * ((1-γ)·Φ⁻¹(1-1/N) + γ·Φ⁻¹(1-1/(N·e))). Com 1 tentativa ou
    variância nula entre tentativas, não há seleção → benchmark 0."""
    if n_trials <= 1 or var_trials_sr <= 0:
        return 0.0
    nd = NormalDist()
    z1 = nd.inv_cdf(1.0 - 1.0 / n_trials)
    z2 = nd.inv_cdf(1.0 - 1.0 / (n_trials * math.e))
    return math.sqrt(var_trials_sr) * ((1.0 - _EULER) * z1 + _EULER * z2)


def deflated_sharpe_ratio(returns: list, trial_sharpes: list) -> dict:
    """DSR = PSR(returns, SR0), SR0 = E[max SR] dado o nº de tentativas registradas.

    `trial_sharpes`: SRs por-período das tentativas (None/±inf são tolerados — contam
    no N, ficam fora da variância). Retorna {dsr, sr0, n_trials}; dsr é
    P(SR verdadeiro > máximo esperado por sorte)."""
    n = len(trial_sharpes)
    finite = [s for s in trial_sharpes if s is not None and math.isfinite(s)]
    var = variance(finite) if len(finite) >= 2 else 0.0
    sr0 = expected_max_sharpe(n, var)
    return {"dsr": probabilistic_sharpe_ratio(returns, benchmark_sharpe=sr0),
            "sr0": sr0, "n_trials": n}


# ---------- fachada orientada a objeto (interface do core) ----------

class TrialRegistry:
    """Fachada fina sobre o arquivo de tentativas — a interface pública do contrato.

    registry = TrialRegistry("trials.json")
    registry.register("v3-fr90", params={...}, sharpe=-0.002)
    verdict = registry.deflated_sharpe(returns)   # desconta por todas as tentativas
    """
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path or _DEFAULT_PATH)

    def register(self, name: str, *, params: dict, sharpe: float | None = None,
                 notes: str = "", now: str | None = None) -> list[dict]:
        return register_trial(name, params=params, sharpe=sharpe, notes=notes,
                              path=self.path, now=now)

    def load(self) -> list[dict]:
        return load_trials(self.path)

    def sharpes(self) -> list:
        return [t.get("sharpe") for t in self.load()]

    def deflated_sharpe(self, returns: list) -> dict:
        """DSR de `returns` descontado por TODAS as tentativas registradas no arquivo."""
        return deflated_sharpe_ratio(returns, self.sharpes())
