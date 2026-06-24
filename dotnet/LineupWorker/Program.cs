using LineupWorker;
using LineupWorker.Services;
using StackExchange.Redis;

var host = Host.CreateDefaultBuilder(args)
    .ConfigureAppConfiguration((ctx, cfg) =>
    {
        cfg.AddJsonFile("appsettings.json", optional: false, reloadOnChange: false);
        cfg.AddEnvironmentVariables(prefix: "LINEUP_");   // override via env: LINEUP_Worker__LineupTimeoutMinutes=60
    })
    .ConfigureServices((ctx, services) =>
    {
        var redisConn = ctx.Configuration.GetConnectionString("Redis") ?? "localhost:6379";

        // Redis: singleton thread-safe; ConfigurationOptions para fine-tuning de latência
        services.AddSingleton<IConnectionMultiplexer>(_ =>
        {
            var opts = ConfigurationOptions.Parse(redisConn);
            opts.SocketManager    = SocketManager.ThreadPool;     // evita thread starvation
            opts.ReconnectRetryPolicy = new LinearRetry(500);     // reconecta a cada 500ms
            return ConnectionMultiplexer.Connect(opts);
        });

        // VorpStateService: warm-up síncrono na inicialização — DEVE completar antes
        // do Worker começar a processar escalações. IHostedService garante a ordem
        // de StartAsync pelo registro (VorpState primeiro, Worker depois).
        services.AddSingleton<VorpStateService>();
        services.AddHostedService(sp => sp.GetRequiredService<VorpStateService>());

        // LatencyAuditService: singleton compartilhado entre Worker e MarketStateEngine
        services.AddSingleton<LatencyAuditService>();

        // MarketOddsCache: singleton que mantém True Odds via WebSocket (Zona 2 - Contrato 3)
        services.AddSingleton<MarketOddsCache>();
        services.AddHostedService(sp => sp.GetRequiredService<MarketOddsCache>());

        // MarketStateEngine (Zona 2): singleton para que o Worker possa chamar InvokeKernelAsync
        services.AddSingleton<MarketStateEngine>();
        services.AddHostedService(sp => sp.GetRequiredService<MarketStateEngine>());

        // Worker principal (Hot Path — Zona 1)
        services.AddHostedService<LineupWorkerService>();

        // Health check periódico: imprime p50/p95/p99 de latência a cada 5 min
        services.AddHostedService<LatencyReporterService>();
    })
    .Build();

await host.RunAsync();

// ---------------------------------------------------------------------------
// Serviço auxiliar: relatório de latência periódico (não é hot path)
// ---------------------------------------------------------------------------
namespace LineupWorker
{
    internal sealed class LatencyReporterService : BackgroundService
    {
        private readonly LatencyAuditService _audit;
        private readonly ILogger<LatencyReporterService> _log;

        public LatencyReporterService(LatencyAuditService audit,
                                      ILogger<LatencyReporterService> log)
        {
            _audit = audit;
            _log   = log;
        }

        protected override async Task ExecuteAsync(CancellationToken ct)
        {
            while (!ct.IsCancellationRequested)
            {
                await Task.Delay(TimeSpan.FromMinutes(5), ct);
                var (p50, p95, p99, breaches, total) = await _audit.GetStatsAsync();
                _log.LogInformation(
                    "[LatencyReport] E2E p50={P50:F1}ms p95={P95:F1}ms p99={P99:F1}ms " +
                    "| SLA breaches={B}/{T} ({Pct:P1})",
                    p50, p95, p99, breaches, total,
                    total > 0 ? (double)breaches / total : 0);
            }
        }
    }
}
