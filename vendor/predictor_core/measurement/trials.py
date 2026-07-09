"""predictor-core.measurement.trials — Experiment Registry + Deflated Sharpe Ratio.

RECONCILIAÇÃO (2026-07-09): esta é a versão EVOLUÍDA, re-promovida do
previsao-cripto (analyzers/trials.py), que havia divergido da cópia original do
core — o pior tipo de drift: duas réguas de governança na mesma plataforma.
Ganhos sobre a v1: schema formal (`validate_trials`), governança de identidade
N+1 (mudar `params` de trial existente é ERRO, não update silencioso) e a trava
de controle positivo (criar trial NOVA exige atestado do harness — ver abaixo).

Governança contra data-snooping: cada configuração avaliada contra os dados
(ativo, horizonte, prompt, feature, fonte) é uma TENTATIVA. Avaliar N
configurações e reportar a melhor infla o Sharpe esperado por pura sorte —
E[max SR] cresce com N mesmo sem skill. O DSR (Bailey & López de Prado, 2014)
desconta isso: é o PSR calculado contra E[max SR | H0, N] em vez de zero.

O arquivo de tentativas é VERSIONADO de propósito: o desconto só é honesto se o
denominador (quantas tentativas houve) sobreviver ao esquecimento seletivo.

TRAVA DE PODER (harness ↔ registry): um NO-GO só é interpretável se o pipeline
provou que detectaria edge plantado (testing/harness). Criar uma trial NOVA
exige um ATESTADO — arquivo irmão `<trials>.harness_attestation.json`, emitido
por `testing.harness.attest_pipeline_power` — senão o registro está governando
vereditos de um juiz possivelmente cego. Atualizar sharpe/notes de trial
EXISTENTE não exige (a maturação automática de resultados não pode depender do
harness ter rodado na mesma máquina). O atestado é arquivo, não flag em
memória, porque o harness roda na suíte de testes e o registro roda no
pipeline: processos distintos.

Unidades: os `sharpe` registrados e o DSR operam POR-PERÍODO (a mesma unidade
que o PSR observa internamente), NÃO anualizada.

O caminho do arquivo é do DOMÍNIO: passe `path` explicitamente ou use o default
`./trials.json` no diretório de trabalho.
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


class PowerAttestationMissingError(RuntimeError):
    """Tentativa de criar trial NOVA sem atestado de controle positivo.

    Rode `testing.harness.attest_pipeline_power(...)` — que exige que o SEU
    pipeline detecte edge sintético e rejeite ruído — para emitir o atestado
    irmão do trials.json. Sem essa prova, o registro governaria vereditos de
    um juiz que ninguém confirmou não ser cego."""


def attestation_path_for(trials_path: Path | str) -> Path:
    """Caminho canônico do atestado: irmão do trials.json."""
    p = Path(trials_path)
    return p.with_name(p.stem + ".harness_attestation.json")


def _attestation_file_ok(att: Path) -> bool:
    """Atestado válido = arquivo existente, JSON legível, com `passed_at`."""
    if not att.exists():
        return False
    try:
        return bool(json.loads(att.read_text(encoding="utf-8")).get("passed_at"))
    except (ValueError, OSError):
        return False


# ---------- registro ----------

def load_trials(path: Path | str | None = None) -> list[dict]:
    p = Path(path or _DEFAULT_PATH)
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8"))


def validate_trials(trials: list[dict]) -> list[str]:
    """Schema formal do registro. Retorna a lista de violações (vazia = conforme).
    A suíte do consumidor deve falhar se o trials.json real não conformar — o
    registro só protege o DSR se todo campo do denominador for interpretável.

    Obrigatórios: name (str não-vazio, sem espaços — identidade), registered_at
    (ISO-8601 UTC 'Z'), params (dict NÃO-vazio — a configuração exata), sharpe
    (None ou número finito, unidade por-período), notes (str).
    Opcionais tipados: features_used (list[str]), train_period/test_period
    ([início, fim] ISO-8601).
    """
    errs: list[str] = []
    seen: set[str] = set()
    for i, t in enumerate(trials):
        tag = f"trial[{i}]"
        name = t.get("name")
        if not isinstance(name, str) or not name or " " in name:
            errs.append(f"{tag}: name inválido ({name!r}) — str não-vazia sem espaços")
        elif name in seen:
            errs.append(f"{tag}: name duplicado ({name!r}) — identidade precisa ser única")
        else:
            seen.add(name)
            tag = f"trial[{name}]"
        ra = t.get("registered_at", "")
        try:
            datetime.strptime(ra, "%Y-%m-%dT%H:%M:%SZ")
        except (TypeError, ValueError):
            errs.append(f"{tag}: registered_at inválido ({ra!r}) — use ISO-8601 UTC 'Z'")
        params = t.get("params")
        if not isinstance(params, dict) or not params:
            errs.append(f"{tag}: params precisa ser dict NÃO-vazio (a configuração exata "
                        "é o que permite ao DSR distinguir tentativas)")
        sharpe = t.get("sharpe")
        if sharpe is not None and not (isinstance(sharpe, (int, float))
                                       and math.isfinite(sharpe)):
            errs.append(f"{tag}: sharpe inválido ({sharpe!r}) — None ou número finito")
        if not isinstance(t.get("notes", ""), str):
            errs.append(f"{tag}: notes precisa ser str")
        for key in ("train_period", "test_period"):
            per = t.get(key)
            if per is not None and not (isinstance(per, list) and len(per) == 2
                                        and all(isinstance(x, str) for x in per)):
                errs.append(f"{tag}: {key} inválido — [início, fim] ISO-8601")
        fu = t.get("features_used")
        if fu is not None and not (isinstance(fu, list)
                                   and all(isinstance(x, str) for x in fu)):
            errs.append(f"{tag}: features_used inválido — list[str]")
    return errs


def register_trial(name: str, *, params: dict, sharpe: float | None = None,
                   notes: str = "", path: Path | str | None = None,
                   now: str | None = None,
                   power_attestation: Path | str | bool | None = None,
                   **extra) -> list[dict]:
    """Registra (ou atualiza) uma tentativa. `name` é a identidade da CONFIGURAÇÃO.

    Governança de identidade: reexecutar a MESMA configuração atualiza a entrada
    (sharpe/notes, preservando o registered_at original); tentar "atualizar" uma
    trial existente com `params` DIFERENTES é ValueError — variação de
    configuração é tentativa NOVA (N+1), e escondê-la num update fabricaria
    significância que o DSR não desconta.

    Trava de poder: criar trial NOVA exige o atestado do harness (arquivo irmão;
    ver docstring do módulo). `power_attestation`: None = procura o irmão;
    caminho = usa esse arquivo; False = bypass EXPLÍCITO (só para teste de
    mecânica do registro — nunca em pesquisa real).

    `now` injetável para teste determinístico. `extra` aceita os campos
    opcionais do schema (features_used, train_period, test_period). Valida o
    schema ANTES de gravar. Retorna a lista completa após a escrita."""
    p = Path(path or _DEFAULT_PATH)
    trials = load_trials(p)
    stamp = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = {"name": name, "registered_at": stamp, "params": params,
             "sharpe": sharpe, "notes": notes, **extra}
    for i, t in enumerate(trials):
        if t.get("name") == name:
            if t.get("params") != params:
                raise ValueError(
                    f"trial '{name}' já existe com params DIFERENTES — variação de "
                    "configuração é tentativa nova: registre com um name novo (N+1). "
                    f"registrado={t.get('params')!r} vs proposto={params!r}")
            entry["registered_at"] = t.get("registered_at", stamp)
            trials[i] = entry
            break
    else:
        if power_attestation is not False:
            att = Path(power_attestation) if power_attestation else attestation_path_for(p)
            if not _attestation_file_ok(att):
                raise PowerAttestationMissingError(
                    f"trial nova '{name}' sem atestado de controle positivo "
                    f"({att}) — rode testing.harness.attest_pipeline_power "
                    "para provar que o pipeline detecta edge plantado e "
                    "rejeita ruído, ANTES de registrar tentativas.")
        trials.append(entry)
    errs = validate_trials(trials)
    if errs:
        raise ValueError("registro violaria o schema de trials: " + "; ".join(errs))
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

    `trial_sharpes`: SRs por-período das tentativas (None/±inf são tolerados —
    contam no N, ficam fora da variância). Retorna {dsr, sr0, n_trials}; dsr é
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
    registry.validate()                           # [] = schema conforme
    verdict = registry.deflated_sharpe(returns)   # desconta por todas as tentativas
    """
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path or _DEFAULT_PATH)

    def register(self, name: str, *, params: dict, sharpe: float | None = None,
                 notes: str = "", now: str | None = None,
                 power_attestation: Path | str | bool | None = None,
                 **extra) -> list[dict]:
        return register_trial(name, params=params, sharpe=sharpe, notes=notes,
                              path=self.path, now=now,
                              power_attestation=power_attestation, **extra)

    def load(self) -> list[dict]:
        return load_trials(self.path)

    def validate(self) -> list[str]:
        return validate_trials(self.load())

    def sharpes(self) -> list:
        return [t.get("sharpe") for t in self.load()]

    def deflated_sharpe(self, returns: list) -> dict:
        """DSR de `returns` descontado por TODAS as tentativas registradas no arquivo."""
        return deflated_sharpe_ratio(returns, self.sharpes())
