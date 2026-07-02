"""
Feature builder: medias moveis de estatisticas por time.
Forward-only: so usa jogos anteriores a data da partida.
Auditoria 2026-07-02 (P4): a media agora filtra match_statistics.team pelo LADO
que o time ocupou em cada jogo ('home'/'away') — antes misturava as estatisticas
do time com as do adversario. (P12): conexao somente-leitura (mode=ro).
"""
import sqlite3

DEFAULT_FEATURES = [
    'Expected goals',
    'Big chances',
    'Total shots',
    'Shots on target',
    'Shots inside box',
    'Touches in penalty area',
    'Ball possession'
]


def _connect_ro(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=ON")
    conn.row_factory = sqlite3.Row
    return conn


def build_features(db_path: str, event_id: int, window: int = 10) -> dict:
    """
    Para um evento, calcula as features dos dois times.
    Retorna dict com chaves 'home_Expected goals', 'away_Expected goals', etc.
    Inclui 'delta_xg' = home_Expected goals - away_Expected goals.
    Times sem historico retornam dict vazio para aquele time.
    """
    conn = _connect_ro(db_path)

    row = conn.execute(
        "SELECT date, home_team, away_team FROM sofascore_matches WHERE event_id = ?",
        (event_id,)
    ).fetchone()

    if not row:
        conn.close()
        return {}

    match_date = row['date']
    home_team = row['home_team']
    away_team = row['away_team']

    home_feats = _team_features(conn, home_team, match_date, window)
    away_feats = _team_features(conn, away_team, match_date, window)
    conn.close()

    features = {}
    for stat, val in home_feats.items():
        features[f'home_{stat}'] = val
    for stat, val in away_feats.items():
        features[f'away_{stat}'] = val

    home_xg = home_feats.get('Expected goals', 0.0)
    away_xg = away_feats.get('Expected goals', 0.0)
    features['delta_xg'] = home_xg - away_xg

    return features


def _team_features(conn: sqlite3.Connection, team: str, match_date: str,
                   window: int) -> dict:
    """
    Media de cada estatistica nos ultimos `window` jogos do time.
    So considera jogos com data < match_date, e SO as linhas de
    match_statistics cujo team ('home'/'away') corresponde ao lado que o
    time ocupou naquele jogo (fix da auditoria P4 — antes a media misturava
    time e adversario).
    """
    event_rows = conn.execute("""
        SELECT event_id,
               CASE WHEN home_team = ? THEN 'home' ELSE 'away' END as side
        FROM sofascore_matches
        WHERE (home_team = ? OR away_team = ?)
          AND date < ?
          AND home_score IS NOT NULL
        ORDER BY date DESC
        LIMIT ?
    """, (team, team, team, match_date, window)).fetchall()

    if not event_rows:
        return {}

    side_by_event = {r['event_id']: r['side'] for r in event_rows}
    event_ids = list(side_by_event)
    placeholders = ','.join('?' * len(event_ids))
    stat_placeholders = ','.join('?' * len(DEFAULT_FEATURES))

    rows = conn.execute(f"""
        SELECT ms.event_id, ms.team, ms.stat_name, ms.value
        FROM match_statistics ms
        WHERE ms.event_id IN ({placeholders})
          AND ms.stat_name IN ({stat_placeholders})
          AND ms.period = 'ALL'
          AND ms.value IS NOT NULL
    """, event_ids + DEFAULT_FEATURES).fetchall()

    sums: dict = {}
    counts: dict = {}
    for r in rows:
        if r['team'] != side_by_event[r['event_id']]:
            continue                      # linha do adversario: fora da media
        sums[r['stat_name']] = sums.get(r['stat_name'], 0.0) + r['value']
        counts[r['stat_name']] = counts.get(r['stat_name'], 0) + 1

    return {stat: sums[stat] / counts[stat] for stat in sums}
