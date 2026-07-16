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
    TrialRegistry, register_trial, load_trials, validate_trials,
    deflated_sharpe_ratio, attestation_path_for, PowerAttestationMissingError,
    MetricMismatchError,
)
from predictor_core.measurement.calibration import PlattCalibrator, shin_devig
from predictor_core.kernel.timeindex import utcnow, to_utc, iso_z, parse_iso, NaiveDatetimeError
from predictor_core.kernel.jsonl_store import JsonlStore
from predictor_core.testing.prequential import PrequentialEvaluator
from predictor_core.measurement.nullref import (
    null_distribution, tail_probability, percentile_of, random_portfolio_sequence,
)
from predictor_core.measurement.replay import replay, PastView, LookaheadError
from predictor_core.measurement.ledger import Posting, Transaction, Ledger, UnbalancedTransactionError
from predictor_core.measurement.ordinal import plackett_luce_prob, fit_plackett_luce, rank_probabilities
from predictor_core.kernel.rating import Entity, expected_score, update_pair, RatingBook
from predictor_core.testing.stress import check_property, floats, integers, lists_of, PropertyFailure
from predictor_core.data.asof import state_asof
from predictor_core.data.contracts import PredictionPoint

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
    # measurement — trials/DSR (+ governança reconciliada 2026-07-09)
    "TrialRegistry", "register_trial", "load_trials", "validate_trials",
    "deflated_sharpe_ratio", "attestation_path_for", "PowerAttestationMissingError",
    # measurement — referência nula (3ª lente)
    "null_distribution", "tail_probability", "percentile_of", "random_portfolio_sequence",
    # measurement — replay
    "replay", "PastView", "LookaheadError",
    # measurement — ledger (partida dobrada, agosto/2026)
    "Posting", "Transaction", "Ledger", "UnbalancedTransactionError",
    # measurement — camada ordinal (Plackett-Luce, agosto/2026)
    "plackett_luce_prob", "fit_plackett_luce", "rank_probabilities",
    # kernel — EloEngine generalizado (agosto/2026)
    "Entity", "expected_score", "update_pair", "RatingBook",
    # testing — telemetria de estresse property-based (agosto/2026)
    "check_property", "floats", "integers", "lists_of", "PropertyFailure",
    # v1.3.0 — estado definitivo: calibração, tempo, JSONL, prequential, punição global
    "PlattCalibrator", "shin_devig",
    "utcnow", "to_utc", "iso_z", "parse_iso", "NaiveDatetimeError",
    "JsonlStore", "PrequentialEvaluator", "MetricMismatchError",
    # data — estado as-of + contrato do ciclo previsão→maturação
    "state_asof", "PredictionPoint",
]
