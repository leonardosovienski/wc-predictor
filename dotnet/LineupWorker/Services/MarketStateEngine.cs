using System.Text.Json;
using LineupWorker.Models;
using StackExchange.Redis;

namespace LineupWorker.Services;

/// <summary>
/// MarketStateEngine — Zona 2 do Hot Path.
///
/// Acorda via notificação Redis "fair_odds_ready:{match_id}" publicada pelo Kernel Python
/// após escrever a chave efêmera "fair_odds:{match_id}" (TTL 5s).
///
/// T4 está estritamente definido como o clock tick imediatamente ANTES da emissão do
/// BetSignal — engloba a leitura das Fair Odds (Redis), a leitura das Market Odds
/// (ConcurrentDictionary em memória) e a aritmética de edge. Nenhum I/O de banco.
///
/// Contrato de abortamento:
///   • Fair Odds expiradas (chave TTL esgotada → Redis retorna null) → ABORT.
///   • Market Odds ausentes ou stale (> 30s) → ABORT.
///   • Edge fora da janela [MinEdge, MaxEdge] → não gera sinal (sem ABORT).
/// </summary>
public sealed class MarketStateEngine : BackgroundService
{
    private const string FAIR_ODDS_READY_PATTERN = "fair_odds_ready:*";
    private const string FAIR_ODDS_KEY_PREFIX    = "fair_odds:";
    private const string STATE_KEY_PREFIX        = "lineup_state:";
    private const string BET_SIGNAL_CHANNEL      = "bet_signals";
    private const string KERNEL_INVOKE_CHANNEL   = "system:invoke_kernel";

    private readonly IConnectionMultiplexer _redis;
    private readonly MarketOddsCache        _marketCache;
    private readonly LatencyAuditService    _audit;
    private readonly ILogger<MarketStateEngine> _log;
    private readonly double _minEdge;
    private readonly double _maxEdge;
    private readonly double _kellyFrac;
    private readonly double _budgetMs;

    public MarketStateEngine(
        IConnectionMultiplexer redis,
        MarketOddsCache marketCache,
        LatencyAuditService audit,
        ILogger<MarketStateEngine> log,
        IConfiguration cfg)
    {
        _redis       = redis;
        _marketCache = marketCache;
        _audit       = audit;
        _log         = log;
        _minEdge  = cfg.GetValue<double>("MarketStateEngine:MinEdgePct",    0.02);
        _maxEdge  = cfg.GetValue<double>("MarketStateEngine:MaxEdgePct",    0.15);
        _kellyFrac = cfg.GetValue<double>("MarketStateEngine:KellyFraction", 0.25);
        _budgetMs = cfg.GetValue<double>("MarketStateEngine:LatencyBudgetMs", 300);
    }

    protected override async Task ExecuteAsync(CancellationToken ct)
    {
        var sub = _redis.GetSubscriber();

        // Subscreve ao canal de notificação publicado pelo Kernel Python.
        // ChannelMessageQueue.OnMessage: API não-ambígua e robusta entre versões.
        var queue = await sub.SubscribeAsync(RedisChannel.Pattern(FAIR_ODDS_READY_PATTERN));
        queue.OnMessage(async channelMessage =>
        {
            var message = channelMessage.Message;
            if (!message.HasValue) return;
            // Extrai matchId do nome do canal (fair_odds_ready:{matchId})
            var channelStr = channelMessage.Channel.ToString();
            var prefix     = FAIR_ODDS_READY_PATTERN[..^1];   // "fair_odds_ready:"
            var matchId    = channelStr.StartsWith(prefix)
                ? channelStr[prefix.Length..]
                : "";
            if (string.IsNullOrEmpty(matchId)) return;

            try { await ProcessFairOddsAsync(matchId, message.ToString(), ct); }
            catch (Exception ex)
            {
                _log.LogError(ex, "[MSE] erro ao processar fair_odds_ready:{Match}", matchId);
            }
        });

        _log.LogInformation("[MSE] aguardando fair_odds_ready:* do Kernel Python…");
        await Task.Delay(Timeout.Infinite, ct);
    }

    // ---------------------------------------------------------------------------
    // Hot path T3.5 → T4
    // ---------------------------------------------------------------------------

