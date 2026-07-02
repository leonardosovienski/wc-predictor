# src/diagnose_event_data.py
import sqlite3
from src import db
from src.ingest import ROOT, load_config

def main():
    cfg = load_config()
    db_path = ROOT / cfg["database"]
    conn = db.connect(str(db_path), read_only=True)
    cursor = conn.cursor()

    print("\n=== ODDS_LINES ===\n")
    for market in ['cards', 'corners']:
        cursor.execute("SELECT COUNT(*) FROM odds_lines WHERE market = ?", (market,))
        count = cursor.fetchone()[0]
        print(f"market='{market}': {count} linhas")
        if count > 0:
            cursor.execute("SELECT event_id, line, odd_a, odd_b, odd_a_open, odd_b_open FROM odds_lines WHERE market = ? LIMIT 3", (market,))
            for row in cursor.fetchall():
                print(f"  event_id={row[0]}, line={row[1]}, close=({row[2]},{row[3]}), open=({row[4]},{row[5]})")

    print("\n=== STAT_NAMES disponíveis (amostra) ===\n")
    cursor.execute("SELECT DISTINCT stat_name FROM match_statistics ORDER BY stat_name")
    stats = [r[0] for r in cursor.fetchall()]
    print(f"Total: {len(stats)} nomes")
    for s in stats[:30]:
        print(f"  {s}")
    if len(stats) > 30:
        print(f"  ... e mais {len(stats)-30}")

    print("\n=== Correspondência odds_lines + match_statistics ===\n")
    for market in ['cards', 'corners']:
        # Apenas odds_lines com o market
        cursor.execute("SELECT COUNT(DISTINCT event_id) FROM odds_lines WHERE market = ?", (market,))
        odds_events = cursor.fetchone()[0]
        print(f"{market}: {odds_events} event_ids com odds")

        # Quantos desses têm alguma estatística (qualquer)
        cursor.execute("""
            SELECT COUNT(DISTINCT ol.event_id)
            FROM odds_lines ol
            JOIN match_statistics ms ON ol.event_id = ms.event_id
            WHERE ol.market = ?
        """, (market,))
        joined = cursor.fetchone()[0]
        print(f"  com alguma estatística: {joined}")

        # Verificar com nomes candidatos
        for stat_candidate in ['Yellow cards', 'Cards', 'Corner kicks', 'Corners']:
            cursor.execute("""
                SELECT COUNT(DISTINCT ol.event_id)
                FROM odds_lines ol
                JOIN match_statistics ms ON ol.event_id = ms.event_id
                WHERE ol.market = ? AND ms.stat_name = ?
            """, (market, stat_candidate))
            cnt = cursor.fetchone()[0]
            if cnt > 0:
                print(f"  com estatística '{stat_candidate}': {cnt}")

    print("\n=== Odds abertas (open) não nulas ===\n")
    for market in ['cards', 'corners']:
        cursor.execute("""
            SELECT COUNT(*) FROM odds_lines 
            WHERE market = ? AND odd_a_open IS NOT NULL AND odd_b_open IS NOT NULL
        """, (market,))
        open_not_null = cursor.fetchone()[0]
        print(f"{market}: {open_not_null} linhas com odd_a_open e odd_b_open não nulos")

    # Verificar se a query original (com JOIN duplo) retornaria algo para um evento específico
    print("\n=== Teste da query original (primeiro evento com odds) ===\n")
    for market in ['cards', 'corners']:
        cursor.execute("SELECT event_id FROM odds_lines WHERE market = ? LIMIT 1", (market,))
        row = cursor.fetchone()
        if row:
            eid = row[0]
            print(f"Testando event_id={eid} para {market}:")
            # Verifica se há estatística 'home' e 'away' com o nome candidato
            for stat_candidate in ['Yellow cards', 'Cards', 'Corner kicks', 'Corners']:
                cursor.execute("""
                    SELECT COUNT(*) FROM match_statistics 
                    WHERE event_id = ? AND team = 'home' AND stat_name = ?
                """, (eid, stat_candidate))
                home_count = cursor.fetchone()[0]
                cursor.execute("""
                    SELECT COUNT(*) FROM match_statistics 
                    WHERE event_id = ? AND team = 'away' AND stat_name = ?
                """, (eid, stat_candidate))
                away_count = cursor.fetchone()[0]
                if home_count > 0 and away_count > 0:
                    print(f"  Estatística '{stat_candidate}' encontrada para home e away.")
                else:
                    print(f"  Estatística '{stat_candidate}': home={home_count}, away={away_count}")

    conn.close()

if __name__ == "__main__":
    main()