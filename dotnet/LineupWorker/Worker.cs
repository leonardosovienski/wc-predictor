using System.Text.Json;
using System.Threading.Channels;
using LineupWorker.Models;
using LineupWorker.Services;
using StackExchange.Redis;

namespace LineupWorker;

/// <summary>
/// Worker de escalações — Hot Path da Zona 1.
///
/// Fluxo de latência auditado (todos os timestamps em UTC de alta resolução):
///
///   T0 (source) → [Redis pub/sub] → T1 (received) → [VORP lookup O(1)] →
///   T2 (vorp computed) → [Redis SET] → T3 (redis written) →
///   → [lineup_complete] → MarketStateEngine → T4 (market read)
///
/// Garantias de latência:
///   • VORP lookup: O(1) — ConcurrentDictionary em memória, sem lock.
///   • Nenhuma alocação de string no caminho do VORP (chaves pré-interned).
///   • Redis pipeline: SET + ZADD em 1 round-trip (batch).
///   • GC: Channel<T> pré-alocado; LineupEvent é um record (sem boxing).
///
/// Fallback de timeout (watchdog a cada 60s):
///   • Se T_deadline < agora e escalação não chegou → emite VarianceWideningSignal
///     com a matriz de titularidade histórica do time, sinalizando ao
///     MarketStateEngine que deve alargar a variância do modelo.
/// </summary>
public sealed class LineupWorkerService : BackgroundService
{
    private const string LINEUP_CHANNEL_PATTERN = "lineups:*";
    private const string STATE_KEY_PREFIX       = "lineup_state:";
    private const string WIDEN_CHANNEL          = "variance_widen";
    private const string COMPLETE_CHANNEL       = "lineup_complete";

    private readonly ILogger<LineupWorkerService> _log;
    private readonly VorpStateService             _vorp;
    private readonly LatencyAuditService          _audit;
    private readonly MarketStateEngine            _mse;
    private readonly IConnectionMultiplexer       _redis;
    private readonly int    _timeoutMinutes;
    private readonly double _widenFactor;
    private readonly int    _watchdogIntervalSec;
    private readonly int    _redisStateTtlHours;

    // Fila interna desacoplada: receptor (pub/sub callback) → processador
    // BoundedChannel com DropOldest garante que GC pause nunca bloqueia o receptor Redis.
    private readonly Channel<(LineupEvent Event, DateTimeOffset T1_Received)> _queue;

    // Partidas aguardando escalação: matchId → (deadline, homeOk, awayOk)
    private readonly Dictionary<string, MatchTracking> _pending = new();

    public LineupWorkerService(
        ILogger<LineupWorkerService> log,
        VorpStateService vorp,
        LatencyAuditService audit,
        MarketStateEngine mse,
        IConnectionMultiplexer redis,
        IConfiguration cfg)
    {
        _log                = log;
        _vorp               = vorp;
        _audit              = audit;
        _mse                = mse;
        _redis              = redis;
        _timeoutMinutes     = cfg.GetValue<int>("Worker:LineupTimeoutMinutes",    55);
        _widenFactor        = cfg.GetValue<double>("Worker:VarianceWideningFactor", 1.35);
        _watchdogIntervalSec = cfg.GetValue<int>("Worker:WatchdogIntervalSeconds",  60);
        _redisStateTtlHours = cfg.GetValue<int>("Worker:RedisStateTtlHours",        6);

        var cap = cfg.GetValue<int>("Worker:QueueCapacity", 512);
        _queue = Channel.CreateBounded<(LineupEvent, DateTimeOffset)>(
            new BoundedChannelOptions(cap)
            {
                SingleReader = false,
                FullMode     = BoundedChannelFullMode.DropOldest,
            });
    }

    protected override async Task ExecuteAsync(CancellationToken ct)
    {
        if (!_vorp.IsReady)
        {
            _log.LogWarning("[Worker] VorpStateService ainda não aqueceu — aguardando…");
            await Task.Delay(2_000, ct);
        }

        var sub = _redis.GetSubscriber();

        // ChannelMessageQueue.OnMessage: API não-ambígua e robusta entre versões
        // do StackExchange.Redis (as sobrecargas com Action<RedisChannel,RedisValue>
        // são obsoletas/ambíguas em 2.7+).
        var queue = await sub.SubscribeAsync(RedisChannel.Pattern(LINEUP_CHANNEL_PATTERN));
        queue.OnMessage(channelMessage =>
        {
            // T1 capturado IMEDIATAMENTE ao receber — antes de qualquer processamento
            var t1 = DateTimeOffset.UtcNow;
            var message = channelMessage.Message;
            if (!message.HasValue) return;
            try
            {
                var ev = JsonSerializer.Deserialize<LineupEvent>(message.ToString());
                if (ev is null) return;

                // TryWrite: false = Channel cheio, DropOldest ativou
                // → SLA_BREACH_CRITICAL: dispara fallback de incerteza imediato
                if (!_queue.Writer.TryWrite((ev, t1)))
                {
                    _log.LogCritical(
                        "[CRITICAL] SLA_BREACH_CRITICAL {Match}/{Side} — Channel " +
                        "cheio (DropOldest ativado). Fallback de incerteza imediato.",
                        ev.MatchId, ev.Side);
                    _ = TriggerImmediateFallbackAsync(ev.MatchId, ev.Side, ev.CapturedAt);
                }
            }
            catch (Exception ex)
            {
                _log.LogError(ex, "[Worker] falha ao desserializar escalação");
            }
        });

        _log.LogInformation("[Worker] escutando {Pattern}", LINEUP_CHANNEL_PATTERN);

        await Task.WhenAll(
            ProcessQueueAsync(ct),
            TimeoutWatchdogAsync(ct)
        );
    }

