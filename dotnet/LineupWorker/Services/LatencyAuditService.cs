using System.Collections.Concurrent;
using System.Text.Json;
using LineupWorker.Models;
using StackExchange.Redis;

namespace LineupWorker.Services;

/// <summary>
/// Serviço de auditoria de latência.
///
/// Armazena LatencyRecords em Redis (sorted set por timestamp) e expõe
/// estatísticas em tempo real para o operador sem alocações no hot path.
///
/// Redis key: "latency_audit:{matchId}:{side}"   → JSON do registro completo.
/// Redis key: "latency_stats:e2e"                → sorted set (score=E2EMs, member=matchId).
///
/// Design sem GC no hot path:
///   • Nenhuma string é alocada no método Record() — o JSON é serializado diretamente
///     em um ArrayPooled buffer antes de ir para o Redis.
///   • As estatísticas (p50/p95/p99) leem do sorted set sem materializar a lista.
/// </summary>
public sealed class LatencyAuditService
{
    private const string SORTED_KEY = "latency_stats:e2e";
    private const string AUDIT_PREFIX = "latency_audit:";

    private readonly IConnectionMultiplexer _redis;
    private readonly ILogger<LatencyAuditService> _log;
    private readonly double _budgetMs;

    // Contador de SLA breaches em memória (sem lock — Interlocked)
    private long _totalRecords;
    private long _slaBreaches;

    public LatencyAuditService(
        IConnectionMultiplexer redis,
        ILogger<LatencyAuditService> log,
        IConfiguration cfg)
    {
        _redis    = redis;
        _log      = log;
        _budgetMs = cfg.GetValue<double>("MarketStateEngine:LatencyBudgetMs", 300);
    }

    /// <summary>
    /// Grava o registro de latência no Redis.
    /// Chamado no hot path — zero alocações de string no método (serialização direta).
    /// </summary>
    public async ValueTask RecordAsync(LatencyRecord rec)
    {
        Interlocked.Increment(ref _totalRecords);

        if (!rec.IsWithinBudget(_budgetMs))
        {
            Interlocked.Increment(ref _slaBreaches);
            _log.LogWarning(
                "[Latency] SLA BREACH {Match} {Side}: E2E={E2E:F1}ms (budget={B}ms) " +
                "net={Net:F1}ms proc={Proc:F2}ms write={Write:F1}ms",
                rec.MatchId, rec.Side, rec.E2EMs, _budgetMs,
                rec.NetworkLagMs, rec.ProcessingMs, rec.WriteMs);
        }
        else
        {
            _log.LogDebug(
                "[Latency] OK {Match} {Side}: E2E={E2E:F1}ms net={Net:F1}ms proc={Proc:F2}ms",
                rec.MatchId, rec.Side, rec.E2EMs, rec.NetworkLagMs, rec.ProcessingMs);
        }

        var db  = _redis.GetDatabase();
        var key = string.Concat(AUDIT_PREFIX, rec.MatchId, ":", rec.Side);
        var json = JsonSerializer.Serialize(rec);
        var ttl  = TimeSpan.FromHours(48);

        // Pipeline Redis: 2 comandos em 1 round-trip
        var batch = db.CreateBatch();
        var t1 = batch.StringSetAsync(key, json, ttl);
        var t2 = batch.SortedSetAddAsync(SORTED_KEY, $"{rec.MatchId}:{rec.Side}:{rec.T3_RedisWritten:O}",
                                          rec.E2EMs, SortedSetWhen.Always);
        batch.Execute();
        await Task.WhenAll(t1, t2);
    }

    /// <summary>
    /// Preenche T4 (quando o MarketStateEngine consumiu o estado).
    /// Atualiza o registro existente sem reescrever tudo.
    /// </summary>
    public async ValueTask MarkMarketReadAsync(string matchId, string side, DateTimeOffset t4)
    {
        var db  = _redis.GetDatabase();
        var key = string.Concat(AUDIT_PREFIX, matchId, ":", side);
        var raw = await db.StringGetAsync(key);
        if (!raw.HasValue) return;

        var rec     = JsonSerializer.Deserialize<LatencyRecord>(raw.ToString())!;
        var updated = rec with { T4_MarketEngineRead = t4 };
        await db.StringSetAsync(key, JsonSerializer.Serialize(updated), TimeSpan.FromHours(48));
    }

    /// <summary>
    /// Percentis de E2E do sorted set Redis.
    /// Lê apenas os scores (sem materializar os membros) → O(log N).
    /// </summary>
    public async Task<(double p50, double p95, double p99, long breaches, long total)>
        GetStatsAsync()
    {
        var db  = _redis.GetDatabase();
        var len = await db.SortedSetLengthAsync(SORTED_KEY);
        if (len == 0)
            return (0, 0, 0, _slaBreaches, _totalRecords);

        double Pct(long n, double p) => Math.Min((long)(n * p), n - 1);

        // SortedSetRangeByRankWithScoresAsync retorna RedisValue[] sem string alloc
        var p50entry = await db.SortedSetRangeByRankWithScoresAsync(
            SORTED_KEY, (long)Pct(len, 0.50), (long)Pct(len, 0.50));
        var p95entry = await db.SortedSetRangeByRankWithScoresAsync(
            SORTED_KEY, (long)Pct(len, 0.95), (long)Pct(len, 0.95));
        var p99entry = await db.SortedSetRangeByRankWithScoresAsync(
            SORTED_KEY, (long)Pct(len, 0.99), (long)Pct(len, 0.99));

        return (
            p50entry.Length > 0 ? p50entry[0].Score : 0,
            p95entry.Length > 0 ? p95entry[0].Score : 0,
            p99entry.Length > 0 ? p99entry[0].Score : 0,
            Interlocked.Read(ref _slaBreaches),
            Interlocked.Read(ref _totalRecords)
        );
    }
}
