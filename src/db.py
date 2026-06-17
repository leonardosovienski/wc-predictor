import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    date        TEXT NOT NULL,
    home_team   TEXT NOT NULL,
    away_team   TEXT NOT NULL,
    home_score  INTEGER,
    away_score  INTEGER,
    tournament  TEXT,
    city        TEXT,
    country     TEXT,
    neutral     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (date, home_team, away_team)
);
CREATE INDEX IF NOT EXISTS idx_matches_date ON matches(date);

CREATE TABLE IF NOT EXISTS player_comp_stats (
    player      TEXT NOT NULL,
    team        TEXT NOT NULL,
    competition TEXT NOT NULL,
    season      TEXT NOT NULL,
    position    TEXT,
    minutes     INTEGER,
    games       INTEGER,
    goals       INTEGER,
    assists     INTEGER,
    xg          REAL,
    xag         REAL,
    PRIMARY KEY (player, team, competition, season)
);
CREATE INDEX IF NOT EXISTS idx_pcs_team ON player_comp_stats(team, competition, season);

CREATE TABLE IF NOT EXISTS sofascore_matches (
    event_id    INTEGER PRIMARY KEY,
    competition TEXT, season TEXT, date TEXT,
    home_team   TEXT, away_team TEXT,
    home_score  INTEGER, away_score INTEGER,
    home_xg     REAL, away_xg REAL,
    odds_home   REAL, odds_draw REAL, odds_away REAL,
    odds_over   REAL, odds_under REAL
);
CREATE TABLE IF NOT EXISTS sofascore_player_ratings (
    event_id    INTEGER, player TEXT, team TEXT,
    rating      REAL, minutes INTEGER,
    PRIMARY KEY (event_id, player)
);

-- Série temporal de odds (append-only). Cada coleta grava a foto do momento;
-- abertura/fechamento são derivados (primeira/última foto pré-apito). As colunas
-- flat *_open em sofascore_matches existem por velocidade de backtest; esta
-- tabela é a fonte pra plotar movimento de linha e validar contra sharp books.
CREATE TABLE IF NOT EXISTS odds_snapshots (
    event_id    INTEGER NOT NULL,
    captured_at TEXT    NOT NULL,   -- UTC ISO-8601 do momento da coleta
    market      TEXT    NOT NULL,   -- '1x2' | 'ou2.5'
    selection   TEXT    NOT NULL,   -- 'home'|'draw'|'away'|'over'|'under'
    odd         REAL    NOT NULL,
    pre_match   INTEGER NOT NULL DEFAULT 1,  -- 0 = coletado pós-jogo (linha congelada)
    PRIMARY KEY (event_id, market, selection, captured_at)
);
CREATE INDEX IF NOT EXISTS idx_snap_event ON odds_snapshots(event_id, market);

CREATE TABLE IF NOT EXISTS current_elo (
    team TEXT PRIMARY KEY,
    elo  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS model_parameters (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    param_a     REAL, param_b REAL, param_alpha REAL, param_rho REAL,
    n_matches   INTEGER, config_hash TEXT, computed_at TEXT
);
"""

UPSERT = """
INSERT INTO matches (date, home_team, away_team, home_score, away_score,
                     tournament, city, country, neutral)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(date, home_team, away_team) DO UPDATE SET
    home_score = excluded.home_score,
    away_score = excluded.away_score,
    tournament = excluded.tournament,
    city       = excluded.city,
    country    = excluded.country,
    neutral    = excluded.neutral;
"""

UPSERT_PLAYER = """
INSERT INTO player_comp_stats (player, team, competition, season, position,
                               minutes, games, goals, assists, xg, xag)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(player, team, competition, season) DO UPDATE SET
    position = excluded.position,
    minutes  = excluded.minutes,
    games    = excluded.games,
    goals    = excluded.goals,
    assists  = excluded.assists,
    xg       = excluded.xg,
    xag      = excluded.xag;
"""


def connect(db_path: str, read_only: bool = False) -> sqlite3.Connection:
    """Abre o banco. read_only=True monta em mode=ro (SQLite URI) + query_only —
    FISICAMENTE incapaz de escrever (Shadow Deployment v2: lê a produção viva do
    cron da Copa sem a menor chance de corromper o arquivo original). Nesse modo
    não cria schema nem migra (ambos escreveriam)."""
    if read_only:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30)
        conn.execute("PRAGMA query_only=ON")     # trava extra: rejeita qualquer escrita
        conn.execute("PRAGMA busy_timeout=30000")
        return conn
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    # WAL: leitor (CLI, simulador) e escritor (ingest, cron) concorrem sem
    # "database is locked". busy_timeout faz o escritor esperar em vez de abortar.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn):
    """Adiciona colunas novas a bancos pré-existentes (idempotente)."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(sofascore_matches)")}
    new = ("odds_over", "odds_under",
           # abertura = primeira odd observada PRÉ-APITO (write-once via COALESCE).
           # NULL na base histórica coletada pós-jogo: abertura desconhecida ≠ close.
           "odds_home_open", "odds_draw_open", "odds_away_open",
           "odds_over_open", "odds_under_open")
    for col in new:
        if col not in cols:
            conn.execute(f"ALTER TABLE sofascore_matches ADD COLUMN {col} REAL")
    conn.commit()


