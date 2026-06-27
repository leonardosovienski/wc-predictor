"""Coleta do Sofascore: por jogo, extrai placar, xG, odds 1X2 e nota por jogador.

A coleta roda na máquina do usuário (a rede do sandbox bloqueia o Sofascore).
Competições e season_id ficam em config.yaml (sofascore.competitions). Para
descobrir o season_id de uma competição: `python -m src.ingest_sofascore --seasons UT_ID`.
"""
import re
import sys
import time
from datetime import datetime, timezone

from . import db
from .ingest import ROOT, load_config
from .obs import get_logger, setup_logging

log = get_logger()
# Sofascore (curl_cffi) é importado DENTRO de run(), não aqui: os parsers e o
# guard is_pre_match são funções puras e a suíte de testes os importa sem
# precisar do cliente HTTP instalado.


def frac_to_decimal(choice: dict):
    """Sofascore dá odds como fração ('5/2'). Converte para decimal (3.5).
    Fronteira com payload externo: formato inesperado vira None, nunca exceção
    — um choice ruim não pode derrubar a coleta do evento inteiro."""
    fv = choice.get("fractionalValue")
    if not fv:
        dv = choice.get("decimalValue")
        try:
            return float(dv) if dv else None
        except (TypeError, ValueError):
            return None
    try:
        num, den = fv.split("/")
        return round(1 + float(num) / float(den), 3)
    except (ValueError, ZeroDivisionError, AttributeError, TypeError):
        return None


def is_pre_match(start_ts, now=None) -> bool:
    """Estritamente pré-jogo: o apito inicial está no FUTURO.

    É o guard que protege a métrica de CLV: odd ao vivo (jogo em andamento)
    não é abertura — gravá-la como open contaminaria a única população onde o
    CLV carrega sinal. `not finished` é insuficiente: in-play também não está
    finished. Sem start_ts conhecido, assume NÃO-pré-jogo (conservador: melhor
    perder uma abertura do que gravar uma falsa).

    Unidade: epoch em SEGUNDOS. Timestamp em milissegundos fica ~1000× maior,
    sempre "futuro", e aprovaria jogo encerrado como pré-jogo — o guard pareceria
    ativo estando desligado. Ordem de grandeza suspeita ⇒ NÃO-pré-jogo, pela
    mesma regra conservadora."""
    if not start_ts:
        return False
    if start_ts > 1e11:        # 13 dígitos: milissegundos, unidade errada
        return False
    if now is None:
        now = int(time.time())
    return start_ts > now


