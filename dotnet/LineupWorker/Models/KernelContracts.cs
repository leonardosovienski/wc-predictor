namespace LineupWorker.Models;

// ---------------------------------------------------------------------------
// CONTRATO 1 — Invocação do Kernel (C# → Redis → Python)
// Canal: "system:invoke_kernel"
// ---------------------------------------------------------------------------

/// <summary>Payload enviado ao Kernel Python para gerar as Fair Odds.</summary>
public record KernelInvokePayload(
    string  match_id,     // identificador único da partida
    double  elo_a,        // Elo do time A (home)
    double  elo_b,        // Elo do time B (away)
    double  dvorp_a,      // Delta VORP do time A (0 se escalação não chegou)
    double  dvorp_b,      // Delta VORP do time B
    long    timestamp_t3  // Unix ms do clock tick imediatamente antes da publicação
);

// ---------------------------------------------------------------------------
// CONTRATO 2 — Resposta das Fair Odds (Python → Redis → C#)
// Chave efêmera: "fair_odds:{match_id}"  (TTL: 5s)
// Canal de notificação: "fair_odds_ready:{match_id}"
// ---------------------------------------------------------------------------

/// <summary>
/// Fair Odds geradas pelo Kernel — preço justo sem overround (1/p_model).
/// Null indica probabilidade próxima de zero (descarte a seleção).
/// </summary>
public record FairOddsPayload(
    double? Home,    // "1"
    double? Draw,    // "X"
    double? Away,    // "2"
    double? Over25,  // "o25"
    double? Under25  // "u25"
)
{
    /// <summary>Desserializa do JSON enxuto com chaves numéricas do Kernel Python.</summary>
    public static FairOddsPayload FromDict(System.Text.Json.JsonElement root) => new(
        Home:    root.TryGetProperty("1",   out var h)   ? h.GetDouble()   : null,
        Draw:    root.TryGetProperty("X",   out var d)   ? d.GetDouble()   : null,
        Away:    root.TryGetProperty("2",   out var a)   ? a.GetDouble()   : null,
        Over25:  root.TryGetProperty("o25", out var o)   ? o.GetDouble()   : null,
        Under25: root.TryGetProperty("u25", out var u)   ? u.GetDouble()   : null
    );
}

// ---------------------------------------------------------------------------
// CONTRATO 3 — Market Odds Cache (Exchange → C# via WebSocket)
// Mantido em ConcurrentDictionary<matchId, MarketOdds> pelo MarketOddsCache.
// Nunca vai a disco ou banco — puramente em memória.
// ---------------------------------------------------------------------------

/// <summary>
/// True Odds do mercado (com overround removido pelo exchange ou pela nossa Shin inline).
/// Atualizado via WebSocket a cada tick do livro de ordens.
/// </summary>
public record MarketOdds(
    string         MatchId,
    double         OddsHome,
    double         OddsDraw,
    double         OddsAway,
    double?        OddsOver25,
    double?        OddsUnder25,
    DateTimeOffset LastUpdated,
    string         Source   // "pinnacle" | "isn" | "betfair"
)
{
    /// <summary>Overround detectado (>1.0 indica margem presente).</summary>
    public double Overround =>
        (OddsHome > 0 ? 1.0 / OddsHome : 0)
      + (OddsDraw > 0 ? 1.0 / OddsDraw : 0)
      + (OddsAway > 0 ? 1.0 / OddsAway : 0);

    /// <summary>True se as odds estão frescas (dentro da janela de staleness).</summary>
    public bool IsFresh(TimeSpan maxAge) => DateTimeOffset.UtcNow - LastUpdated <= maxAge;
}
