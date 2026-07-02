"""
Testa TODAS as features disponiveis em match_statistics
e gera uma tabela comparativa de Brier Score e spread do ProbMax.

Fixes da auditoria 2026-07-02:
  P1  — history do MLE no formato correto (elo_diff, hs, as). A versao anterior
        passava [elo_home, elo_away, hs, as]: o fit tratava o Elo do visitante
        (~1500) como "gols do mandante" (a cravado no bound, lambda ~ 23 gols).
        TODA a tabela de features gerada antes deste fix e' invalida.
  P3  — Elo forward-only por data do evento (ratings_asof), nao o current_elo
        de hoje (lookahead).
  P12 — banco aberto em modo somente-leitura (mandato shadow).
"""
import sys
import numpy as np
from src import db
from src.ingest import ROOT, load_config
from src.model import fit_goal_model, predict_match
from src.feature_builder import build_features, DEFAULT_FEATURES
from src.predict import _canon
from src.ratings import ratings_asof

DB_PATH = str(ROOT / "data" / "matches.db")


def brier_1x2(y_true, proba_matrix):
    """Brier Score para 3 classes (home, draw, away)."""
    n = len(y_true)
    y_onehot = np.zeros((n, 3))
    y_onehot[np.arange(n), y_true] = 1.0
    return float(np.mean(np.sum((proba_matrix - y_onehot) ** 2, axis=1)))


def load_rows_with_forward_elo(conn, cfg, extra_where: str = ""):
    """Jogos com estatisticas + Elo PRE-JOGO forward-only (P3).
    Retorna tuplas (event_id, home, away, hs, as, date, elo_home, elo_away)
    — mesmo layout posicional que os scripts ja consumiam."""
    base_rows = conn.execute(f"""
        SELECT sm.event_id, sm.home_team, sm.away_team,
               sm.home_score, sm.away_score, sm.date
        FROM sofascore_matches sm
        JOIN match_statistics ms ON sm.event_id = ms.event_id
        WHERE sm.home_score IS NOT NULL {extra_where}
        GROUP BY sm.event_id
        ORDER BY sm.date
    """).fetchall()

    m_rows = conn.execute(
        "SELECT date, home_team, away_team, home_score, away_score, "
        "tournament, neutral FROM matches WHERE home_score IS NOT NULL "
        "ORDER BY date").fetchall()
    dates = {r[5] for r in base_rows}
    snaps = ratings_asof(m_rows, cfg["elo"], dates)
    snaps = {d: {_canon(t): e for t, e in s.items()} for d, s in snaps.items()}

    rows = []
    for eid, home, away, hs, as_, d in base_rows:
        snap = snaps.get(d, {})
        rows.append((eid, home, away, hs, as_, d,
                     snap.get(_canon(home or ""), 1500),
                     snap.get(_canon(away or ""), 1500)))
    return rows


def test_feature(conn, feature_name, train_rows, test_rows):
    """
    Testa uma feature especifica.
    Retorna dict com metricas.
    """
    # Prepara history no formato que fit_goal_model consome: (diff, hs, as).
    # Auditoria P1: NAO passar [elo_home, elo_away, hs, as].
    history = []
    for r in train_rows:
        elo_home = r[6] if r[6] is not None else 1500
        elo_away = r[7] if r[7] is not None else 1500
        history.append((elo_home - elo_away, r[3], r[4]))

    # Extrai delta_feature para cada jogo
    delta_train = []
    for r in train_rows:
        feats = build_features(DB_PATH, r[0])
        home_val = feats.get(f'home_{feature_name}', 0.0) or 0.0
        away_val = feats.get(f'away_{feature_name}', 0.0) or 0.0
        delta_train.append(home_val - away_val)

    # Treina baseline
    params_base = fit_goal_model(history)

    # Treina com feature
    params_feat = fit_goal_model(history, delta_xg=delta_train)
    theta_xg = params_feat[4] if len(params_feat) == 5 else 0.0

    # Avalia no teste
    y_true = []
    proba_base = []
    proba_feat = []

    for r in test_rows:
        if r[3] > r[4]:
            y_true.append(0)
        elif r[3] == r[4]:
            y_true.append(1)
        else:
            y_true.append(2)

        feats = build_features(DB_PATH, r[0])
        home_val = feats.get(f'home_{feature_name}', 0.0) or 0.0
        away_val = feats.get(f'away_{feature_name}', 0.0) or 0.0
        delta = home_val - away_val

        elo_home = r[6] if r[6] is not None else 1500
        elo_away = r[7] if r[7] is not None else 1500

        pred_base = predict_match(elo_home, elo_away, params_base)
        proba_base.append([pred_base['p_win'], pred_base['p_draw'],
                           pred_base['p_loss']])

        pred_feat = predict_match(elo_home, elo_away, params_feat, delta_xg=delta)
        proba_feat.append([pred_feat['p_win'], pred_feat['p_draw'],
                           pred_feat['p_loss']])

    proba_base = np.array(proba_base)
    proba_feat = np.array(proba_feat)
    y_true = np.array(y_true)

    brier_base = brier_1x2(y_true, proba_base)
    brier_feat = brier_1x2(y_true, proba_feat)

    probmax_base = np.max(proba_base[:, [0, 2]], axis=1)
    probmax_feat = np.max(proba_feat[:, [0, 2]], axis=1)

    return {
        'feature': feature_name,
        'theta_xg': theta_xg,
        'brier_base': brier_base,
        'brier_feat': brier_feat,
        'improvement': brier_base - brier_feat,
        'probmax_p50_base': np.percentile(probmax_base, 50),
        'probmax_p50_feat': np.percentile(probmax_feat, 50),
        'probmax_p90_base': np.percentile(probmax_base, 90),
        'probmax_p90_feat': np.percentile(probmax_feat, 90),
        'probmax_max_base': np.max(probmax_base),
        'probmax_max_feat': np.max(probmax_feat),
    }


