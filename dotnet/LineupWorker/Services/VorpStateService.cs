using System.Text.Json;
using StackExchange.Redis;

namespace LineupWorker.Services;

/// <summary>
/// Serviço de warm-up: carrega VORP e Replacement Levels do artefato JSON produzido
/// pelo src/research/vorp_ridge.py e os mantém em memória para consulta O(1).
///
/// Ciclo de vida: singleton — aquece uma vez na inicialização do host.
/// </summary>
public sealed class VorpStateService : IHostedService
{
    private readonly ILogger<VorpStateService> _log;
    private readonly IConfiguration _cfg;

    // Estruturas em memória — imutáveis após warm-up
    private IReadOnlyDictionary<string, double> _vorpByPlayer  = new Dictionary<string, double>();
    private IReadOnlyDictionary<string, double> _replacementByPos = new Dictionary<string, double>();
    private IReadOnlyDictionary<string, double[]> _titularidadeByTeam = new Dictionary<string, double[]>();

    private bool _ready;

    public VorpStateService(ILogger<VorpStateService> log, IConfiguration cfg)
    {
        _log = log;
        _cfg = cfg;
    }

    public Task StartAsync(CancellationToken ct)
    {
        var artifactPath = _cfg["Vorp:ArtifactPath"] ?? "data/vorp.json";
        _log.LogInformation("[VorpState] aquecendo de {Path}", artifactPath);

        using var stream = File.OpenRead(artifactPath);
        var doc = JsonDocument.Parse(stream);
        var root = doc.RootElement;

        _vorpByPlayer = root.GetProperty("beta_players")
            .EnumerateObject()
            .ToDictionary(p => p.Name, p => p.Value.GetDouble());

        _replacementByPos = root.GetProperty("replacement_levels")
            .EnumerateObject()
            .ToDictionary(p => p.Name, p => p.Value.GetDouble());

        // Titularidade histórica por time (opcional — arquivo separado)
        var titPath = _cfg["Vorp:TitularidadePath"];
        if (titPath != null && File.Exists(titPath))
        {
            using var tstream = File.OpenRead(titPath);
            var tdoc = JsonDocument.Parse(tstream);
            _titularidadeByTeam = tdoc.RootElement
                .EnumerateObject()
                .ToDictionary(
                    p => p.Name,
                    p => p.Value.EnumerateArray().Select(v => v.GetDouble()).ToArray()
                );
        }

        _ready = true;
        _log.LogInformation("[VorpState] pronto — {N} jogadores, {P} posições",
            _vorpByPlayer.Count, _replacementByPos.Count);

        return Task.CompletedTask;
    }

    public Task StopAsync(CancellationToken ct) => Task.CompletedTask;

    public bool IsReady => _ready;

    /// <summary>Retorna VORP do jogador (O(1)). Fallback: Replacement Level da posição.</summary>
    public double GetVorp(string player, string position)
    {
        if (_vorpByPlayer.TryGetValue(player, out var v))
            return v;
        if (_replacementByPos.TryGetValue(position, out var rv))
            return rv;
        return _replacementByPos.GetValueOrDefault("UNKNOWN", 0.0);
    }

    /// <summary>Delta VORP de um lineup completo: soma dos VORPs dos 11 titulares.</summary>
    public double ComputeDeltaVorp(IEnumerable<(string Player, string Position)> starters)
        => starters.Sum(s => GetVorp(s.Player, s.Position));

    /// <summary>Retorna a matriz de probabilidade de titularidade histórica do time.
    /// Usada no fallback de timeout. null se não disponível.</summary>
    public double[]? GetTitularidadeMatrix(string team)
        => _titularidadeByTeam.GetValueOrDefault(team);
}
