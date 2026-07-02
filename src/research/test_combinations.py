"""
Testa COMBINAÇÕES de features (pares) para ver se juntas melhoram mais que isoladas.

Fixes da auditoria 2026-07-02: mesmos da verify_calibration —
  P1  — history no formato (elo_diff, hs, as), nao [elo_h, elo_a, hs, as];
  P3  — Elo forward-only por data (ratings_asof), nao current_elo (lookahead);
  P12 — banco somente-leitura.
Mantido o recorte date >= '2026-06-01' da versao original (documentado: este
script olha SO a Copa 2026; a base completa e' a do verify_calibration).
"""
import sys
import numpy as np
from src import db
from src.ingest import ROOT, load_config
from src.model import fit_goal_model, predict_match
from src.feature_builder import build_features
from src.research.verify_calibration import load_rows_with_forward_elo, brier_1x2

DB_PATH = str(ROOT / "data" / "matches.db")

# Features que mostraram sinal no teste individual
CANDIDATES = [
    'Expected goals',
    'Shots on target',
    'Shots inside box',
    'Big chances',
]


def test_combination(conn, feature_names, train_rows, test_rows):
    """Testa uma combinação de features (delta médio delas)."""
    # Auditoria P1: history no formato (diff, hs, as).
    history = []
    for r in train_rows:
        elo_home = r[6] if r[6] is not None else 1500
        elo_away = r[7] if r[7] is not None else 1500
        history.append((elo_home - elo_away, r[3], r[4]))

    # Delta combinado = média dos deltas de cada feature
    delta_train = []
    for r in train_rows:
        feats = build_features(DB_PATH, r[0])
        deltas = []
        for f in feature_names:
            home_val = feats.get(f'home_{f}', 0.0) or 0.0
            away_val = feats.get(f'away_{f}', 0.0) or 0.0
            deltas.append(home_val - away_val)
        delta_train.append(np.mean(deltas) if deltas else 0.0)

    params_base = fit_goal_model(history)
    params_feat = fit_goal_model(history, delta_xg=delta_train)
    theta_xg = params_feat[4] if len(params_feat) == 5 else 0.0

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
        deltas = []
        for f in feature_names:
            home_val = feats.get(f'home_{f}', 0.0) or 0.0
            away_val = feats.get(f'away_{f}', 0.0) or 0.0
            deltas.append(home_val - away_val)
        delta = np.mean(deltas) if deltas else 0.0

        elo_home = r[6] if r[6] is not None else 1500
        elo_away = r[7] if r[7] is not None else 1500

        pred_base = predict_match(elo_home, elo_away, params_base)
        proba_base.append([pred_base['p_win'], pred_base['p_draw'], pred_base['p_loss']])

        pred_feat = predict_match(elo_home, elo_away, params_feat, delta_xg=delta)
        proba_feat.append([pred_feat['p_win'], pred_feat['p_draw'], pred_feat['p_loss']])

    proba_base = np.array(proba_base)
    proba_feat = np.array(proba_feat)
    y_true = np.array(y_true)

    brier_base = brier_1x2(y_true, proba_base)
    brier_feat = brier_1x2(y_true, proba_feat)
    probmax_base = np.max(proba_base[:, [0, 2]], axis=1)
    probmax_feat = np.max(proba_feat[:, [0, 2]], axis=1)

    return {
        'features': '+'.join(feature_names),
        'theta_xg': theta_xg,
        'brier_base': brier_base,
        'brier_feat': brier_feat,
        'improvement': brier_base - brier_feat,
        'probmax_max_base': np.max(probmax_base),
        'probmax_max_feat': np.max(probmax_feat),
    }


def main():
    cfg = load_config()
    # P12: somente-leitura.
    conn = db.connect(DB_PATH, read_only=True)
    rows = load_rows_with_forward_elo(conn, cfg,
                                      extra_where="AND sm.date >= '2026-06-01'")
    conn.close()

    split_idx = int(len(rows) * 0.8)
    train_rows = rows[:split_idx]
    test_rows = rows[split_idx:]

    print(f"Treino: {len(train_rows)} jogos, Teste: {len(test_rows)} jogos")
    print(f"Candidatas: {CANDIDATES}\n")

    results = []

    # Individuais (para referência)
    for f in CANDIDATES:
        print(f"Testando: {f} (individual)...", end=" ", flush=True)
        r = test_combination(None, [f], train_rows, test_rows)
        results.append(r)
        status = "^" if r['improvement'] > 0 else "v"
        print(f"theta={r['theta_xg']:.4f} Brier={status}{abs(r['improvement']):.4f}")

    # Pares
    for i in range(len(CANDIDATES)):
        for j in range(i + 1, len(CANDIDATES)):
            combo = [CANDIDATES[i], CANDIDATES[j]]
            name = f"{CANDIDATES[i]}+{CANDIDATES[j]}"
            print(f"Testando: {name}...", end=" ", flush=True)
            r = test_combination(None, combo, train_rows, test_rows)
            results.append(r)
            status = "^" if r['improvement'] > 0 else "v"
            print(f"theta={r['theta_xg']:.4f} Brier={status}{abs(r['improvement']):.4f}")

    # Trio
    if len(CANDIDATES) >= 3:
        combo = CANDIDATES[:3]
        name = '+'.join(combo)
        print(f"Testando: {name}...", end=" ", flush=True)
        r = test_combination(None, combo, train_rows, test_rows)
        results.append(r)
        status = "^" if r['improvement'] > 0 else "v"
        print(f"theta={r['theta_xg']:.4f} Brier={status}{abs(r['improvement']):.4f}")

    # Todas juntas
    print(f"Testando: TODAS...", end=" ", flush=True)
    r = test_combination(None, CANDIDATES, train_rows, test_rows)
    results.append(r)
    status = "^" if r['improvement'] > 0 else "v"
    print(f"theta={r['theta_xg']:.4f} Brier={status}{abs(r['improvement']):.4f}")

    results.sort(key=lambda r: r['improvement'], reverse=True)

    print(f"\n{'Features':<40s} {'theta':>8s} {'Brier_base':>10s} {'Brier_feat':>10s} "
          f"{'Melhora':>8s} {'max_base':>8s} {'max_feat':>8s}")
    print("-" * 90)
    for r in results:
        print(f"{r['features']:<40s} {r['theta_xg']:>+8.4f} "
              f"{r['brier_base']:>10.4f} {r['brier_feat']:>10.4f} "
              f"{r['improvement']:>+8.4f} "
              f"{r['probmax_max_base']:>7.2%} {r['probmax_max_feat']:>7.2%}")

    best = results[0]
    print(f"\nMelhor: {best['features']} (melhora={best['improvement']:.4f}, "
          f"ProbMax: {best['probmax_max_base']:.2%} → {best['probmax_max_feat']:.2%})")


if __name__ == '__main__':
    main()
