"""Odds shopping — compara casas de aposta, acha o melhor preço e cruza com o modelo.

O que faz (por jogo da Copa, mercados 1X2 e total de gols):
  1. Busca odds de dezenas de casas via The Odds API (agregador; ~10-40 casas
     por evento, regioes eu/uk/us).
  2. MELHOR PRECO por selecao + em qual casa (line shopping = valor garantido:
     voce nunca deveria aceitar preco pior pelo mesmo bilhete).
  3. CONSENSO de mercado de-vigado (mediana das casas, vig removido) — a melhor
     estimativa de probabilidade disponivel (o backtest provou que ela vence o
     nosso modelo: CLV -8,7%).
  4. Cruza com o MODELO e recomenda so nas ZONAS DE CONFIANCA da auditoria:
     totais e empate (calibrados); NUNCA recomenda azarao so porque o modelo
     gostou (vies de achatamento documentado).

Setup (uma vez, na rede limpa):
  1. Chave gratuita em https://the-odds-api.com (500 req/mes gratis).
  2. PowerShell:  $env:ODDS_API_KEY = "sua_chave"
  3. python scripts/odds_shop.py

Uso:
  python scripts/odds_shop.py                      # todos os jogos futuros da Copa
  python scripts/odds_shop.py --jogo "Spain"       # filtra por nome de time
  python scripts/odds_shop.py --from-file resp.json  # roda de um JSON salvo (offline/teste)
  python scripts/odds_shop.py --min-edge 0.05      # so recomenda edge >= 5%

A resposta crua e' salva em data/odds_shop/ (auditavel; e' o published_at da
informacao). Read-only no matches.db. Stdlib apenas — sem dependencia nova.
"""
import argparse
import json
import os
import sqlite3
import ssl
import statistics
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from src.model import predict_match
from src import market_pricer as mp
from src.predict import _canon

API_BASE = "https://api.the-odds-api.com/v4"
SPORT = "soccer_fifa_world_cup"

# Zonas de confianca do modelo (auditoria 2026-07-02):
#   - totais (over/under): calibrados, sem vies de favorito
#   - empate: validado na investigacao causal (N=2.424)
#   - vitoria de FAVORITO: modelo subestima (achatamento) — usar consenso, nao modelo
#   - vitoria de AZARAO: NUNCA recomendar pelo modelo (mercado vence 58% x 8%)
MIN_EDGE_DEFAULT = 0.03      # edge minimo vs MELHOR preco para virar recomendacao
MIN_BOOKS = 4                # menos casas que isso = consenso fraco, so informa

# Janela do BACKTEST (config.yaml backtest.min/max_edge) — o unico gatilho com
# CLV comprovado (O/U 2.5 vs preco bruto). Fallback = valores auditados.
try:
    from src.ingest import load_config
    _bt = load_config().get("backtest", {})
    _BT_MIN, _BT_MAX = float(_bt.get("min_edge", 0.02)), float(_bt.get("max_edge", 0.15))
except Exception:
    _BT_MIN, _BT_MAX = 0.02, 0.15


_quota = {"remaining": None, "used": None}   # headers da última chamada


def _fetch(url: str) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": "wc-predictor-v2"})
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
        # quota do plano gratuito (500 req/mes): sem isto o operador descobre
        # que acabou na semana da final, quando mais precisa do line shopping
        _quota["remaining"] = r.headers.get("x-requests-remaining")
        _quota["used"] = r.headers.get("x-requests-used")
        return json.loads(r.read().decode("utf-8"))


def fetch_odds(api_key: str) -> list:
    params = urllib.parse.urlencode({
        "apiKey": api_key,
        "regions": "eu,uk,us",
        "markets": "h2h,totals",
        "oddsFormat": "decimal",
    })
    data = _fetch(f"{API_BASE}/sports/{SPORT}/odds?{params}")
    # snapshot auditavel (published_at da informacao)
    out_dir = ROOT / "data" / "odds_shop"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (out_dir / f"odds_{stamp}.json").write_text(json.dumps(data), encoding="utf-8")
    return data


