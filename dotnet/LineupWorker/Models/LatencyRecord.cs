namespace LineupWorker.Models;

/// <summary>
/// Registro imutável de latência para auditoria pós-fato.
///
/// Grafo de timestamps (todos em UTC, alta resolução):
///   T0_SourcePublished   → quando a fonte publicou a escalação
///   T1_Received          → quando nosso subscriber recebeu a mensagem Redis
///   T2_VorpComputed      → quando o Delta VORP foi calculado em memória
///   T3_RedisWritten      → quando o LineupState foi persistido no Redis
///   T4_MarketEngineRead  → quando o MarketStateEngine leu o estado (preenchido depois)
///
/// Deltas derivados:
///   NetworkLagMs         = T1 - T0   (latência de rede + pub/sub)
///   ProcessingMs         = T2 - T1   (puro cálculo em memória, deve ser <1ms)
///   WriteMs              = T3 - T2   (round-trip Redis SET)
///   E2EMs                = T3 - T0   (latência total do nosso pipeline)
///   MarketReactionMs     = T4 - T3   (tempo até o motor de mercado reagir — opcional)
/// </summary>
public record LatencyRecord(
    string          MatchId,
    string          Side,
    DateTimeOffset  T0_SourcePublished,
    DateTimeOffset  T1_Received,
    DateTimeOffset  T2_VorpComputed,
    DateTimeOffset  T3_RedisWritten,
    DateTimeOffset? T4_MarketEngineRead,
    double          DeltaVorp,
    bool            IsFallback,
    string?         FallbackReason
)
{
    public double NetworkLagMs   => (T1_Received    - T0_SourcePublished).TotalMilliseconds;
    public double ProcessingMs   => (T2_VorpComputed - T1_Received).TotalMilliseconds;
    public double WriteMs        => (T3_RedisWritten - T2_VorpComputed).TotalMilliseconds;
    public double E2EMs          => (T3_RedisWritten - T0_SourcePublished).TotalMilliseconds;
    public double? MarketReactionMs => T4_MarketEngineRead.HasValue
        ? (T4_MarketEngineRead.Value - T3_RedisWritten).TotalMilliseconds
        : null;

    /// <summary>True se o pipeline bateu o budget de latência configurado.</summary>
    public bool IsWithinBudget(double budgetMs) => E2EMs <= budgetMs;
}

/// <summary>Sinal de aposta emitido pelo MarketStateEngine.</summary>
public record BetSignal(
    string         MatchId,
    string         Market,        // "1x2" | "ou25"
    string         Selection,     // "home" | "draw" | "away" | "over" | "under"
    double         PModel,
    double         OddsOffered,
    double         EdgeVsPrice,   // P_model - 1/odd
    double         KellyStake,    // fração do bankroll recomendada
    double         DeltaVorpHome,
    double         DeltaVorpAway,
    DateTimeOffset IssuedAt,
    double         PipelineLatencyMs
);