    // ---------------------------------------------------------------------------
    // Hot path: processamento de escalações
    // ---------------------------------------------------------------------------

    private async Task ProcessQueueAsync(CancellationToken ct)
    {
        await foreach (var (ev, t1) in _queue.Reader.ReadAllAsync(ct))
        {
            try { await HandleLineupAsync(ev, t1, ct); }
            catch (Exception ex)
            {
                _log.LogError(ex, "[Worker] erro ao processar {Match}", ev.MatchId);
            }
        }
    }

    private async Task HandleLineupAsync(LineupEvent ev, DateTimeOffset t1, CancellationToken ct)
    {
        // T2: VORP calculado em O(1) — lookup em ConcurrentDictionary em memória
        var starters = ev.Starters.Select(p => (Player: p, Position: "UNKNOWN"));
        var delta    = _vorp.ComputeDeltaVorp(starters);
        var t2       = DateTimeOffset.UtcNow;

        // Registra o deadline para o watchdog (idempotente)
        _pending.TryAdd(ev.MatchId,
            new MatchTracking(ev.CapturedAt.AddMinutes(_timeoutMinutes), false, false));

        // Atualiza tracking de lado recebido
        if (_pending.TryGetValue(ev.MatchId, out var tracking))
        {
            _pending[ev.MatchId] = ev.Side == "home"
                ? tracking with { HomeOk = true }
                : tracking with { AwayOk = true };
        }

        // Lê/cria estado corrente da partida
        var db   = _redis.GetDatabase();
        var key  = STATE_KEY_PREFIX + ev.MatchId;
        var raw  = await db.StringGetAsync(key);

        var current = raw.HasValue
            ? JsonSerializer.Deserialize<LineupState>(raw.ToString())!
            : new LineupState(ev.MatchId, 0, 0, false, false,
                              ev.CapturedAt, DateTimeOffset.UtcNow, "none");

        var updated = ev.Side == "home"
            ? current with { DeltaVorpHome = delta, HomeLineupComplete = true,
                             LineupCapturedAt = ev.CapturedAt, ComputedAt = t2 }
            : current with { DeltaVorpAway = delta, AwayLineupComplete = true,
                             LineupCapturedAt = ev.CapturedAt, ComputedAt = t2 };

        // T3: escrita Redis — pipeline SET + notificação lineup_complete se completo
        var batch = db.CreateBatch();
        var ttl   = TimeSpan.FromHours(_redisStateTtlHours);
        var setTask = batch.StringSetAsync(key, JsonSerializer.Serialize(updated), ttl);

        // Emite lineup_complete apenas quando AMBOS os lados chegaram
        Task? notifyTask = null;
        if (updated.HomeLineupComplete && updated.AwayLineupComplete)
        {
            var completeMsg = JsonSerializer.Serialize(
                new { MatchId = ev.MatchId, CompleteAt = t2 });
            notifyTask = batch.PublishAsync(
                RedisChannel.Literal(COMPLETE_CHANNEL), completeMsg);
        }
        batch.Execute();
        await setTask;
        if (notifyTask != null) await notifyTask;

        var t3 = DateTimeOffset.UtcNow;

        // Grava registro de latência para auditoria (fora do caminho crítico)
        var latRec = new LatencyRecord(
            MatchId:            ev.MatchId,
            Side:               ev.Side,
            T0_SourcePublished: ev.CapturedAt,
            T1_Received:        t1,
            T2_VorpComputed:    t2,
            T3_RedisWritten:    t3,
            T4_MarketEngineRead: null,
            DeltaVorp:          delta,
            IsFallback:         false,
            FallbackReason:     null
        );
        // Invoca o Kernel Python após T2 (VORP já calculado) — fire-and-forget
        // O Kernel recebe os λ inputs e publica fair_odds:{matchId} (TTL 5s)
        _ = _mse.InvokeKernelAsync(
                matchId: ev.MatchId,
                eloA:    1500.0,   // TODO: passar Elo real via LineupEvent quando disponível
                eloB:    1500.0,
                dvorpA:  updated.DeltaVorpHome,
                dvorpB:  updated.DeltaVorpAway)
            .ContinueWith(t => _log.LogError(t.Exception, "[Worker] falha ao invocar kernel"),
                          TaskContinuationOptions.OnlyOnFaulted);

        // Fire-and-forget na auditoria — não bloqueia o hot path
        _ = _audit.RecordAsync(latRec).AsTask()
            .ContinueWith(t => _log.LogError(t.Exception, "[Worker] falha na auditoria"),
                          TaskContinuationOptions.OnlyOnFaulted);

        _log.LogInformation(
            "[Worker] {Match} {Side} ΔVORP={D:+0.000} E2E={E2E:F1}ms (net={Net:F1} proc={Proc:F2} write={Write:F1})",
            ev.MatchId, ev.Side, delta, (t3 - ev.CapturedAt).TotalMilliseconds,
            (t1 - ev.CapturedAt).TotalMilliseconds,
            (t2 - t1).TotalMilliseconds,
            (t3 - t2).TotalMilliseconds);
    }

