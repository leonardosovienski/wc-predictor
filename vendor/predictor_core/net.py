"""COMPAT SHIM — `net` mudou-se para `predictor_core.kernel.net`.

Mantido para não quebrar `from predictor_core.net import ...` (público OU privado).
Novo código deve importar de `predictor_core.kernel.net`. Reexporta o namespace inteiro
do módulo real para compatibilidade total durante o ciclo de deprecação.
"""
from predictor_core.kernel import net as _mod
globals().update({k: v for k, v in vars(_mod).items() if not k.startswith("__")})