def devig_probs(prices: list[float]) -> list[float]:
    """Normalizacao proporcional das implicitas de UMA casa (rapido e adequado
    para consenso; o Shin fica para o pipeline principal)."""
    imp = [1.0 / p for p in prices]
    s = sum(imp)
    return [x / s for x in imp]


def _stale(bk: dict, max_stale_s: float | None) -> bool:
    """Casa com feed velho (W5, auditoria 2026-07-09): o melhor preço via max()
    incluía books com last_update congelado — preço fantasma que o operador
    não consegue executar. Sem last_update no payload, mantém (não dá pra
    julgar); max_stale_s None desliga o filtro (modo --from-file/offline,
    onde TODO o snapshot é velho por definição)."""
    if max_stale_s is None:
        return False
    lu = bk.get("last_update")
    if not lu:
        return False
    try:
        age = (datetime.now(timezone.utc)
               - datetime.fromisoformat(lu.replace("Z", "+00:00"))).total_seconds()
    except ValueError:
        return False
    return age > max_stale_s


def consensus(event: dict, market_key: str, point=None,
              max_stale_s: float | None = None) -> dict:
    """{selecao: {'best': (odd, casa), 'consensus_prob': float, 'n_books': int}}
    Consenso = mediana das probabilidades de-vigadas por casa."""
    per_book: dict = {}
    for bk in event.get("bookmakers", []):
        if _stale(bk, max_stale_s):
            continue
        for m in bk.get("markets", []):
            if m.get("key") != market_key:
                continue
            outs = m.get("outcomes", [])
            if point is not None:
                outs = [o for o in outs if o.get("point") == point]
            if len(outs) < 2:
                continue
            names = [o["name"] for o in outs]
            probs = devig_probs([o["price"] for o in outs])
            for o, p in zip(outs, probs):
                per_book.setdefault(o["name"], []).append(
                    (o["price"], bk.get("title", bk.get("key", "?")), p))
    out = {}
    for name, entries in per_book.items():
        best = max(entries, key=lambda e: e[0])
        out[name] = {
            "best": (best[0], best[1]),
            "consensus_prob": statistics.median(e[2] for e in entries),
            "n_books": len(entries),
        }
    return out


def model_probs_for(home: str, away: str):
    """Probabilidades do modelo (campo neutro) ou None se times desconhecidos."""
    conn = sqlite3.connect(f"file:{ROOT / 'data' / 'matches.db'}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=ON")
    elo = {t: e for t, e in conn.execute("SELECT team, elo FROM current_elo")}
    prow = conn.execute("SELECT param_a, param_b, param_alpha, param_rho "
                        "FROM model_parameters WHERE id=1").fetchone()
    conn.close()
    canon_elo = {_canon(t): e for t, e in elo.items()}
    eh, ea = canon_elo.get(_canon(home)), canon_elo.get(_canon(away))
    if eh is None or ea is None or not prow:
        return None
    r = predict_match(eh, ea, tuple(prow))
    ou = mp.over_under(r["grid"], 2.5)
    return {"home": r["p_win"], "draw": r["p_draw"], "away": r["p_loss"],
            "over25": ou["Over"], "under25": ou["Under"]}


def period_probs_for(home: str, away: str):
    """P(over linha) do MODELO por período (1T/2T), com a fração calibrada no
    placar de intervalo ingerido (display.ht_goal_fraction). None se times
    desconhecidos ou sem calibração — mercado de tempo SEM modelo é só preço."""
    from src.display import ht_goal_fraction
    from src.model import _score_grid

    conn = sqlite3.connect(f"file:{ROOT / 'data' / 'matches.db'}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=ON")
    elo = {t: e for t, e in conn.execute("SELECT team, elo FROM current_elo")}
    prow = conn.execute("SELECT param_a, param_b, param_alpha, param_rho "
                        "FROM model_parameters WHERE id=1").fetchone()
    calib = ht_goal_fraction(conn)
    conn.close()
    canon_elo = {_canon(t): e for t, e in elo.items()}
    eh, ea = canon_elo.get(_canon(home)), canon_elo.get(_canon(away))
    if eh is None or ea is None or not prow or calib is None:
        return None
    a, b, alpha, rho = prow
    import math

    import numpy as np
    diff = (eh - ea) / 400.0
    lam_a, lam_b = math.exp(a + b * diff), math.exp(a - b * diff)
    out = {"calib_n": calib["n"]}
    for tag, fr in (("1T", calib["frac1"]), ("2T", 1.0 - calib["frac1"])):
        g = _score_grid(lam_a * fr, lam_b * fr, alpha, rho, 12)
        k = np.arange(g.shape[0])
        tot = k.reshape(-1, 1) + k.reshape(1, -1)
        out[tag] = {ln: float(g[tot > ln].sum()) for ln in (0.5, 1.5, 2.5)}
    return out


