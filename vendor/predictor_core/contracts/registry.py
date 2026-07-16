"""contracts.registry — caminho canônico da governança de experimentos (v1.3.0).

Fachada sobre `measurement/trials.py` (implementação física preservada).
Novo código importa daqui."""
from predictor_core.measurement.trials import (  # noqa: F401
    TrialRegistry, register_trial, load_trials, validate_trials,
    deflated_sharpe_ratio, expected_max_sharpe, attestation_path_for,
    PowerAttestationMissingError,
)

__all__ = ["TrialRegistry", "register_trial", "load_trials", "validate_trials",
           "deflated_sharpe_ratio", "expected_max_sharpe", "attestation_path_for",
           "PowerAttestationMissingError"]
