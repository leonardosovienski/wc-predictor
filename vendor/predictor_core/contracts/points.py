"""contracts.points — caminho canônico dos envelopes de dados (v1.3.0).

Fachada sobre `data/contracts.py` (a implementação física, preservada onde os
vendors já a importam). Novo código importa daqui."""
from predictor_core.data.contracts import (  # noqa: F401
    MarketDataPoint, SignalPoint, PredictionPoint,
    DataProvider, SignalProvider, DataUnavailableError,
)

__all__ = ["MarketDataPoint", "SignalPoint", "PredictionPoint",
           "DataProvider", "SignalProvider", "DataUnavailableError"]