def upsert_matches(conn: sqlite3.Connection, rows) -> int:
    cur = conn.executemany(UPSERT, rows)
    conn.commit()
    return cur.rowcount


def upsert_players(conn: sqlite3.Connection, rows) -> int:
    cur = conn.executemany(UPSERT_PLAYER, rows)
    conn.commit()
    return cur.rowcount


SS_MATCH = """
INSERT INTO sofascore_matches (event_id, competition, season, date, home_team,
    away_team, home_score, away_score, home_xg, away_xg, odds_home, odds_draw, odds_away,
    odds_over, odds_under,
    odds_home_open, odds_draw_open, odds_away_open, odds_over_open, odds_under_open)
VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(event_id) DO UPDATE SET
    home_score=excluded.home_score, away_score=excluded.away_score,
    home_xg=excluded.home_xg, away_xg=excluded.away_xg,
    -- odds_* = FECHAMENTO: a última leitura sempre vence
    odds_home=excluded.odds_home, odds_draw=excluded.odds_draw, odds_away=excluded.odds_away,
    odds_over=excluded.odds_over, odds_under=excluded.odds_under,
    -- *_open = ABERTURA: write-once — coleta posterior não destrói a primeira foto
    odds_home_open  = COALESCE(sofascore_matches.odds_home_open,  excluded.odds_home_open),
    odds_draw_open  = COALESCE(sofascore_matches.odds_draw_open,  excluded.odds_draw_open),
    odds_away_open  = COALESCE(sofascore_matches.odds_away_open,  excluded.odds_away_open),
    odds_over_open  = COALESCE(sofascore_matches.odds_over_open,  excluded.odds_over_open),
    odds_under_open = COALESCE(sofascore_matches.odds_under_open, excluded.odds_under_open);
"""

SS_RATING = """
INSERT INTO sofascore_player_ratings (event_id, player, team, rating, minutes)
VALUES (?,?,?,?,?)
ON CONFLICT(event_id, player) DO UPDATE SET
    rating=excluded.rating, minutes=excluded.minutes, team=excluded.team;
"""


def upsert_ss_matches(conn, rows):
    cur = conn.executemany(SS_MATCH, rows); conn.commit(); return cur.rowcount


def upsert_ss_ratings(conn, rows):
    cur = conn.executemany(SS_RATING, rows); conn.commit(); return cur.rowcount


def insert_snapshots(conn, rows):
    """Append-only; PK (event,market,selection,captured_at) torna re-runs inócuos."""
    cur = conn.executemany(
        "INSERT OR IGNORE INTO odds_snapshots "
        "(event_id, captured_at, market, selection, odd, pre_match) "
        "VALUES (?,?,?,?,?,?)", rows)
    conn.commit()
    return cur.rowcount


# --- cache de modelo (Parte 2: serving instantâneo) ---

def save_elo(conn, items):
    conn.execute("DELETE FROM current_elo")
    conn.executemany("INSERT INTO current_elo (team, elo) VALUES (?, ?)", items)
    conn.commit()


def load_elo(conn):
    try:
        return {t: e for t, e in conn.execute("SELECT team, elo FROM current_elo")}
    except sqlite3.OperationalError:
        return {}


def save_params(conn, a, b, alpha, rho, n_matches, config_hash, computed_at):
    conn.execute(
        "INSERT OR REPLACE INTO model_parameters "
        "(id, param_a, param_b, param_alpha, param_rho, n_matches, config_hash, computed_at) "
        "VALUES (1, ?, ?, ?, ?, ?, ?, ?)",
        (a, b, alpha, rho, n_matches, config_hash, computed_at))
    conn.commit()


def load_params(conn):
    try:
        return conn.execute(
            "SELECT param_a, param_b, param_alpha, param_rho, n_matches, config_hash, computed_at "
            "FROM model_parameters WHERE id = 1").fetchone()
    except sqlite3.OperationalError:
        return None