def parse_match(ev: dict):
    ts = ev.get("startTimestamp")
    if ts and ts > 1e11:       # Sofascore trocou a unidade pra ms: normaliza
        log.warning("startTimestamp em milissegundos (%s) — normalizando", ts)
        ts = int(ts // 1000)
    date = datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d") if ts else None
    finished = ev.get("status", {}).get("type") == "finished"
    return {
        "event_id": ev["id"],
        "date": date,
        "start_ts": ts,
        "finished": finished,
        "home_team": ev.get("homeTeam", {}).get("name"),
        "away_team": ev.get("awayTeam", {}).get("name"),
        "home_score": ev.get("homeScore", {}).get("current") if finished else None,
        "away_score": ev.get("awayScore", {}).get("current") if finished else None,
    }


def parse_xg(stats: dict):
    for period in (stats or {}).get("statistics", []):
        if period.get("period") != "ALL":
            continue
        for group in period.get("groups", []):
            for item in group.get("statisticsItems", []):
                if "expected goals" in item.get("name", "").lower():
                    try:
                        return float(item["home"]), float(item["away"])
                    except (ValueError, KeyError, TypeError):
                        return None, None
    return None, None


def parse_odds(odds: dict):
    for market in (odds or {}).get("markets", []):
        name = market.get("marketName", "").lower()
        if "full time" in name or market.get("marketId") == 1:
            out = {}
            for choice in market.get("choices", []):
                out[choice.get("name")] = frac_to_decimal(choice)
            return out.get("1"), out.get("X"), out.get("2")
    return None, None, None


# handicap no fim do nome do choice ('Over 2.5' → '2.5')
_HANDICAP = re.compile(r"(\d+(?:\.\d+)?)\s*$")


def parse_ou(odds: dict, line: float = 2.5):
    """Odd de Over/Under na linha principal de gols (default 2.5).
    O mercado de totais do Sofascore carrega o handicap em `choice.name`
    ('Over 2.5') ou no `market.choiceGroup`. A comparação é NUMÉRICA: matching
    por substring deixava a linha 12.5 sobrescrever a 2.5 sem exceção e a odd
    errada entrava no banco calada. Retorna (over, under)."""
    for market in (odds or {}).get("markets", []):
        name = market.get("marketName", "").lower()
        if "total" not in name and "over/under" not in name and "goals" not in name:
            continue
        group = market.get("choiceGroup")
        over = under = None
        for choice in market.get("choices", []):
            cname = (choice.get("name") or "").lower()
            m = _HANDICAP.search(cname)
            handicap = m.group(1) if m else group
            try:
                if handicap is None or float(handicap) != line:
                    continue
            except (TypeError, ValueError):
                continue
            if "over" in cname:
                over = frac_to_decimal(choice)
            elif "under" in cname:
                under = frac_to_decimal(choice)
        if over and under:
            return over, under
    return None, None


def parse_ratings(lineups: dict, home_name: str, away_name: str, event_id: int):
    rows = []
    for side, team in (("home", home_name), ("away", away_name)):
        for p in (lineups or {}).get(side, {}).get("players", []):
            st = p.get("statistics", {})
            rating = st.get("rating")
            if rating is None:
                continue
            rows.append((event_id, p.get("player", {}).get("name"), team,
                         float(rating), st.get("minutesPlayed")))
    return rows


def run(seasons_for: int | None = None) -> None:
    from .sofascore import Sofascore   # lazy: só quem coleta precisa do curl_cffi
    setup_logging(ROOT / "data")
    cfg = load_config()
    scfg = cfg.get("sofascore", {})
    client = Sofascore(rate_limit=float(scfg.get("rate_limit_seconds", 1.5)),
                       cache_dir=str(ROOT / scfg["cache_dir"]) if scfg.get("cache_dir") else None)

    if seasons_for:  # modo descoberta de season_id
        for sid, year in client.list_seasons(seasons_for):
            log.info("season_id=%s  year=%s", sid, year)
        return

    comps = scfg.get("competitions")
    if not comps:
        sys.exit("nada em sofascore.competitions no config.yaml")
    conn = db.connect(str(ROOT / cfg["database"]))

    n_matches = n_ratings = 0
    for comp in comps:
        name, season = comp["name"], str(comp["season"])
        try:
            events = client.season_events(comp["ut_id"], comp["season_id"],
                                          upcoming=comp.get("upcoming", False))
        except Exception as e:
            log.error("coleta de %s falhou: %s", name, e)
            continue
        total = len(events)
        log.info("%s: %d jogos a coletar (~%.0fs com rate limit)...",
                 name, total, total * client.rate * 2)
        for i, ev in enumerate(events, 1):
            m = parse_match(ev)
            eid = m["event_id"]
            try:
                # cache só pra jogo encerrado: odd é dado temporal (ver sofascore._get)
                raw_odds = client.event_odds(eid, finished=m["finished"])
                oh, od, oa = parse_odds(raw_odds)
                ou_line = cfg.get("backtest", {}).get("over_under_line", 2.5)
                o_over, o_under = parse_ou(raw_odds, ou_line)

                # ABERTURA = primeira odd observada ESTRITAMENTE PRÉ-apito.
                # is_pre_match (start futuro) — não basta "não terminou": jogo
                # em andamento também não terminou, e odd in-play gravada como
                # open contaminaria a população onde o CLV carrega sinal. O
                # COALESCE preserva a abertura legítima já capturada antes.
                pre = is_pre_match(m["start_ts"])
                if pre:
                    opens = (oh, od, oa, o_over, o_under)
                else:
                    opens = (None, None, None, None, None)

                if m["finished"]:
                    hxg, axg = parse_xg(client.event_statistics(eid))
                    ratings = parse_ratings(client.event_lineups(eid),
                                            m["home_team"], m["away_team"], eid)
                else:                       # fixture futuro: só odds
                    hxg = axg = None
                    ratings = []
                db.upsert_ss_matches(conn, [(eid, name, season, m["date"],
                    m["home_team"], m["away_team"], m["home_score"], m["away_score"],
                    hxg, axg, oh, od, oa, o_over, o_under, *opens)])

                # série temporal: toda coleta vira foto (append-only, idempotente).
                # pre_match usa o MESMO guard estrito — foto in-play fica marcada
                # 0 e o backtest/análise filtra a população certa por construção.
                now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                snaps = [(eid, now, "1x2", sel, odd, int(pre))
                         for sel, odd in (("home", oh), ("draw", od), ("away", oa)) if odd]
                snaps += [(eid, now, f"ou{ou_line}", sel, odd, int(pre))
                          for sel, odd in (("over", o_over), ("under", o_under)) if odd]
                if snaps:
                    db.insert_snapshots(conn, snaps)

                if ratings:
                    db.upsert_ss_ratings(conn, ratings)
                    n_ratings += len(ratings)
                n_matches += 1
                # aviso de progresso por jogo: placar (disputado) ou "fixture"
                placar = (f"{m['home_score']}x{m['away_score']}"
                          if m["finished"] else "fixture")
                log.info("  [%d/%d] %s %s %s", i, total,
                         m["home_team"], placar, m["away_team"])
            except Exception as e:
                log.warning("evento %s falhou: %s", eid, e)
        log.info("%s: %d jogos processados", name, len(events))
    log.info("sofascore_matches: %d | sofascore_player_ratings: %d", n_matches, n_ratings)


if __name__ == "__main__":
    arg = sys.argv[1:] 
    if arg and arg[0] == "--seasons" and len(arg) > 1:
        sys.exit(run(seasons_for=int(arg[1])))
    sys.exit(run())