    private async Task ProcessFairOddsAsync(string matchId, string fairOddsJson,
                                            CancellationToken ct)
    {
        // Fair Odds chegam inline na notificação (Python publica o payload junto)
        // MAS verificamos a chave efêmera no Redis para confirmar TTL ainda válido
        var db      = _redis.GetDatabase();
        var rawKey  = await db.StringGetAsync(FAIR_ODDS_KEY_PREFIX + matchId);
        if (!rawKey.HasValue)
        {
            _log.LogWarning("[MSE] ABORT {Match} — fair_odds expiradas (TTL esgotado)", matchId);
            return;
        }

        FairOddsPayload fair;
        try
        {
            using var doc = JsonDocument.Parse(rawKey.ToString());
            fair = FairOddsPayload.FromDict(doc.RootElement);
        }
        catch (JsonException ex)
        {
            _log.LogError(ex, "[MSE] JSON inválido em fair_odds:{Match}", matchId);
            return;
        }

        // Market Odds: O(1) lookup em ConcurrentDictionary — zero I/O
        var market = _marketCache.TryGet(matchId);
        if (market is null)
        {
            _log.LogWarning("[MSE] ABORT {Match} — market odds ausentes ou stale", matchId);
            return;
        }

        // Lê o estado de VORP para incluir no BetSignal (auditoria)
        var stateRaw   = await db.StringGetAsync(STATE_KEY_PREFIX + matchId);
        var state      = stateRaw.HasValue
            ? JsonSerializer.Deserialize<LineupState>(stateRaw.ToString())
            : null;

        // T4: clock tick estrito ANTES da aritmética de edge (não depois)
        var t4 = DateTimeOffset.UtcNow;

        var signals = ComputeEdge(matchId, fair, market, state, t4).ToList();

        await _audit.MarkMarketReadAsync(matchId, "combined", t4);

        if (!signals.Any())
        {
            _log.LogDebug("[MSE] {Match} — sem edge na janela [{Min:P0},{Max:P0}]",
                matchId, _minEdge, _maxEdge);
            return;
        }

        var pub = _redis.GetSubscriber();
        foreach (var sig in signals)
        {
            var json = JsonSerializer.Serialize(sig);
            await pub.PublishAsync(RedisChannel.Literal(BET_SIGNAL_CHANNEL), json);
            _log.LogInformation(
                "[MSE] BetSignal {Match} {Mkt}/{Sel}: edge={E:+0.00%} kelly={K:P2} " +
                "fair={F:F3} market={M:F3} E2E={L:F1}ms {SLA}",
                sig.MatchId, sig.Market, sig.Selection,
                sig.EdgeVsPrice, sig.KellyStake,
                sig.PModel > 0 ? 1.0 / sig.PModel : 0, sig.OddsOffered,
                sig.PipelineLatencyMs,
                sig.PipelineLatencyMs <= _budgetMs ? "✓" : "⚠ LATE");
        }
    }

    // ---------------------------------------------------------------------------
    // Aritmética de edge (puramente em RAM, sem I/O)
    // ---------------------------------------------------------------------------

    private IEnumerable<BetSignal> ComputeEdge(
        string matchId, FairOddsPayload fair, MarketOdds market,
        LineupState? state, DateTimeOffset t4)
    {
        var dvh = state?.DeltaVorpHome ?? 0;
        var dva = state?.DeltaVorpAway ?? 0;
        var e2e = state != null
            ? (t4 - state.LineupCapturedAt).TotalMilliseconds
            : 0;

        // Iteração sobre os mercados disponíveis
        var candidates = new[]
        {
            (Market: "1x2", Sel: "home",  FairOdd: fair.Home,    MarketOdd: market.OddsHome),
            (Market: "1x2", Sel: "draw",  FairOdd: fair.Draw,    MarketOdd: market.OddsDraw),
            (Market: "1x2", Sel: "away",  FairOdd: fair.Away,    MarketOdd: market.OddsAway),
            (Market: "ou25", Sel: "over",  FairOdd: fair.Over25,  MarketOdd: market.OddsOver25 ?? 0),
            (Market: "ou25", Sel: "under", FairOdd: fair.Under25, MarketOdd: market.OddsUnder25 ?? 0),
        };

        foreach (var (mkt, sel, fairOdd, marketOdd) in candidates)
        {
            if (fairOdd is null || fairOdd <= 1.0 || marketOdd <= 1.0) continue;

            // p_model = 1 / fair_odd (justa, sem overround)
            var pModel  = 1.0 / fairOdd.Value;
            // edge vs preço de mercado (com vig)
            var edge    = pModel - 1.0 / marketOdd;

            if (edge < _minEdge || edge > _maxEdge) continue;

            var kelly   = Math.Min(_kellyFrac * edge / (marketOdd - 1.0), 0.05);

            yield return new BetSignal(
                MatchId:            matchId,
                Market:             mkt,
                Selection:          sel,
                PModel:             pModel,
                OddsOffered:        marketOdd,
                EdgeVsPrice:        edge,
                KellyStake:         kelly,
                DeltaVorpHome:      dvh,
                DeltaVorpAway:      dva,
                IssuedAt:           t4,
                PipelineLatencyMs:  e2e
            );
        }
    }

    // ---------------------------------------------------------------------------
    // Invocação do Kernel (C# → Redis → Python) — chamada pelo Worker após T2
    // ---------------------------------------------------------------------------

    public async Task InvokeKernelAsync(
        string matchId, double eloA, double eloB,
        double dvorpA, double dvorpB)
    {
        var payload = new KernelInvokePayload(
            match_id:    matchId,
            elo_a:       eloA,
            elo_b:       eloB,
            dvorp_a:     dvorpA,
            dvorp_b:     dvorpB,
            timestamp_t3: DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()
        );
        var json = JsonSerializer.Serialize(payload);
        await _redis.GetSubscriber().PublishAsync(
            RedisChannel.Literal(KERNEL_INVOKE_CHANNEL), json);
    }
}
