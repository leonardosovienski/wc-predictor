"""COMPAT SHIM — `infra` mudou-se para `predictor_core.kernel.infra`.

Mantido para não quebrar `from predictor_core.infra import ...`. Novo código deve
importar de `predictor_core.kernel.infra`. Reexporta o namespace inteiro do módulo real.
"""
from predictor_core.kernel import infra as _mod
globals().update({k: v for k, v in vars(_mod).items() if not k.startswith("__")})
