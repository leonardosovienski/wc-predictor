namespace LineupWorker.Models;

/// <summary>Evento de escalação recebido via Redis Pub/Sub.</summary>
public record LineupEvent(
    string  MatchId,
    string  HomeTeam,
    string  AwayTeam,
    string  Side,            // "home" | "away"
    string[] Starters,       // 11 jogadores titulares
    string[] Subs,           // até 9 reservas (opcional)
    DateTimeOffset CapturedAt
);

/// <summary>Resultado publicado no Redis após cálculo do Delta VORP.</summary>
public record LineupState(
    string  MatchId,
    double  DeltaVorpHome,
    double  DeltaVorpAway,
    bool    HomeLineupComplete,
    bool    AwayLineupComplete,
    /// <summary>Timestamp exato da captura da escalação — auditável pelo Market State Engine.</summary>
    DateTimeOffset LineupCapturedAt,
    DateTimeOffset ComputedAt,
    string  FallbackStrategy   // "none" | "timeout_historical" | "timeout_widen_variance"
);

/// <summary>Sinal de widening emitido quando o timeout de escalação expira.</summary>
public record VarianceWideningSignal(
    string  MatchId,
    string  Side,
    double  VarianceMultiplier,
    double[] TitularidadeMatrix,  // P(jogador_i é titular) para os N jogadores do elenco
    DateTimeOffset IssuedAt
);
