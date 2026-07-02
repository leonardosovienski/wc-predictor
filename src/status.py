"""Painel do estado do banco: o que cada fonte coletou e o que o modelo usa."""
import sqlite3

from . import db
from .ingest import ROOT, load_config
from predictor_core.obs import emit_event

_DOMAIN = "wc"


def _count(conn, sql, params=()):
    try:
        return conn.execute(sql, params).fetchone()[0]
    except sqlite3.OperationalError:
        return None


def run():
    cfg = load_config()
    # db.connect, não sqlite3 cru: cria data/ se faltar (checkout limpo não
    # quebra) e roda a migração de schema antes das queries de colunas novas.
    conn = db.connect(str(ROOT / cfg["database"]))
    line = "=" * 58

    print(line)
    print("ESTADO DO BANCO")
    print(line)

    played = _count(conn, "SELECT COUNT(*) FROM matches WHERE home_score IS NOT NULL")
    if played is not None:
        rng = conn.execute("SELECT MIN(date), MAX(date) FROM matches "
                           "WHERE home_score IS NOT NULL").fetchone()
        fixtures = _count(conn, "SELECT COUNT(*) FROM matches WHERE home_score IS NULL")
        print("\n[resultados de selecoes]  -> ALIMENTA o modelo")
        print(f"  {played} jogos ({rng[0]} a {rng[1]}), {fixtures} fixtures futuros")

    fb = _count(conn, "SELECT COUNT(*) FROM player_comp_stats")
    if fb:
        comps = conn.execute("SELECT competition, COUNT(*) FROM player_comp_stats "
                             "GROUP BY competition").fetchall()
        print("\n[stats de jogador (FBref)]  -> coletado, NAO conectado")
        print(f"  {fb} linhas: " + ", ".join(f"{c} ({n})" for c, n in comps))

    ss = _count(conn, "SELECT COUNT(*) FROM sofascore_matches")
    if ss:
        xg = _count(conn, "SELECT COUNT(*) FROM sofascore_matches WHERE home_xg IS NOT NULL")
        od = _count(conn, "SELECT COUNT(*) FROM sofascore_matches WHERE odds_home IS NOT NULL")
        rt = _count(conn, "SELECT COUNT(*) FROM sofascore_player_ratings")
        print("\n[Sofascore]  -> xG/notas a conectar; odds usadas via Shin")
        print(f"  {ss} jogos ({xg} com xG, {od} com odds), {rt} notas de jogador")

    # cache do modelo (Parte 2)
    from .cron_update_models import config_hash
    elo = db.load_elo(conn)
    prow = db.load_params(conn)
    print("\n[cache do modelo]  -> serve a CLI e o simulador")
    if not elo or not prow:
        print("  vazio — rode `python -m src.cron_update_models`")
    else:
        a, b, alpha, rho, n_cached, cfg_hash, computed_at = prow
        n_now = played
        fresh = (cfg_hash == config_hash(cfg)) and (n_cached == n_now)
        print(f"  {len(elo)} times | a={a:.3f} b={b:.3f} alpha={alpha:.4f} rho={rho:.4f}")
        print(f"  calculado em {computed_at} sobre {n_cached} jogos")
        print(f"  estado: {'atualizado' if fresh else 'DESATUALIZADO — rode o cron'}")

    bt = _count(conn, "SELECT COUNT(*) FROM backtest_bets")
    if bt:
        pnl = conn.execute("SELECT SUM(pnl), SUM(stake) FROM backtest_bets").fetchone()
        print("\n[backtest]  -> Quality Gate do modelo")
        print(f"  {bt} apostas liquidadas | P&L {pnl[0]:+.2f}u | ROI {pnl[0] / pnl[1]:+.1%}")

    emit_event(_DOMAIN, "status_check",
               metrics={"played": float(played or 0),
                        "fbref_rows": float(fb or 0),
                        "sofascore_matches": float(ss or 0),
                        "backtest_bets": float(bt or 0)},
               metadata={"model_cache": "fresh" if (elo and prow) else "empty",
                         "db_path": str(ROOT / cfg["database"])})

    print("\n" + "-" * 58)
    print("modelo: Binomial Negativa + Dixon-Coles (Elo com decay)")
    print("mercado: odds purificadas por Shin no painel do predict")
    print("a conectar: FBref e notas do Sofascore")
    print("-" * 58)


if __name__ == "__main__":
    run()
