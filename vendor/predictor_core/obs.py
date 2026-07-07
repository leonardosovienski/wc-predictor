"""COMPAT SHIM — `obs` mudou-se para `predictor_core.kernel.obs`.

Mantido para não quebrar `from predictor_core.obs import ...`. Novo código deve importar
de `predictor_core.kernel.obs`. Reexporta o namespace inteiro do módulo real.
"""
from predictor_core.kernel import obs as _mod
globals().update({k: v for k, v in vars(_mod).items() if not k.startswith("__")})