def fetch_period_odds(api_key: str, event_id: str) -> dict | None:
    """Mercados de tempo (totals_h1/h2) — só existem no endpoint POR EVENTO da
    The Odds API (o bulk /odds não os serve). Custo de quota: mercados×regiões
    por chamada. None em erro (jogo sem esses mercados ainda, plano, etc.)."""
    params = urllib.parse.urlencode({
        "apiKey": api_key, "regions": "eu,uk,us",
        "markets": "totals_h1,totals_h2", "oddsFormat": "decimal",
    })
    try:
        data = _fetch(f"{API_BASE}/sports/{SPORT}/events/{event_id}/odds?{params}")
    except Exception as e:
        print(f"  (mercados de tempo indisponiveis: {e})")
        return None
    out_dir = ROOT / "data" / "odds_shop"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (out_dir / f"odds_h1h2_{event_id[:12]}_{stamp}.json").write_text(
        json.dumps(data), encoding="utf-8")
    return data


def _verdict(selection_kind: str, p_model, p_cons, best_odd, n_books, min_edge) -> str:
    """Regras de recomendacao pos-auditoria."""
    imp_best = 1.0 / best_odd
    if n_books < MIN_BOOKS:
        return "poucas casas — so informativo"
    # valor "de graca": melhor preco acima do consenso de-vigado
    edge_cons = p_cons - imp_best
    notes = []
    if edge_cons >= min_edge:
        notes.append(f"MELHOR PRECO > consenso ({edge_cons:+.1%}) — valor pelo proprio mercado")
    if p_model is not None:
        edge_model = p_model - imp_best
        if selection_kind in ("total", "draw") and edge_model >= min_edge:
            notes.append(f"modelo ve valor ({edge_model:+.1%}) em zona confiavel")
        elif selection_kind == "underdog" and edge_model >= min_edge:
            notes.append("modelo gosta, MAS e' azarao — zona do vies, ignorar")
    return " | ".join(notes) if notes else ""


def _started(ev: dict) -> bool:
    """Jogo ja iniciado: odds sao AO VIVO — comparar com modelo pre-jogo gera
    'valor' fantasma (ex.: empate a 126 com o favorito vencendo em campo)."""
    ct = ev.get("commence_time")
    if not ct:
        return False
    try:
        start = datetime.fromisoformat(ct.replace("Z", "+00:00"))
        return start <= datetime.now(timezone.utc)
    except ValueError:
        return False


