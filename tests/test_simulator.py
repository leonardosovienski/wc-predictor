"""derive_groups monta os grupos a partir do grafo de fixtures (jogos sem placar),
sem hardcode das chaves. Injeta um minigrafo em :memory: e prova a derivação."""
from src import db
from src.simulator import derive_groups


def _round_robin(conn, teams, tournament="FIFA World Cup"):
    """Insere os 6 jogos (sem placar) de um grupo de 4 em matches."""
    rows = []
    for i in range(len(teams)):
        for j in range(i + 1, len(teams)):
            rows.append((f"2026-06-{10+i}{j}", teams[i], teams[j],
                         None, None, tournament, "", "", 1))
    conn.executemany(
        "INSERT INTO matches (date, home_team, away_team, home_score, away_score, "
        "tournament, city, country, neutral) VALUES (?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()


def test_deriva_dois_grupos_de_quatro():
    conn = db.connect(":memory:")
    _round_robin(conn, ["A1", "A2", "A3", "A4"])
    _round_robin(conn, ["B1", "B2", "B3", "B4"])

    groups = derive_groups(conn)
    assert len(groups) == 2
    assert all(len(g) == 4 for g in groups)
    flat = {t for g in groups for t in g}
    assert flat == {"A1", "A2", "A3", "A4", "B1", "B2", "B3", "B4"}
    conn.close()


def test_ignora_componente_de_tamanho_errado():
    # um confronto solto (2 times) não forma grupo de 4 e tem que ser descartado.
    conn = db.connect(":memory:")
    _round_robin(conn, ["A1", "A2", "A3", "A4"])
    conn.execute(
        "INSERT INTO matches (date, home_team, away_team, home_score, away_score, "
        "tournament, city, country, neutral) VALUES "
        "('2026-07-01','X','Y',NULL,NULL,'FIFA World Cup','','',1)")
    conn.commit()

    groups = derive_groups(conn)
    assert len(groups) == 1
    assert set(groups[0]) == {"A1", "A2", "A3", "A4"}
    conn.close()


def test_ignora_jogos_ja_disputados():
    # derive_groups só olha fixtures FUTURAS (home_score IS NULL). Jogo com placar
    # não entra no grafo.
    conn = db.connect(":memory:")
    conn.execute(
        "INSERT INTO matches (date, home_team, away_team, home_score, away_score, "
        "tournament, city, country, neutral) VALUES "
        "('2022-11-20','Qatar','Ecuador',0,2,'FIFA World Cup','','',1)")
    conn.commit()
    assert derive_groups(conn) == []
    conn.close()
