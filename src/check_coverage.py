# src/check_coverage.py
"""Verifica cobertura cruzada entre sofascore_matches, match_statistics e odds_lines.
Uso: python -m src.check_coverage
"""

from src import db
from src.ingest import ROOT, load_config

def main():
    cfg = load_config()
    db_path = ROOT / cfg["database"]
    conn = db.connect(str(db_path), read_only=True)
    cursor = conn.cursor()

    # Total de jogos do Sofascore (que já foram processados)
    cursor.execute("SELECT COUNT(*) FROM sofascore_matches")
    total_sofascore = cursor.fetchone()[0]

    # Jogos com estatísticas (match_statistics)
    cursor.execute("SELECT COUNT(DISTINCT event_id) FROM match_statistics")
    stats_matches = cursor.fetchone()[0]

    # Jogos com odds 1X2 (em sofascore_matches)
    cursor.execute("""
        SELECT COUNT(*) FROM sofascore_matches 
        WHERE odds_home IS NOT NULL AND odds_draw IS NOT NULL AND odds_away IS NOT NULL
    """)
    odds_1x2 = cursor.fetchone()[0]

    # Jogos com odds de cards (em odds_lines)
    cursor.execute("SELECT COUNT(DISTINCT event_id) FROM odds_lines WHERE market='cards'")
    odds_cards = cursor.fetchone()[0]

    # Jogos com odds de corners (em odds_lines)
    cursor.execute("SELECT COUNT(DISTINCT event_id) FROM odds_lines WHERE market='corners'")
    odds_corners = cursor.fetchone()[0]

    # Cobertura conjunta: jogos que têm estatísticas E odds de cards
    cursor.execute("""
        SELECT COUNT(DISTINCT ms.event_id)
        FROM match_statistics ms
        JOIN odds_lines ol ON ms.event_id = ol.event_id
        WHERE ol.market = 'cards'
    """)
    stats_and_cards = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(DISTINCT ms.event_id)
        FROM match_statistics ms
        JOIN odds_lines ol ON ms.event_id = ol.event_id
        WHERE ol.market = 'corners'
    """)
    stats_and_corners = cursor.fetchone()[0]

    print("\n=== COBERTURA DE DADOS (apenas Sofascore) ===\n")
    print(f"Total de jogos no Sofascore:              {total_sofascore}")
    print(f"Jogos com estatísticas (match_stats):     {stats_matches} ({stats_matches/total_sofascore*100:.1f}%)")
    print(f"Jogos com odds 1X2 (em sofascore_matches):{odds_1x2} ({odds_1x2/total_sofascore*100:.1f}%)")
    print(f"Jogos com odds de CARDS (em odds_lines):  {odds_cards} ({odds_cards/total_sofascore*100:.1f}%)")
    print(f"Jogos com odds de CORNERS (em odds_lines):{odds_corners} ({odds_corners/total_sofascore*100:.1f}%)")
    print()
    print(f"Jogos com stats + odds cards:             {stats_and_cards} ({stats_and_cards/stats_matches*100:.1f}% dos com stats)" if stats_matches else "Jogos com stats + odds cards: 0")
    print(f"Jogos com stats + odds corners:           {stats_and_corners} ({stats_and_corners/stats_matches*100:.1f}% dos com stats)" if stats_matches else "Jogos com stats + odds corners: 0")

    # Breakdown por competição (usando sofascore_matches)
    print("\n--- Por competição (top 5) ---")
    cursor.execute("""
        SELECT 
            sm.competition,
            COUNT(DISTINCT sm.event_id) AS total,
            COUNT(DISTINCT ms.event_id) AS stats,
            COUNT(DISTINCT CASE WHEN ol.market='cards' THEN ol.event_id END) AS cards_odds,
            COUNT(DISTINCT CASE WHEN ol.market='corners' THEN ol.event_id END) AS corners_odds
        FROM sofascore_matches sm
        LEFT JOIN match_statistics ms ON sm.event_id = ms.event_id
        LEFT JOIN odds_lines ol ON sm.event_id = ol.event_id AND ol.market IN ('cards','corners')
        GROUP BY sm.competition
        ORDER BY total DESC
        LIMIT 5
    """)
    for row in cursor.fetchall():
        print(f"{row[0]}: total={row[1]}, stats={row[2]}, cards_odds={row[3]}, corners_odds={row[4]}")

    conn.close()

if __name__ == "__main__":
    main()