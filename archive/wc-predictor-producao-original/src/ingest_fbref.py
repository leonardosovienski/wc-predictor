"""Coletor de stats agregadas de jogador por competição, via FBref.

FBref serve páginas estáticas — sem anti-bot, sem browser headless. Lê com
requests + pandas. Detalhe importante: o FBref esconde tabelas secundárias
dentro de comentários HTML, então é preciso "descomentar" antes de parsear.

A coleta roda na máquina do usuário (precisa alcançar fbref.com). As competições
ficam em config.yaml (player_stats.competitions), nunca hardcoded aqui.
"""
import re
import sys
import time
import urllib.request
from io import StringIO
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup, Comment

from . import db
from .ingest import ROOT, load_config

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# nome canônico -> candidatos de coluna no FBref (case-insensitive, 1º que casar)
COLUMN_MAP = {
    "player": ["player"],
    "team": ["squad", "team", "nation"],
    "position": ["pos"],
    "games": ["mp", "matches played"],
    "minutes": ["min", "minutes"],
    "goals": ["gls", "goals"],
    "assists": ["ast", "assists"],
    "xg": ["xg"],
    "xag": ["xag", "xa"],
}


def fetch_html(url: str, cache_dir: Path, rate_limit: float) -> str:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / (re.sub(r"\W+", "_", url).strip("_") + ".html")
    if cached.exists():
        return cached.read_text(encoding="utf-8")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode("utf-8", errors="replace")
    cached.write_text(html, encoding="utf-8")
    time.sleep(rate_limit)  # FBref pede gentileza: ~1 req a cada poucos segundos
    return html


def _uncomment_tables(html: str) -> BeautifulSoup:
    soup = BeautifulSoup(html, "lxml")
    for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
        if "<table" in c:
            soup.append(BeautifulSoup(c, "lxml"))
    return soup


def _flatten(cols) -> list:
    out = []
    for c in cols:
        out.append(str(c[-1]) if isinstance(c, tuple) else str(c))
    return out


def _resolve(columns: list) -> dict:
    lower = {c.lower().strip(): c for c in columns}
    found = {}
    for canon, candidates in COLUMN_MAP.items():
        for cand in candidates:
            if cand in lower:
                found[canon] = lower[cand]
                break
    return found


def parse_player_stats(html: str, competition: str, season: str) -> list:
    soup = _uncomment_tables(html)
    table = soup.find("table", id=re.compile(r"stats_standard"))
    if table is None:
        raise ValueError(f"tabela stats_standard ausente em '{competition}'")

    df = pd.read_html(StringIO(str(table)))[0]
    df.columns = _flatten(df.columns)
    cols = _resolve(df.columns)
    if "player" not in cols:
        raise ValueError(f"coluna de jogador não encontrada em '{competition}'")

    # FBref repete a linha de cabeçalho no meio da tabela; descarta
    df = df[df[cols["player"]].astype(str).str.lower() != "player"]
    df = df[df[cols["player"]].notna()]

    def num(series):
        return pd.to_numeric(series.astype(str).str.replace(",", ""), errors="coerce")

    rows = []
    for _, r in df.iterrows():
        def g(key, cast):
            if key not in cols:
                return None
            v = r[cols[key]]
            if cast is int:
                v = num(pd.Series([v])).iloc[0]
                return None if pd.isna(v) else int(v)
            if cast is float:
                v = num(pd.Series([v])).iloc[0]
                return None if pd.isna(v) else float(v)
            return None if pd.isna(v) else str(v)

        player = g("player", str)
        team = g("team", str)
        if not player or not team:
            continue
        rows.append((player, team, competition, season, g("position", str),
                     g("minutes", int), g("games", int), g("goals", int),
                     g("assists", int), g("xg", float), g("xag", float)))
    return rows


def run() -> None:
    cfg = load_config()
    pcfg = cfg.get("player_stats")
    if not pcfg or not pcfg.get("competitions"):
        sys.exit("nada em player_stats.competitions no config.yaml")

    cache = ROOT / pcfg.get("cache_dir", "data/fbref_cache")
    rate = float(pcfg.get("rate_limit_seconds", 4))
    conn = db.connect(str(ROOT / cfg["database"]))

    total = 0
    for comp in pcfg["competitions"]:
        try:
            html = fetch_html(comp["url"], cache, rate)
            rows = parse_player_stats(html, comp["name"], str(comp["season"]))
            db.upsert_players(conn, rows)
            total += len(rows)
            print(f"  {comp['name']}: {len(rows)} jogadores")
        except Exception as e:
            print(f"  [falha] {comp['name']}: {e}")
    print(f"player_comp_stats: {total} linhas processadas")


if __name__ == "__main__":
    sys.exit(run())
