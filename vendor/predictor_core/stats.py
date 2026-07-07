"""COMPAT SHIM — `stats` mudou-se para `predictor_core.measurement.stats`.

Mantido para não quebrar `from predictor_core.stats import ...` durante o ciclo de
deprecação. Novo código: `predictor_core.measurement.stats` (régua financeira) e
`predictor_core.measurement.bootstrap` (bootstrap_ci). `block_bootstrap_ci` e `ci_mean`
seguem aqui como wrappers depreciados (emitem DeprecationWarning ao chamar). Reexporta
o namespace inteiro do módulo real para compatibilidade total.
"""
from predictor_core.measurement import stats as _mod
globals().update({k: v for k, v in vars(_mod).items() if not k.startswith("__")})