def analyze(events: list, jogo_filter: str | None, min_edge: float,
            tempos_key: str | None = None,
            max_stale_s: float | None = None) -> None:
    for ev in events:
        home, away = ev.get("home_team", "?"), ev.get("away_team", "?")
        if jogo_filter and jogo_filter.lower() not in f"{home} {away}".lower():
            continue
        if _started(ev):
            print(f"\n{home} x {away}: JA COMECOU — odds ao vivo, fora do escopo "
                  f"(modelo e' pre-jogo). Pulado.")
            continue
        print(f"\n{'=' * 66}\n{home} x {away}  ({ev.get('commence_time', '?')})\n{'=' * 66}")
        pm = model_probs_for(home, away)
        if pm is None:
            print("  (times fora do Elo local — sem cruzamento com o modelo)")

        h2h = consensus(ev, "h2h", max_stale_s=max_stale_s)
        if h2h:
            print(f"  {'1X2':<12}{'melhor odd':>11}  {'casa':<18}{'consenso':>9}"
                  f"{'modelo':>8}  veredito")
            fav_prob = max((d["consensus_prob"] for d in h2h.values()), default=0)
            for name, d in sorted(h2h.items(), key=lambda kv: -kv[1]["consensus_prob"]):
                if name == "Draw":
                    kind, p_mod = "draw", pm and pm["draw"]
                elif d["consensus_prob"] >= fav_prob - 1e-9:
                    kind, p_mod = "favorite", pm and (pm["home"] if name == home else pm["away"])
                else:
                    kind, p_mod = "underdog", pm and (pm["home"] if name == home else pm["away"])
                v = _verdict(kind, p_mod, d["consensus_prob"], d["best"][0],
                             d["n_books"], min_edge)
                label = "Empate" if name == "Draw" else name
                print(f"  {label[:12]:<12}{d['best'][0]:>11.2f}  {d['best'][1][:18]:<18}"
                      f"{d['consensus_prob']:>9.1%}"
                      f"{(f'{p_mod:.1%}' if p_mod is not None else '—'):>8}  {v}")

        tot = consensus(ev, "totals", point=2.5, max_stale_s=max_stale_s)
        if tot:
            print(f"  {'Gols 2.5':<12}{'melhor odd':>11}  {'casa':<18}{'consenso':>9}"
                  f"{'modelo':>8}  veredito")
            for name, d in tot.items():
                p_mod = pm and (pm["over25"] if name == "Over" else pm["under25"])
                v = _verdict("total", p_mod, d["consensus_prob"], d["best"][0],
                             d["n_books"], min_edge)
                print(f"  {name:<12}{d['best'][0]:>11.2f}  {d['best'][1][:18]:<18}"
                      f"{d['consensus_prob']:>9.1%}"
                      f"{(f'{p_mod:.1%}' if p_mod is not None else '—'):>8}  {v}")
                # JANELA VALIDADA do backtest (min/max_edge do config, o único
                # gatilho com CLV comprovado: O/U 2.5 vs preço bruto) — quando o
                # edge do modelo vs MELHOR preço cai nela, imprime o comando de
                # registro no livro-caixa pronto pra colar. Aposta só existe se
                # for registrada ANTES do jogo (python -m src.bet_log).
                if p_mod is not None:
                    edge_best = p_mod - 1.0 / d["best"][0]
                    if _BT_MIN < edge_best <= _BT_MAX:
                        ko = ev.get("commence_time", "")
                        ko_args = f" --date {ko[:10]} --kickoff {ko}" if ko else ""
                        print(f"      -> JANELA VALIDADA ({edge_best:+.1%}): "
                              f"python -m src.bet_log add \"{home}\" \"{away}\" ou25 "
                              f"{name.lower()} {d['best'][0]} --casa \"{d['best'][1]}\" "
                              f"--edge {edge_best:.4f} --prob {p_mod:.4f}{ko_args}")

        if tempos_key:
            _analyze_periods(ev, home, away, tempos_key, max_stale_s=max_stale_s)


_PERIOD_MARKETS = (("totals_h1", "1T"), ("totals_h2", "2T"))
_PERIOD_LINES = (0.5, 1.5, 2.5)


def _analyze_periods(ev: dict, home: str, away: str, api_key: str,
                     max_stale_s: float | None = None) -> None:
    """Odds de 1T/2T (melhor preço + consenso) cruzadas com o modelo calibrado.
    SEM CLV validado — o marcador é 'PICK >=60%' (regra da retro-análise das
    oitavas: picks com prob >=60% acertaram 78%), nunca 'JANELA VALIDADA'."""
    data = fetch_period_odds(api_key, ev.get("id", ""))
    if not data:
        return
    pp = period_probs_for(home, away)
    for mkey, tag in _PERIOD_MARKETS:
        blocks = []
        for ln in _PERIOD_LINES:
            c = consensus(data, mkey, point=ln, max_stale_s=max_stale_s)
            if c:
                blocks.append((ln, c))
        if not blocks:
            continue
        print(f"  {'Gols ' + tag:<12}{'melhor odd':>11}  {'casa':<18}{'consenso':>9}"
              f"{'modelo':>8}  [SEM CLV validado]")
        for ln, c in blocks:
            for name, d in c.items():
                p_over = pp and pp[tag].get(ln)
                p_mod = None if p_over is None else \
                    (p_over if name == "Over" else 1.0 - p_over)
                marker = ""
                if p_mod is not None:
                    edge_best = p_mod - 1.0 / d["best"][0]
                    if p_mod >= 0.60 and edge_best > 0:
                        mk_code = f"ou{str(ln).replace('.', '')}_{tag.lower()}"
                        ko = ev.get("commence_time", "")
                        ko_args = f" --kickoff {ko}" if ko else ""
                        marker = (f"PICK >=60% ({edge_best:+.1%}) — registrar: "
                                  f"python -m src.bet_log add \"{home}\" \"{away}\" "
                                  f"{mk_code} {name.lower()} {d['best'][0]} "
                                  f"--casa \"{d['best'][1]}\"{ko_args}")
                print(f"  {name + ' ' + str(ln):<12}{d['best'][0]:>11.2f}  "
                      f"{d['best'][1][:18]:<18}{d['consensus_prob']:>9.1%}"
                      f"{(f'{p_mod:.1%}' if p_mod is not None else '—'):>8}  {marker}")


