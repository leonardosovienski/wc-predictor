"""predictor-core — biblioteca vendorizada. NÃO editar local; sync via script.

Estrutura em camadas: kernel (L0) · measurement (L1) · data (L2, futuro). A API pública
estável é re-exportada aqui — `from predictor_core import sharpe, emit_event, replay`.
Os caminhos por submódulo (`predictor_core.measurement.stats`, ...) são o destino
canônico; os módulos planos de topo (`predictor_core.stats`, ...) são shims de compat.
"""
import pathlib

VERSION_FILE = pathlib.Path(__file__).parent / "VERSION"
__version__ = VERSION_FILE.read_text(encoding="utf-8").strip().split("\n")[0]

# --- API pública estável (re-export das camadas) ---------------------------
from predictor_core.kernel.infra import connect, run_migrations, config_hash
from predictor_core.kernel.obs import emit_event, read_events, setup_logging, get_logger
from predictor_core.kernel.settings import require_secrets, MissingCredentialsError
from predictor_core.kernel.net import download_file, sha256_file
from predictor_core.kernel.meta import fingerprint, validate, StaleModelError
from predictor_core.measurement.stats import (
    sharpe, sortino, max_drawdown, probabilistic_sharpe_ratio,
    spearman, spearman_block_ci, block_bootstrap_ci, ci_mean,  # 2 últimas: depreciadas
)
from predictor_core.measurement.bootstrap import bootstrap_ci
from predictor_core.measurement.metrics import (
    brier, log_loss, rps, calibration_table, diebold_mariano,
)
from predictor_core.measurement.trials import (
    TrialRegistry, register_trial, load_trials, deflated_sharpe_ratio,
)
from predictor_core.measurement.nullref import (
    null_distribution, tail_probability, percentile_of, random_portfolio_sequence,
)
from predictor_core.measurement.replay import replay, PastView, LookaheadError
from predictor_core.data.asof import state_asof

__all__ = [
    "__version__",
    # kernel
    "connect", "run_migrations", "config_hash",
    "emit_event", "read_events", "setup_logging", "get_logger",
    "require_secrets", "MissingCredentialsError",
    "download_file", "sha256_file",
    "fingerprint", "validate", "StaleModelError",
    # measurement — financeira
    "sharpe", "sortino", "max_drawdown", "probabilistic_sharpe_ratio",
    "spearman", "spearman_block_ci",
    # measurement — bootstrap (novo) + depreciados
    "bootstrap_ci", "block_bootstrap_ci", "ci_mean",
    # measurement — probabilística
    "brier", "log_loss", "rps", "calibration_table", "diebold_mariano",
    # measurement — trials/DSR
    "TrialRegistry", "register_trial", "load_trials", "deflated_sharpe_ratio",
    # measurement — referência nula (3ª lente)
    "null_distribution", "tail_probability", "percentile_of", "random_portfolio_sequence",
    # measurement — replay
    "replay", "PastView", "LookaheadError",
    # data — estado as-of
    "state_asof",
]