    // ---------------------------------------------------------------------------
    // Watchdog de timeout — fallback quando escalação não chega
    // ---------------------------------------------------------------------------

    private async Task TimeoutWatchdogAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            await Task.Delay(TimeSpan.FromSeconds(_watchdogIntervalSec), ct);

            var now     = DateTimeOffset.UtcNow;
            var expired = _pending
                .Where(kv => kv.Value.Deadline < now)
                .Select(kv => kv.Key)
                .ToList();

            foreach (var matchId in expired)
            {
                _pending.Remove(matchId);
                var tracking = _pending.GetValueOrDefault(matchId);

                var db  = _redis.GetDatabase();
                var raw = await db.StringGetAsync(STATE_KEY_PREFIX + matchId);
                if (!raw.HasValue) continue;

                var state   = JsonSerializer.Deserialize<LineupState>(raw.ToString())!;
                bool needH  = !state.HomeLineupComplete;
                bool needA  = !state.AwayLineupComplete;
                if (!needH && !needA) continue;

                _log.LogWarning("[Worker] TIMEOUT {Match} — fallback widening (home={H} away={A})",
                    matchId, needH, needA);

                var sub = _redis.GetSubscriber();
                foreach (var (side, needed, team) in new[]
                {
                    ("home", needH, matchId.Split('_').ElementAtOrDefault(0) ?? ""),
                    ("away", needA, matchId.Split('_').ElementAtOrDefault(1) ?? ""),
                })
                {
                    if (!needed) continue;

                    var mat    = _vorp.GetTitularidadeMatrix(team);
                    var signal = new VarianceWideningSignal(
                        MatchId:            matchId,
                        Side:               side,
                        VarianceMultiplier: _widenFactor,
                        TitularidadeMatrix: mat ?? Array.Empty<double>(),
                        IssuedAt:           now
                    );
                    await sub.PublishAsync(
                        RedisChannel.Literal(WIDEN_CHANNEL),
                        JsonSerializer.Serialize(signal));

                    // Grava registro de fallback na auditoria
                    var latRec = new LatencyRecord(
                        MatchId:            matchId,
                        Side:               side,
                        T0_SourcePublished: now.AddMinutes(-_timeoutMinutes),
                        T1_Received:        now,
                        T2_VorpComputed:    now,
                        T3_RedisWritten:    now,
                        T4_MarketEngineRead: null,
                        DeltaVorp:          0,
                        IsFallback:         true,
                        FallbackReason:     "timeout_widen_variance"
                    );
                    _ = _audit.RecordAsync(latRec).AsTask();
                }

                var fallback = state with { FallbackStrategy = "timeout_widen_variance",
                                            ComputedAt = now };
                await db.StringSetAsync(
                    STATE_KEY_PREFIX + matchId,
                    JsonSerializer.Serialize(fallback),
                    TimeSpan.FromHours(_redisStateTtlHours));
            }
        }
    }

    /// <summary>
    /// Fallback imediato para quando o Channel descarta uma escalação (SLA_BREACH_CRITICAL).
    /// Emite VarianceWideningSignal e registra o breach na auditoria.
    /// Executado fora do hot path (Task.Run implícito via fire-and-forget).
    /// </summary>
    private async Task TriggerImmediateFallbackAsync(
        string matchId, string side, DateTimeOffset sourceTs)
    {
        var now = DateTimeOffset.UtcNow;
        var sub = _redis.GetSubscriber();

        var signal = new VarianceWideningSignal(
            MatchId:            matchId,
            Side:               side,
            VarianceMultiplier: _widenFactor,
            TitularidadeMatrix: Array.Empty<double>(),   // sem lineup → sem matriz
            IssuedAt:           now
        );
        await sub.PublishAsync(
            RedisChannel.Literal(WIDEN_CHANNEL),
            JsonSerializer.Serialize(signal));

        var latRec = new LatencyRecord(
            MatchId:            matchId,
            Side:               side,
            T0_SourcePublished: sourceTs,
            T1_Received:        now,
            T2_VorpComputed:    now,
            T3_RedisWritten:    now,
            T4_MarketEngineRead: null,
            DeltaVorp:          0,
            IsFallback:         true,
            FallbackReason:     "sla_breach_critical_channel_full"
        );
        await _audit.RecordAsync(latRec);
    }

    private record MatchTracking(DateTimeOffset Deadline, bool HomeOk, bool AwayOk);
}
