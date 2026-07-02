import pytest
import sqlite3
from src.feature_builder import build_features


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "test.db"
    conn = sqlite3.connect(str(p))
    conn.executescript("""
        CREATE TABLE sofascore_matches (
            event_id INTEGER PRIMARY KEY,
            date TEXT,
            home_team TEXT,
            away_team TEXT,
            home_score INTEGER,
            away_score INTEGER
        );
        CREATE TABLE match_statistics (
            event_id INTEGER,
            team TEXT,
            period TEXT,
            stat_name TEXT,
            value REAL,
            PRIMARY KEY (event_id, team, period, stat_name)
        );
        INSERT INTO sofascore_matches VALUES
            (1, '2026-06-10', 'Brazil', 'Argentina', 2, 0);
        INSERT INTO sofascore_matches VALUES
            (2, '2026-06-15', 'Brazil', 'Uruguay', 3, 1);
        INSERT INTO sofascore_matches VALUES
            (3, '2026-06-20', 'Brazil', 'Colombia', 1, 0);
        INSERT INTO match_statistics VALUES
            (1, 'home', 'ALL', 'Expected goals', 2.0);
        INSERT INTO match_statistics VALUES
            (2, 'home', 'ALL', 'Expected goals', 2.5);
        INSERT INTO match_statistics VALUES
            (3, 'home', 'ALL', 'Expected goals', 1.8);
        INSERT INTO match_statistics VALUES
            (1, 'home', 'ALL', 'Ball possession', 55.0);
        INSERT INTO match_statistics VALUES
            (2, 'home', 'ALL', 'Ball possession', 58.0);
    """)
    conn.commit()
    conn.close()
    return str(p)


def test_build_features(db_path):
    feats = build_features(db_path, event_id=3, window=2)
    assert abs(feats['home_Expected goals'] - 2.25) < 0.01
    assert abs(feats['home_Ball possession'] - 56.5) < 0.01
    assert 'delta_xg' in feats


def test_build_features_empty(db_path):
    feats = build_features(db_path, event_id=1, window=2)
    # Jogo 1 e o primeiro, sem historico anterior
    assert feats.get('home_Expected goals') is None or feats.get('home_Expected goals') == 0.0
    assert 'delta_xg' in feats


def test_build_features_filtra_pelo_lado_do_time(db_path):
    """Auditoria P4: a media do time NAO pode incluir as linhas do adversario.
    Injetamos valores absurdos de 'away' nos jogos 1 e 2 (Brazil jogou como
    home): se a media mudar, o filtro de lado regrediu."""
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        INSERT INTO match_statistics VALUES (1, 'away', 'ALL', 'Expected goals', 99.0);
        INSERT INTO match_statistics VALUES (2, 'away', 'ALL', 'Expected goals', 99.0);
    """)
    conn.commit()
    conn.close()
    feats = build_features(db_path, event_id=3, window=2)
    # media correta: (2.0 + 2.5) / 2 = 2.25 — o codigo antigo devolveria
    # (2.0 + 2.5 + 99 + 99) / 4 = 50.625
    assert abs(feats['home_Expected goals'] - 2.25) < 0.01


def test_build_features_ignora_periodos_parciais(db_path):
    """Auditoria P2 (mesma familia): linhas de 1ST/2ND nao entram na media."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO match_statistics VALUES (1, 'home', '1ST', 'Expected goals', 88.0)")
    conn.commit()
    conn.close()
    feats = build_features(db_path, event_id=3, window=2)
    assert abs(feats['home_Expected goals'] - 2.25) < 0.01