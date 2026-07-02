"""Sonda de diagnóstico do Sofascore — descobre, sem adivinhar, QUAIS mercados de
odds e QUAIS estatísticas a API realmente entrega para um evento.

Motivação: o parser atual (ingest_sofascore.py) só extrai 1X2 + Over/Under 2.5
das odds, e só "expected goals" das estatísticas. Mas a resposta crua provavelmente
traz muito mais (BTTS, handicap, escanteios, cartões...). Antes de expandir o modelo
para precificar novos mercados, precisamos VER o que existe — não supor nomes de campo.

Roda na máquina do usuário (a rede do sandbox bloqueia o Sofascore). Faz 3 chamadas
read-only e salva o cru + um resumo em data/research/. NÃO escreve no banco.

USO:
    # auto-seleciona um fixture futuro da base
    python -m src.research.sofascore_probe

    # ou aponta um event_id específico
    python -m src.research.sofascore_probe --event-id 14025190
"""
import argparse
import json
import sys
from pathlib import Path

from .. import db
from ..ingest import ROOT, load_config


# ------------------------------------------------------------------ #
# Helpers PUROS (testáveis sem rede) — espelham a estrutura real da   #
# resposta: odds = {markets:[{marketName, marketId, choiceGroup,      #
# choices:[{name, fractionalValue, decimalValue}]}]};                 #
# statistics = {statistics:[{period, groups:[{groupName,              #
# statisticsItems:[{name, home, away}]}]}]}.                          #
# ------------------------------------------------------------------ #

def summarize_odds(raw: dict | None) -> dict:
    """Resume a resposta de event_odds: lista de mercados com seus choices.
    Não interpreta — só expõe o que veio, para o desenho da expansão ser fato."""
    markets = (raw or {}).get("markets", []) or []
    out = []
    for m in markets:
        out.append({
            "marketId": m.get("marketId"),
            "marketName": m.get("marketName"),
            "choiceGroup": m.get("choiceGroup"),
            "choices": [c.get("name") for c in (m.get("choices") or [])],
        })
    return {"n_markets": len(out), "markets": out}


def summarize_statistics(raw: dict | None) -> dict:
    """Resume event_statistics: por período, os nomes dos statisticsItems
    disponíveis (chutes, posse, escanteios, cartões, faltas...)."""
    periods = (raw or {}).get("statistics", []) or []
    out = []
    for period in periods:
        items = []
        for group in period.get("groups", []) or []:
            for it in group.get("statisticsItems", []) or []:
                items.append(it.get("name"))
        out.append({"period": period.get("period"), "items": items})
    return {"n_periods": len(out), "periods": out}


def summarize_lineups(raw: dict | None) -> dict:
    """Resume event_lineups: chaves de statistics disponíveis por jogador
    (minutos, chutes, notas...) — base para mercados de jogador."""
    sample_keys = set()
    n_players = 0
    for side in ("home", "away"):
        for p in (raw or {}).get(side, {}).get("players", []) or []:
            n_players += 1
            sample_keys.update((p.get("statistics") or {}).keys())
    return {"n_players": n_players, "player_stat_keys": sorted(sample_keys)}


# ------------------------------------------------------------------ #
# Seleção de evento + execução                                        #
# ------------------------------------------------------------------ #

def _pick_event(conn) -> int | None:
    """Prefere um fixture FUTURO (sem placar) — onde as odds estão vivas.
    Cai para o evento mais recente se não houver fixture pendente."""
    row = conn.execute(
        "SELECT event_id FROM sofascore_matches "
        "WHERE home_score IS NULL ORDER BY date LIMIT 1").fetchone()
    if row:
        return row[0]
    row = conn.execute(
        "SELECT event_id FROM sofascore_matches ORDER BY date DESC LIMIT 1").fetchone()
    return row[0] if row else None


def run(event_id: int | None = None) -> int:
    cfg = load_config()
    conn = db.connect(str(ROOT / cfg["database"]))

    if event_id is None:
        event_id = _pick_event(conn)
        if event_id is None:
            print("Nenhum event_id em sofascore_matches — rode a coleta primeiro.",
                  file=sys.stderr)
            return 1
    print(f"[probe] event_id = {event_id}")

    # Import lazy: o curl_cffi só é exigido de quem realmente coleta.
    from ..sofascore import Sofascore
    scfg = cfg.get("sofascore", {})
    client = Sofascore(rate_limit=float(scfg.get("rate_limit_seconds", 1.5)))

    raw_odds = client.event_odds(event_id)            # fixture: odds ao vivo
    raw_stats = client.event_statistics(event_id)
    raw_lineups = client.event_lineups(event_id)

    report = {
        "event_id": event_id,
        "odds": summarize_odds(raw_odds),
        "statistics": summarize_statistics(raw_stats),
        "lineups": summarize_lineups(raw_lineups),
    }

    out_dir = ROOT / "data" / "research"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"sofascore_probe_{event_id}.json"
    out_path.write_text(json.dumps(
        {"summary": report,
         "raw_odds": raw_odds, "raw_statistics": raw_stats, "raw_lineups": raw_lineups},
        indent=2, ensure_ascii=False), encoding="utf-8")

    # Resumo no console (o que importa para o desenho da expansão)
    print(f"\n=== MERCADOS DE ODDS ({report['odds']['n_markets']}) ===")
    for m in report["odds"]["markets"]:
        print(f"  [{m['marketId']}] {m['marketName']}  choices={m['choices']}")
    print(f"\n=== ESTATÍSTICAS DISPONÍVEIS ===")
    for p in report["statistics"]["periods"]:
        print(f"  período {p['period']}: {p['items']}")
    print(f"\n=== STATS DE JOGADOR (chaves) ===")
    print(f"  {report['lineups']['n_players']} jogadores; chaves: {report['lineups']['player_stat_keys']}")
    print(f"\n[probe] cru + resumo salvos em: {out_path}")
    print("[probe] me envie esse arquivo (ou o resumo acima) para desenhar a expansão sobre fatos.")
    return 0


def _main() -> int:
    ap = argparse.ArgumentParser(description="Sonda de diagnóstico do Sofascore")
    ap.add_argument("--event-id", type=int, default=None,
                    help="event_id específico (default: auto — fixture futuro da base)")
    args = ap.parse_args()
    return run(event_id=args.event_id)


if __name__ == "__main__":
    sys.exit(_main())
