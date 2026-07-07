import sqlite3
from pathlib import Path

SCHEMA = """

CREATE TABLE IF NOT EXISTS match_statistics (
    event_id INTEGER NOT NULL,
    team TEXT NOT NULL,
    period TEXT NOT NULL,
    stat_name TEXT NOT NULL,
    value REAL,
    PRIMARY KEY (event_id, team, period, stat_name),
    FOREIGN KEY (event_id) REFERENCES sofascore_matches(event_id)
);


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

-- Mercados de LINHA (dois lados + linha variável): Over/Under (todas as linhas) e
-- Handicap Asiático na MESMA tabela — porque são a mesma forma (linha + 2 lados).
-- Evita dezenas de colunas hardcoded por linha e é à prova de linha nova; a Fase 3
-- (cartões/escanteios) entra aqui sem mudar schema (market='cards'|'corners').
--   ou: odd_a=Over,  odd_b=Under  |  ah: odd_a=home (mando), odd_b=away
--   line: 2.5, -0.75, ...  | *_open = abertura (write-once via COALESCE)
CREATE TABLE IF NOT EXISTS odds_lines (
    event_id   INTEGER NOT NULL,
    market     TEXT    NOT NULL,   -- 'ou' | 'ah' | (futuro: 'cards','corners')
    line       REAL    NOT NULL,
    odd_a      REAL, odd_b REAL,
    odd_a_open REAL, odd_b_open REAL,
    PRIMARY KEY (event_id, market, line)
);
CREATE INDEX IF NOT EXISTS idx_lines_event ON odds_lines(event_id, market);

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


# Mercados de seleção FIXA (sem linha): colunas flat por velocidade de backtest.
# DC/DNB/BTTS têm seleções estáveis, então flat faz sentido (1 linha por jogo,
# odds inline). Mercados de LINHA (OU/AH) vão para odds_lines, não aqui.
_FLAT_MARKET_COLS = (
    "odds_dc_1x", "odds_dc_x2", "odds_dc_12",
    "odds_dnb_home", "odds_dnb_away",
    "odds_btts_yes", "odds_btts_no",
    "odds_dc_1x_open", "odds_dc_x2_open", "odds_dc_12_open",
    "odds_dnb_home_open", "odds_dnb_away_open",
    "odds_btts_yes_open", "odds_btts_no_open",
)


def _migrate(conn):
    """Adiciona colunas novas a bancos pré-existentes (idempotente)."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(sofascore_matches)")}
    new = ("odds_over", "odds_under",
           # abertura = primeira odd observada PRÉ-APITO (write-once via COALESCE).
           # NULL na base histórica coletada pós-jogo: abertura desconhecida ≠ close.
           "odds_home_open", "odds_draw_open", "odds_away_open",
           "odds_over_open", "odds_under_open",
           *_FLAT_MARKET_COLS)
    for col in new:
        if col not in cols:
            conn.execute(f"ALTER TABLE sofascore_matches ADD COLUMN {col} REAL")
    # placar do 1o tempo (period1 do Sofascore) — o dado sempre esteve no cache
    # de events, só nunca foi ingerido (auditoria 2026-07-07). Destrava aferição
    # dos mercados de 1o/2o tempo e a calibração da hipótese de taxa constante.
    for col in ("home_score_ht", "away_score_ht"):
        if col not in cols:
            conn.execute(f"ALTER TABLE sofascore_matches ADD COLUMN {col} INTEGER")
    # Backfill não-destrutivo: a linha principal de OU (2.5) já gravada nas colunas
    # legadas vira a forma canônica em odds_lines. INSERT OR IGNORE preserva o que
    # já existir lá (re-rodar a migração é inócuo).
    conn.execute(
        "INSERT OR IGNORE INTO odds_lines "
        "(event_id, market, line, odd_a, odd_b, odd_a_open, odd_b_open) "
        "SELECT event_id, 'ou', 2.5, odds_over, odds_under, odds_over_open, odds_under_open "
        "FROM sofascore_matches WHERE odds_over IS NOT NULL")
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
    -- nome de time resolve de placeholder de bracket ('W83') pro time real
    -- conforme o Sofascore fecha as fases anteriores; sem isso a 2ª coleta
    -- do MESMO event_id mantinha o placeholder da 1ª pra sempre (bug real:
    -- fazia parecer que o Sofascore nunca resolvia o nome, quando na
    -- verdade era o upsert descartando o nome novo em silêncio).
    competition=excluded.competition, season=excluded.season, date=excluded.date,
    home_team=excluded.home_team, away_team=excluded.away_team,
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


def update_ht_scores(conn, event_id, home_ht, away_ht):
    """Placar do 1o tempo — UPDATE separado do upsert principal de propósito
    (mesmo padrão de update_flat_markets): estender a tupla posicional de 20
    campos do SS_MATCH quebraria todo chamador/teste existente. None é no-op:
    jogo não terminado ou payload sem period1 não apaga dado já gravado."""
    if home_ht is None or away_ht is None:
        return
    conn.execute("UPDATE sofascore_matches SET home_score_ht=?, away_score_ht=? "
                 "WHERE event_id=?", (int(home_ht), int(away_ht), event_id))
    conn.commit()


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