def main():
    cfg = load_config()
    # P12: somente-leitura — pesquisa nao pode escrever no banco (shadow).
    conn = db.connect(DB_PATH, read_only=True)

    rows = load_rows_with_forward_elo(conn, cfg)

    # Descobre todas as features disponiveis
    all_stats = conn.execute("""
        SELECT DISTINCT stat_name FROM match_statistics
        WHERE period = 'ALL'
        ORDER BY stat_name
    """).fetchall()
    all_features = [r[0] for r in all_stats]

    conn.close()

    if len(rows) < 20:
        print(f"Apenas {len(rows)} jogos com estatisticas. Precisa de >= 20.")
        return

    split_idx = int(len(rows) * 0.8)
    train_rows = rows[:split_idx]
    test_rows = rows[split_idx:]

    print(f"Treino: {len(train_rows)} jogos, Teste: {len(test_rows)} jogos")
    print(f"Features disponiveis: {len(all_features)}")
    print()

    # Testa cada feature
    results = []
    for i, feat in enumerate(all_features):
        print(f"[{i+1}/{len(all_features)}] Testando: {feat}...", end=" ", flush=True)
        try:
            r = test_feature(None, feat, train_rows, test_rows)
            results.append(r)
            status = "^" if r['improvement'] > 0 else "v"
            print(f"theta={r['theta_xg']:.4f} Brier={status}{abs(r['improvement']):.4f}")
        except Exception as e:
            print(f"ERRO: {e}")

    # Ordena por melhora no Brier
    results.sort(key=lambda r: r['improvement'], reverse=True)

    # Tabela final
    print(f"\n{'Feature':<30s} {'theta':>7s} {'Brier_base':>10s} {'Brier_feat':>10s} "
          f"{'Melhora':>8s} {'p50_base':>8s} {'p50_feat':>8s} {'p90_base':>8s} "
          f"{'p90_feat':>8s} {'max_base':>8s} {'max_feat':>8s}")
    print("-" * 130)

    for r in results:
        print(f"{r['feature']:<30s} {r['theta_xg']:>+7.4f} "
              f"{r['brier_base']:>10.4f} {r['brier_feat']:>10.4f} "
              f"{r['improvement']:>+8.4f} "
              f"{r['probmax_p50_base']:>7.2%} {r['probmax_p50_feat']:>7.2%} "
              f"{r['probmax_p90_base']:>7.2%} {r['probmax_p90_feat']:>7.2%} "
              f"{r['probmax_max_base']:>7.2%} {r['probmax_max_feat']:>7.2%}")

    # Melhores e piores
    best = results[0]
    worst = results[-1]
    improved = [r for r in results if r['improvement'] > 0]
    print(f"\nMelhor feature: {best['feature']} (melhora={best['improvement']:.4f})")
    print(f"Pior feature:   {worst['feature']} (melhora={worst['improvement']:.4f})")
    print(f"Features que melhoraram o Brier: {len(improved)}/{len(results)}")
    if improved:
        print("Lista das que melhoraram:")
        for r in improved:
            print(f"  {r['feature']:<30s} +{r['improvement']:.4f}  theta={r['theta_xg']:.4f}")


if __name__ == '__main__':
    main()
