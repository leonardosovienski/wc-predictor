"""COMPAT SHIM — `settings` mudou-se para `predictor_core.kernel.settings`.

Mantido para não quebrar `from predictor_core.settings import ...`. Novo código deve
importar de `predictor_core.kernel.settings`. Reexporta o namespace inteiro do módulo real.
"""
from predictor_core.kernel import settings as _mod
globals().update({k: v for k, v in vars(_mod).items() if not k.startswith("__")})
