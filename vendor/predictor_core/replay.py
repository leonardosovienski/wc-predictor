"""COMPAT SHIM — `replay` mudou-se para `predictor_core.measurement.replay`.

Mantido para não quebrar `from predictor_core.replay import ...`. Novo código deve
importar de `predictor_core.measurement.replay`. Reexporta o namespace inteiro do módulo.
"""
from predictor_core.measurement import replay as _mod
globals().update({k: v for k, v in vars(_mod).items() if not k.startswith("__")})
