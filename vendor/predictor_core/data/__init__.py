"""predictor_core.data (L2) — contratos de dado point-in-time e infraestrutura.

Promovido do previsao-cripto (DPL, ADR-002). O core carrega apenas os CONTRATOS e a
infraestrutura genérica; os providers concretos (Binance, CoinGecko, Kraken, BCB,
COTAHIST, Fear&Greed) permanecem nos domínios.

  contracts       — MarketDataPoint, SignalPoint (com `published_at` obrigatório),
                    DataProvider, SignalProvider, DataUnavailableError.
  aggregation     — fusão multi-fonte (consensus_median/mean, twap).
  circuit_breaker — CircuitBreaker unificado (une as duas implementações do cripto:
                    a da dpl e a da v3) + CircuitOpenError.
  router          — FallbackRouter (sequencial) e AggregationRouter (consenso concorrente).
  quality         — detector de saltos + inferência de split (funções puras).

Depende de kernel (obs). Nenhum import de domínio."""
