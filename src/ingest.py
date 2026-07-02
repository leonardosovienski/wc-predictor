import io
import sys
import time
import urllib.request
from pathlib import Path

import pandas as pd
import yaml

from . import db
from .net import retry
from .obs import get_logger, setup_logging
from predictor_core.obs import emit_event

log = get_logger()
_DOMAIN = "wc"

ROOT = Path(__file__).resolve().parent.parent


def load_config() -> dict:
    with open(ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


@retry(attempts=3, base_delay=2.0)
def _download(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read().decode("utf-8")


def fetch_csv(cfg: dict) -> pd.DataFrame:
    try:
        raw = _download(cfg["source"]["url"])
        df = pd.read_csv(io.StringIO(raw))
        log.info("fonte remota: %d linhas", len(df))
    except Exception as e:
        fallback = ROOT / cfg["source"]["local_fallback"]
        log.warning("fonte remota indisponível (%s); usando fallback %s", e, fallback)
        df = pd.read_csv(fallback)
    return df


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    df = df.dropna(subset=["date", "home_team", "away_team"])
    df["neutral"] = df["neutral"].astype(str).str.upper().isin(["TRUE", "1"]).astype(int)
    for col in ("home_score", "away_score"):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    df = df.drop_duplicates(subset=["date", "home_team", "away_team"], keep="last")
    return df[["date", "home_team", "away_team", "home_score", "away_score",
               "tournament", "city", "country", "neutral"]]


def run() -> None:
    cfg = load_config()
    setup_logging(ROOT / "data")
    t0 = time.monotonic()
    df = normalize(fetch_csv(cfg))
    conn = db.connect(str(ROOT / cfg["database"]))
    rows = [
        (r.date, r.home_team, r.away_team,
         None if pd.isna(r.home_score) else int(r.home_score),
         None if pd.isna(r.away_score) else int(r.away_score),
         r.tournament, r.city, r.country, int(r.neutral))
        for r in df.itertuples()
    ]
    db.upsert_matches(conn, rows)
    played = conn.execute("SELECT COUNT(*) FROM matches WHERE home_score IS NOT NULL").fetchone()[0]
    fixtures = conn.execute("SELECT COUNT(*) FROM matches WHERE home_score IS NULL").fetchone()[0]
    log.info("banco: %d partidas jogadas, %d fixtures futuros", played, fixtures)
    emit_event(_DOMAIN, "ingest_done",
               metrics={"records": float(len(rows)), "played": float(played),
                        "fixtures": float(fixtures),
                        "duration_sec": round(time.monotonic() - t0, 2)},
               metadata={"source": "results_csv"})


if __name__ == "__main__":
    sys.exit(run())
