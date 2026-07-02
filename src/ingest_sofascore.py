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


def frac_to_decimal(choice: dict, key: str = "fractionalValue"):
    """Sofascore dá odds como fração ('5/2'). Converte para decimal (3.5).

    `key` escolhe o campo: 'fractionalValue' = preço ATUAL/fechamento (default);
    'initialFractionalValue' = preço de ABERTURA (vem inline no mesmo payload —
    destrava a população 'open' real sem esperar o cron coletar em dois tempos).

    Fronteira com payload externo: formato inesperado vira None, nunca exceção
    — um choice ruim não pode derrubar a coleta do evento inteiro. O fallback
    para decimalValue só vale para o fechamento (a abertura não tem campo decimal)."""
    fv = choice.get(key)
    if not fv:
        if key == "fractionalValue":
            dv = choice.get("decimalValue")
            try:
                return float(dv) if dv else None
            except (TypeError, ValueError):
                return None
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


def _safe_float(val):
    """Converte valor (possivelmente string com '%', 'm', 'km') para float."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val)
    for suffix in ('%', 'km', 'KM', 'm', 'M'):
        s = s.replace(suffix, '')
    s = s.strip()
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def parse_statistics(event_data):
    """
    Extrai TODAS as estatisticas do event_statistics.
    Retorna dict: {period: {stat_name: {'home': float, 'away': float}}}
    """
    if not event_data:
        return {}
    periods = event_data.get('statistics')
    if not periods:
        return {}
    if isinstance(periods, dict):
        periods = periods.get('periods', [])
    if not isinstance(periods, list):
        return {}
    result = {}
    for period in periods:
        period_name = period.get('period', 'ALL')
        groups = period.get('groups', [])
        period_stats = {}
        for group in groups:
            for item in group.get('statisticsItems', []):
                name = item.get('name')
                if not name:
                    continue
                home_val = _safe_float(item.get('home'))
                away_val = _safe_float(item.get('away'))
                if home_val is not None or away_val is not None:
                    period_stats[name] = {'home': home_val, 'away': away_val}
        if period_stats:
            result[period_name] = period_stats
    return result


def parse_statistics_flat(event_data, event_id):
    """
    Achata parse_statistics em linhas para insert no banco.
    Cada linha: {event_id, team, period, stat_name, value}
    """
    stats_dict = parse_statistics(event_data)
    rows = []
    for period, stats in stats_dict.items():
        for stat_name, vals in stats.items():
            for team in ('home', 'away'):
                value = vals.get(team)
                if value is not None:
                    rows.append({
                        'event_id': event_id,
                        'team': team,
                        'period': period,
                        'stat_name': stat_name,
                        'value': value
                    })
    return rows


def parse_odds(odds: dict, initial: bool = False):
    """1X2 (marketId 1). initial=True lê a ABERTURA (initialFractionalValue)."""
    key = "initialFractionalValue" if initial else "fractionalValue"
    for market in (odds or {}).get("markets", []):
        name = market.get("marketName", "").lower()
        if "full time" in name or market.get("marketId") == 1:
            out = {}
            for choice in market.get("choices", []):
                out[choice.get("name")] = frac_to_decimal(choice, key)
            return out.get("1"), out.get("X"), out.get("2")
    return None, None, None


# handicap no fim do nome do choice ('Over 2.5' → '2.5')
_HANDICAP = re.compile(r"(\d+(?:\.\d+)?)\s*$")


def parse_ou(odds: dict, line: float = 2.5, initial: bool = False):
    """Odd de Over/Under na linha principal de gols (default 2.5).
    O mercado de totais do Sofascore carrega o handicap em `choice.name`
    ('Over 2.5') ou no `market.choiceGroup`. A comparação é NUMÉRICA: matching
    por substring deixava a linha 12.5 sobrescrever a 2.5 sem exceção e a odd
    errada entrava no banco calada. Retorna (over, under).
    initial=True lê a ABERTURA (initialFractionalValue)."""
    key = "initialFractionalValue" if initial else "fractionalValue"
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
                over = frac_to_decimal(choice, key)
            elif "under" in cname:
                under = frac_to_decimal(choice, key)
        if over and under:
            return over, under
    return None, None


# Linha do handicap asiático embutida no nome do choice: "(-0.75) Croatia".
_AH_LINE_RE = re.compile(r"\(\s*([+-]?\d+(?:\.\d+)?)\s*\)\s*(.+)")


def _line_value(market: dict):
    """Linha (float) de um mercado de totais — vem em choiceGroup ('2.5')."""
    cg = market.get("choiceGroup")
    try:
        return float(cg) if cg is not None else None
    except (TypeError, ValueError):
        return None


def _same_team(a: str | None, b: str | None) -> bool:
    """Nomes vêm da MESMA fonte (Sofascore) no nome do choice e em parse_match,
    então a comparação é direta (case-insensitive). Sem _canon: aqui não há
    reconciliação com a base — isso é problema do backtest, não do parser."""
    return bool(a) and bool(b) and a.strip().lower() == b.strip().lower()


def parse_all_odds(odds: dict, home_name: str | None = None,
                   away_name: str | None = None, initial: bool = False) -> dict:
    """Extrai TODOS os mercados derivados da grade de gols do payload de odds.

    Estrutura confirmada via probe (sofascore_probe_15186624.json):
      marketId 1=1X2, 2=DC, 4=DNB, 5=BTTS, 9=OU (linha em choiceGroup),
      17=AH (linha+time no nome do choice),
      20=cards, 21=corners (estrutura igual ao OU).
    initial=True lê a ABERTURA (initialFractionalValue) em vez do fechamento.
    odd ausente/ilegível vira None (nunca exceção — fronteira com payload externo).
    """
    key = "initialFractionalValue" if initial else "fractionalValue"
    out = {"1x2": {}, "dc": {}, "dnb": {}, "btts": {}, "ou": {}, "ah": {},
           "cards": {}, "corners": {}}   # <-- adicionado
    for market in (odds or {}).get("markets", []) or []:
        mid = market.get("marketId")
        choices = market.get("choices", []) or []

        if mid == 1:
            for c in choices:
                out["1x2"][c.get("name")] = frac_to_decimal(c, key)
        elif mid == 2:
            for c in choices:
                out["dc"][c.get("name")] = frac_to_decimal(c, key)
        elif mid == 4:
            for c in choices:
                out["dnb"][c.get("name")] = frac_to_decimal(c, key)
        elif mid == 5:
            for c in choices:
                out["btts"][c.get("name")] = frac_to_decimal(c, key)
        elif mid == 9:
            line = _line_value(market)
            if line is None:
                continue
            over = under = None
            for c in choices:
                nm = (c.get("name") or "").strip().lower()
                if nm == "over":
                    over = frac_to_decimal(c, key)
                elif nm == "under":
                    under = frac_to_decimal(c, key)
            out["ou"][line] = {"Over": over, "Under": under}
        elif mid == 17:
            home_line = None
            entry = {}
            for c in choices:
                m = _AH_LINE_RE.match((c.get("name") or "").strip())
                if not m:
                    continue
                line, team = float(m.group(1)), m.group(2).strip()
                odd = frac_to_decimal(c, key)
                if _same_team(team, home_name):
                    home_line, entry["home"] = line, odd
                elif _same_team(team, away_name):
                    entry["away"] = odd
            if home_line is not None and entry:
                out["ah"][home_line] = entry
        # ===== NOVOS MERCADOS =====
        elif mid == 20:   # cartões
            line = _line_value(market)
            if line is None:
                continue
            over = under = None
            for c in choices:
                nm = (c.get("name") or "").strip().lower()
                if nm == "over":
                    over = frac_to_decimal(c, key)
                elif nm == "under":
                    under = frac_to_decimal(c, key)
            out["cards"][line] = {"Over": over, "Under": under}
        elif mid == 21:   # escanteios
            line = _line_value(market)
            if line is None:
                continue
            over = under = None
            for c in choices:
                nm = (c.get("name") or "").strip().lower()
                if nm == "over":
                    over = frac_to_decimal(c, key)
                elif nm == "under":
                    under = frac_to_decimal(c, key)
            out["corners"][line] = {"Over": over, "Under": under}
    return out


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
    from .sofascore import Sofascore
    setup_logging(ROOT / "data")
    cfg = load_config()
    scfg = cfg.get("sofascore", {})
    client = Sofascore(rate_limit=float(scfg.get("rate_limit_seconds", 1.5)),
                       cache_dir=str(ROOT / scfg["cache_dir"]) if scfg.get("cache_dir") else None)

    if seasons_for:
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
                raw_odds = client.event_odds(eid, finished=m["finished"])
                oh, od, oa = parse_odds(raw_odds)
                ou_line = cfg.get("backtest", {}).get("over_under_line", 2.5)
                o_over, o_under = parse_ou(raw_odds, ou_line)

                oh_o, od_o, oa_o = parse_odds(raw_odds, initial=True)
                o_over_o, o_under_o = parse_ou(raw_odds, ou_line, initial=True)
                opens = (oh_o, od_o, oa_o, o_over_o, o_under_o)

                pre = is_pre_match(m["start_ts"])

                if m["finished"]:
                    stats_data = client.event_statistics(eid)
                    hxg, axg = parse_xg(stats_data)
                    ratings = parse_ratings(client.event_lineups(eid),
                                            m["home_team"], m["away_team"], eid)
                else:
                    hxg = axg = None
                    ratings = []

                db.upsert_ss_matches(conn, [(eid, name, season, m["date"],
                    m["home_team"], m["away_team"], m["home_score"], m["away_score"],
                    hxg, axg, oh, od, oa, o_over, o_under, *opens)])

                now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                snaps = [(eid, now, "1x2", sel, odd, int(pre))
                         for sel, odd in (("home", oh), ("draw", od), ("away", oa)) if odd]
                snaps += [(eid, now, f"ou{ou_line}", sel, odd, int(pre))
                          for sel, odd in (("over", o_over), ("under", o_under)) if odd]
                if snaps:
                    db.insert_snapshots(conn, snaps)

                parsed_close = parse_all_odds(raw_odds, m["home_team"], m["away_team"])
                parsed_open = parse_all_odds(raw_odds, m["home_team"], m["away_team"],
                                             initial=True)
                db.update_flat_markets(conn, eid, parsed_close, parsed_open)
                line_rows = db.lines_rows_from_parsed(eid, parsed_close, parsed_open)
                if line_rows:
                    db.upsert_odds_lines(conn, line_rows)

                # --- estatísticas completas (Fase 2) ---
                if m["finished"]:
                    stats_rows = parse_statistics_flat(stats_data, eid)
                    if stats_rows:
                        db.upsert_match_statistics(conn, stats_rows)

                if ratings:
                    db.upsert_ss_ratings(conn, ratings)
                    n_ratings += len(ratings)
                n_matches += 1
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