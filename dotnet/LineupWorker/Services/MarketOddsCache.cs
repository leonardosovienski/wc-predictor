using System.Collections.Concurrent;
using System.Net.WebSockets;
using System.Text;
using System.Text.Json;
using LineupWorker.Models;

namespace LineupWorker.Services;

/// <summary>
/// MarketOddsCache — cache em memória das True Odds, atualizado via WebSocket.
///
/// Contrato 3: Exchange → C# via WebSocket (Pinnacle/ISN).
/// Todas as leituras são O(1) no ConcurrentDictionary — nenhum I/O no hot path T4.
///
/// WebSocket lifecycle:
///   • Conecta no StartAsync e mantém a conexão ativa com ping/pong.
///   • Reconecta automaticamente com backoff exponencial em caso de drop.
///   • Mensagens chegam como JSON e são parseadas sobre ReadOnlySpan<byte>
///     (zero alocação de string intermediária no parser).
///
/// NOTA: As credenciais (ApiKey, WsUrl) ficam em appsettings.json / env vars
/// prefixados com LINEUP_ — nunca hardcoded.
/// </summary>
public sealed class MarketOddsCache : BackgroundService
{
    private const int RECV_BUFFER_SIZE = 8 * 1024;   // 8 KB por mensagem
    private static readonly TimeSpan ODDS_MAX_AGE = TimeSpan.FromSeconds(30);
    private static readonly TimeSpan RECONNECT_BASE = TimeSpan.FromSeconds(1);
    private const int MAX_RECONNECT_DELAY_SEC = 30;

    // Leitura O(1) lock-free no hot path T4
    private readonly ConcurrentDictionary<string, MarketOdds> _cache = new();

    private readonly ILogger<MarketOddsCache> _log;
    private readonly string _wsUrl;
    private readonly string _apiKey;

    public MarketOddsCache(ILogger<MarketOddsCache> log, IConfiguration cfg)
    {
        _log    = log;
        _wsUrl  = cfg["Exchange:WebSocketUrl"]  ?? "wss://exchange.example.com/odds/ws";
        _apiKey = cfg["Exchange:ApiKey"]         ?? "";
    }

    /// <summary>Leitura O(1) — chamada no hot path T4. Null se match não está em cache.</summary>
    public MarketOdds? TryGet(string matchId)
    {
        if (!_cache.TryGetValue(matchId, out var odds)) return null;
        return odds.IsFresh(ODDS_MAX_AGE) ? odds : null;
    }

    protected override async Task ExecuteAsync(CancellationToken ct)
    {
        int attempt = 0;
        while (!ct.IsCancellationRequested)
        {
            try
            {
                await ConnectAndListenAsync(ct);
                attempt = 0;   // reset em conexão bem-sucedida
            }
            catch (OperationCanceledException) { break; }
            catch (Exception ex)
            {
                attempt++;
                var delay = TimeSpan.FromSeconds(
                    Math.Min(RECONNECT_BASE.TotalSeconds * Math.Pow(2, attempt - 1),
                             MAX_RECONNECT_DELAY_SEC));
                _log.LogError(ex, "[MarketOdds] desconectado (attempt={A}), reconectando em {D:F1}s",
                    attempt, delay.TotalSeconds);
                await Task.Delay(delay, ct);
            }
        }
    }

    private async Task ConnectAndListenAsync(CancellationToken ct)
    {
        using var ws = new ClientWebSocket();
        ws.Options.SetRequestHeader("X-Api-Key", _apiKey);

        _log.LogInformation("[MarketOdds] conectando a {Url}", _wsUrl);
        await ws.ConnectAsync(new Uri(_wsUrl), ct);
        _log.LogInformation("[MarketOdds] WebSocket conectado.");

        // Subscreve partidas ao vivo (payload depende da API do exchange)
        var sub = JsonSerializer.SerializeToUtf8Bytes(new { action = "subscribe", markets = new[] { "1x2", "ou25" } });
        await ws.SendAsync(sub, WebSocketMessageType.Text, true, ct);

        var buffer = new byte[RECV_BUFFER_SIZE];
        var msgBuffer = new System.IO.MemoryStream(RECV_BUFFER_SIZE);

        while (!ct.IsCancellationRequested && ws.State == WebSocketState.Open)
        {
            msgBuffer.SetLength(0);
            WebSocketReceiveResult result;
            do
            {
                result = await ws.ReceiveAsync(buffer, ct);
                if (result.MessageType == WebSocketMessageType.Close) return;
                msgBuffer.Write(buffer, 0, result.Count);
            }
            while (!result.EndOfMessage);

            // Parse sobre ReadOnlyMemory<byte> — zero string intermediária.
            // JsonDocument.Parse aceita ReadOnlyMemory<byte> (não ReadOnlySpan,
            // pois o documento pode reter a referência ao buffer).
            if (!msgBuffer.TryGetBuffer(out var seg)) continue;
            ParseAndUpdate(new ReadOnlyMemory<byte>(seg.Array!, seg.Offset, (int)msgBuffer.Length));
        }
    }

    private void ParseAndUpdate(ReadOnlyMemory<byte> data)
    {
        try
        {
            using var doc = JsonDocument.Parse(data);
            var root = doc.RootElement;

            // Formato esperado do exchange (adaptar por provider):
            // { "match_id": "9021", "home": 2.41, "draw": 3.10, "away": 3.25,
            //   "over25": 2.15, "under25": 1.75, "source": "pinnacle" }
            if (!root.TryGetProperty("match_id", out var midEl)) return;
            var matchId = midEl.GetString() ?? "";

            double Get(string key) => root.TryGetProperty(key, out var v) ? v.GetDouble() : 0.0;
            double? GetOpt(string key) => root.TryGetProperty(key, out var v) ? v.GetDouble() : null;

            var odds = new MarketOdds(
                MatchId:     matchId,
                OddsHome:    Get("home"),
                OddsDraw:    Get("draw"),
                OddsAway:    Get("away"),
                OddsOver25:  GetOpt("over25"),
                OddsUnder25: GetOpt("under25"),
                LastUpdated: DateTimeOffset.UtcNow,
                Source:      root.TryGetProperty("source", out var s) ? s.GetString() ?? "" : "unknown"
            );

            _cache[matchId] = odds;
        }
        catch (JsonException ex)
        {
            _log.LogWarning(ex, "[MarketOdds] JSON inválido do exchange");
        }
    }
}