# --- mercados estendidos (Fase 1: BTTS, DC, DNB, OU multi-linha, AH) ---

_UPDATE_FLAT = """
UPDATE sofascore_matches SET
    odds_dc_1x=?, odds_dc_x2=?, odds_dc_12=?,
    odds_dnb_home=?, odds_dnb_away=?, odds_btts_yes=?, odds_btts_no=?,
    odds_dc_1x_open       = COALESCE(odds_dc_1x_open, ?),
    odds_dc_x2_open       = COALESCE(odds_dc_x2_open, ?),
    odds_dc_12_open       = COALESCE(odds_dc_12_open, ?),
    odds_dnb_home_open    = COALESCE(odds_dnb_home_open, ?),
    odds_dnb_away_open    = COALESCE(odds_dnb_away_open, ?),
    odds_btts_yes_open    = COALESCE(odds_btts_yes_open, ?),
    odds_btts_no_open     = COALESCE(odds_btts_no_open, ?)
WHERE event_id=?
"""


def _flat_vals(parsed: dict):
    dc = parsed.get("dc", {}) or {}
    dnb = parsed.get("dnb", {}) or {}
    btts = parsed.get("btts", {}) or {}
    return [dc.get("1X"), dc.get("X2"), dc.get("12"),
            dnb.get("1"), dnb.get("2"), btts.get("Yes"), btts.get("No")]


def update_flat_markets(conn, event_id, parsed_close: dict, parsed_open: dict):
    """Atualiza as colunas flat (DC/DNB/BTTS) de um jogo já inserido.
    odds_* = FECHAMENTO (parsed_close, última leitura vence); *_open = ABERTURA
    (parsed_open, vinda do initialFractionalValue) — write-once via COALESCE.
    A abertura agora é o preço de abertura da casa de apostas (inline no JSON),
    não 'a primeira foto do nosso cron' — destrava a população 'open' real."""
    close = _flat_vals(parsed_close)
    opens = _flat_vals(parsed_open or {})
    conn.execute(_UPDATE_FLAT, (*close, *opens, event_id))
    conn.commit()


def lines_rows_from_parsed(event_id, parsed_close: dict, parsed_open: dict):
    """Linhas de odds_lines a partir dos dicts de parse_all_odds (fechamento e
    abertura). PURO (sem DB). ou: a=Over,b=Under; ah: a=home,b=away;
    cards/corners: a=Over,b=Under (mesma estrutura do ou).
    A abertura é casada pela MESMA linha; ausente vira None."""
    op = parsed_open or {}
    rows = []
    # OU (gols)
    for line, d in (parsed_close.get("ou") or {}).items():
        od = (op.get("ou") or {}).get(line, {})
        rows.append((event_id, "ou", float(line), d.get("Over"), d.get("Under"),
                     od.get("Over"), od.get("Under")))
    # AH
    for line, d in (parsed_close.get("ah") or {}).items():
        od = (op.get("ah") or {}).get(line, {})
        rows.append((event_id, "ah", float(line), d.get("home"), d.get("away"),
                     od.get("home"), od.get("away")))
    # ===== NOVOS: CARDS =====
    for line, d in (parsed_close.get("cards") or {}).items():
        od = (op.get("cards") or {}).get(line, {})
        rows.append((event_id, "cards", float(line), d.get("Over"), d.get("Under"),
                     od.get("Over"), od.get("Under")))
    # ===== NOVOS: CORNERS =====
    for line, d in (parsed_close.get("corners") or {}).items():
        od = (op.get("corners") or {}).get(line, {})
        rows.append((event_id, "corners", float(line), d.get("Over"), d.get("Under"),
                     od.get("Over"), od.get("Under")))
    return rows


def upsert_odds_lines(conn, rows):
    """Grava mercados de linha (OU/AH). Fechamento sobrescreve; abertura é
    write-once (COALESCE). PK (event_id, market, line) torna re-runs idempotentes."""
    cur = conn.executemany(
        "INSERT INTO odds_lines "
        "(event_id, market, line, odd_a, odd_b, odd_a_open, odd_b_open) "
        "VALUES (?,?,?,?,?,?,?) "
        "ON CONFLICT(event_id, market, line) DO UPDATE SET "
        "  odd_a=excluded.odd_a, odd_b=excluded.odd_b, "
        "  odd_a_open=COALESCE(odds_lines.odd_a_open, excluded.odd_a_open), "
        "  odd_b_open=COALESCE(odds_lines.odd_b_open, excluded.odd_b_open)",
        rows)
    conn.commit()
    return cur.rowcount

def upsert_match_statistics(conn, rows):
    """Insere ou substitui estatísticas do evento.
    rows: lista de dicts com {event_id, team, period, stat_name, value}
    """
    conn.executemany("""
        INSERT OR REPLACE INTO match_statistics (event_id, team, period, stat_name, value)
        VALUES (:event_id, :team, :period, :stat_name, :value)
    """, rows)
    conn.commit()


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
