"""Shadow Deployment (v2): a conexão read-only é FISICAMENTE incapaz de escrever —
a garantia que permite consumir a produção viva do cron da Copa sem risco de corromper."""
import sqlite3

import pytest

from src import db


def _seed(path) -> None:
    conn = db.connect(str(path))
    conn.execute("INSERT INTO matches(date,home_team,away_team,neutral) "
                 "VALUES('2024-01-01','A','B',1)")
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")   # esvazia o WAL p/ abrir ro limpo
    conn.close()


def test_read_only_allows_reads(tmp_path):
    path = tmp_path / "m.db"
    _seed(path)
    ro = db.connect(str(path), read_only=True)
    assert ro.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 1
    ro.close()


def test_read_only_rejects_writes(tmp_path):
    path = tmp_path / "m.db"
    _seed(path)
    ro = db.connect(str(path), read_only=True)
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("INSERT INTO matches(date,home_team,away_team,neutral) "
                   "VALUES('2024-01-02','C','D',1)")
    ro.close()