def _footer(min_edge: float) -> None:
    print("\nRegras aplicadas: recomendacao exige edge >= {:.0%} vs MELHOR preco, em".format(min_edge))
    print("zona confiavel (totais/empate) ou valor vs consenso do proprio mercado.")
    print("Vitoria de azarao pelo modelo NUNCA e' recomendada (vies de achatamento).")
    print("'JANELA VALIDADA' = gatilho do backtest (unico com CLV comprovado);")
    print("mercados de TEMPO sao [SEM CLV] — 'PICK >=60%' segue a regra da")
    print("retro-analise (prob >=60% acertou 78%), aposte menor ou so registre.")
    print("Feche tudo com `python -m src.bet_log settle HOME AWAY H A --ht H-A`.")
    if _quota["remaining"] is not None:
        print(f"Quota The Odds API: {_quota['remaining']} requests restantes "
              f"({_quota['used']} usadas no ciclo).")


def main() -> int:
    ap = argparse.ArgumentParser(description="Line shopping multi-casas + cruzamento com o modelo")
    ap.add_argument("--jogo", help="filtra por nome de time (substring)")
    ap.add_argument("--min-edge", type=float, default=MIN_EDGE_DEFAULT)
    ap.add_argument("--from-file", help="JSON salvo da API (offline/teste)")
    ap.add_argument("--tempos", action="store_true",
                    help="inclui odds de 1o/2o tempo (totals_h1/h2 — 1 chamada "
                         "de API POR JOGO; use com --jogo pra poupar quota)")
    ap.add_argument("--max-stale-min", type=float, default=15.0,
                    help="descarta casa cujo last_update tem mais que N minutos "
                         "(W5: feed congelado vira melhor preco fantasma). "
                         "0 desliga. So vale no modo online; --from-file nunca "
                         "filtra (snapshot e' velho por definicao). Default: 15")
    args = ap.parse_args()

    max_stale_s = None
    if args.from_file:
        events = json.loads(Path(args.from_file).read_text(encoding="utf-8"))
    else:
        if args.max_stale_min > 0:
            max_stale_s = args.max_stale_min * 60.0
        key = os.environ.get("ODDS_API_KEY")
        if not key:
            print("ODDS_API_KEY nao definida.\n"
                  "  1. Chave gratis: https://the-odds-api.com (500 req/mes)\n"
                  "  2. PowerShell:  $env:ODDS_API_KEY = \"sua_chave\"\n"
                  "  3. Rode de novo (na rede limpa — a Volvo bloqueia).")
            return 2
        try:
            events = fetch_odds(key)
        except Exception as e:
            print(f"falha na API de odds: {e}")
            return 1

    if not events:
        print("nenhum jogo com odds no momento.")
        return 0
    tempos_key = os.environ.get("ODDS_API_KEY") if args.tempos else None
    if args.tempos and not tempos_key:
        print("[--tempos ignorado: ODDS_API_KEY nao definida — mercados de "
              "tempo exigem o endpoint por evento]")
    analyze(events, args.jogo, args.min_edge, tempos_key=tempos_key,
            max_stale_s=max_stale_s)
    _footer(args.min_edge)
    return 0


if __name__ == "__main__":
    sys.exit(main())
