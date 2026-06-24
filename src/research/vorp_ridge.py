"""ZONA 0 — Extração Causal do VORP via Regressão Ridge.

Variável-alvo : xG diferencial (home_xg − away_xg) por partida.
Variáveis     : matriz esparsa de presença de jogadores
                (+1 home, −1 away) + diferença de Elo como controle.
Treino        : partidas com season ∈ {2021, 2022}
Reserva       : partidas com season ∈ {2023, 2024}

Fallback para jogadores sem histórico (estreantes / transferências):
  VORP_replacement(posição) = média dos 20% inferiores × 0.8  (Rookie Penalty)

Uso:
    python -m src.research.vorp_ridge [--db data/matches.db] [--alpha 1.0]
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.linalg import lsqr

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src import db
from src.ingest import load_config


# ---------------------------------------------------------------------------
# Carregamento de dados
# ---------------------------------------------------------------------------

def _load_matches(conn, seasons):
    """Retorna lista de (event_id, home_team, away_team, home_xg, away_xg, elo_diff)
    filtrando pelas seasons indicadas. elo_diff lido da tabela current_elo."""
    elo = db.load_elo(conn)
    rows = conn.execute(
        "SELECT event_id, home_team, away_team, home_xg, away_xg, season "
        "FROM sofascore_matches "
        "WHERE home_xg IS NOT NULL AND away_xg IS NOT NULL"
    ).fetchall()
    result = []
    for eid, home, away, hxg, axg, season in rows:
        if season not in seasons:
            continue
        elo_diff = elo.get(home, 1500.0) - elo.get(away, 1500.0)
        result.append((eid, home, away, float(hxg), float(axg), elo_diff))
    return result


def _load_player_presence(conn, event_ids):
    """Retorna dict event_id → {player: (team, minutes)} para os eventos pedidos."""
    if not event_ids:
        return {}
    placeholders = ",".join("?" * len(event_ids))
    rows = conn.execute(
        f"SELECT event_id, player, team, minutes FROM sofascore_player_ratings "
        f"WHERE event_id IN ({placeholders}) AND minutes > 0",
        list(event_ids)
    ).fetchall()
    presence = {}
    for eid, player, team, minutes in rows:
        presence.setdefault(eid, {})[player] = (team, minutes)
    return presence


def _load_positions(conn):
    """Retorna dict player → position mais frequente (melhor esforço, LEFT JOIN)."""
    rows = conn.execute(
        "SELECT player, position FROM player_comp_stats WHERE position IS NOT NULL"
    ).fetchall()
    pos_count = {}
    for player, pos in rows:
        pos_count.setdefault(player, {}).setdefault(pos, 0)
        pos_count[player][pos] += 1
    return {p: max(d, key=d.get) for p, d in pos_count.items()}


# ---------------------------------------------------------------------------
# Construção da matriz esparsa
# ---------------------------------------------------------------------------

def _build_matrix(matches, presence, player_index):
    """Constrói X ∈ ℝ^{N × (P+1)} (esparsa) e y ∈ ℝ^N.

    Coluna P = elo_diff (controle contínuo, escalonado por 400).
    Colunas 0..P-1 = indicadores de jogador: +1 (home), −1 (away).
    y = home_xg − away_xg.
    """
    n_matches = len(matches)
    n_players = len(player_index)

    rows_i, cols_j, vals = [], [], []
    y = np.zeros(n_matches)

    for i, (eid, home, away, hxg, axg, elo_diff) in enumerate(matches):
        y[i] = hxg - axg
        # coluna de controle Elo (última coluna)
        rows_i.append(i); cols_j.append(n_players); vals.append(elo_diff / 400.0)
        # indicadores de jogador
        for player, (team, _) in presence.get(eid, {}).items():
            if player not in player_index:
                continue
            sign = +1.0 if team == home else -1.0
            rows_i.append(i); cols_j.append(player_index[player]); vals.append(sign)

    X = csr_matrix((vals, (rows_i, cols_j)), shape=(n_matches, n_players + 1))
    return X, y


# ---------------------------------------------------------------------------
# Ridge via LSQR (sem scikit-learn)
# ---------------------------------------------------------------------------

def _ridge_lsqr(X, y, alpha: float):
    """Ridge regression: min ‖Xβ − y‖² + α‖β‖².
    Aumenta a matriz com √α·I e resolve via LSQR (estável para matrizes esparsas).
    Retorna β (n_features,)."""
    import scipy.sparse as sp
    n, p = X.shape
    # Matriz aumentada: [X; √α·I] — equivalente matemático da Ridge
    sqrt_alpha = np.sqrt(alpha)
    eye = sqrt_alpha * sp.eye(p, format="csr")
    X_aug = sp.vstack([X, eye], format="csr")
    y_aug = np.concatenate([y, np.zeros(p)])
    result = lsqr(X_aug, y_aug, atol=1e-8, btol=1e-8, iter_lim=10_000)
    return result[0]   # coeficientes β


# ---------------------------------------------------------------------------
# Replacement Level e Rookie Penalty
# ---------------------------------------------------------------------------

ROOKIE_PENALTY = 0.8
REPLACEMENT_PERCENTILE = 0.20   # 20% inferiores definem o piso

def _compute_replacement_levels(beta_players: dict, positions: dict) -> dict:
    """Calcula VORP de 'Replacement Level' por posição.
    = média dos 20% inferiores × ROOKIE_PENALTY.
    Jogadores sem posição conhecida usam 'UNKNOWN'."""
    by_pos = {}
    for player, vorp in beta_players.items():
        pos = positions.get(player, "UNKNOWN")
        by_pos.setdefault(pos, []).append(vorp)

    replacement = {}
    for pos, vorps in by_pos.items():
        arr = np.sort(np.array(vorps))
        cutoff = max(1, int(len(arr) * REPLACEMENT_PERCENTILE))
        replacement[pos] = float(arr[:cutoff].mean()) * ROOKIE_PENALTY
    return replacement


# ---------------------------------------------------------------------------
# Entry point principal
# ---------------------------------------------------------------------------

def run(db_path: str, alpha: float = 1.0):
    """Treina o modelo VORP e retorna artefato serializável com:
      - beta_players: dict player → coeficiente Ridge
      - beta_elo: float (coeficiente do controle Elo)
      - replacement_levels: dict posição → VORP de piso
      - fallback_rule: string descrevendo a política para unseen players
      - train_seasons / test_seasons
    """
    conn = db.connect(db_path, read_only=True)

    TRAIN_SEASONS = {"2021", "2022"}
    TEST_SEASONS  = {"2023", "2024"}

    print("[vorp_ridge] carregando partidas de treino…")
    train_matches = _load_matches(conn, TRAIN_SEASONS)
    test_matches  = _load_matches(conn, TEST_SEASONS)

    if not train_matches:
        sys.exit("[vorp_ridge] ERRO: nenhuma partida de treino encontrada em "
                 f"sofascore_matches para seasons {TRAIN_SEASONS}. "
                 "Rode ingest_sofascore primeiro.")

    all_eids = {m[0] for m in train_matches} | {m[0] for m in test_matches}
    presence = _load_player_presence(conn, all_eids)
    positions = _load_positions(conn)

    # Índice global de jogadores (apenas dos que aparecem no treino)
    train_eids = {m[0] for m in train_matches}
    players_in_train = sorted({
        p for eid, pmap in presence.items()
        if eid in train_eids
        for p in pmap
    })
    player_index = {p: i for i, p in enumerate(players_in_train)}

    print(f"[vorp_ridge] {len(train_matches)} partidas treino | "
          f"{len(test_matches)} reserva | {len(player_index)} jogadores únicos")

    X_train, y_train = _build_matrix(train_matches, presence, player_index)

    print(f"[vorp_ridge] X_train shape={X_train.shape}  nnz={X_train.nnz}")
    print(f"[vorp_ridge] ajustando Ridge (alpha={alpha})…")

    beta = _ridge_lsqr(X_train, y_train, alpha=alpha)

    beta_players = {p: float(beta[i]) for p, i in player_index.items()}
    beta_elo     = float(beta[len(player_index)])   # última coluna

    replacement_levels = _compute_replacement_levels(beta_players, positions)

    # Diagnóstico rápido
    vorps = np.array(list(beta_players.values()))
    print(f"[vorp_ridge] VORP: min={vorps.min():.3f}  p5={np.percentile(vorps,5):.3f}  "
          f"median={np.median(vorps):.3f}  p95={np.percentile(vorps,95):.3f}  "
          f"max={vorps.max():.3f}")
    print(f"[vorp_ridge] beta_elo={beta_elo:.4f} (positivo = vantagem Elo → mais xG)")

    for pos, rv in sorted(replacement_levels.items()):
        print(f"[vorp_ridge] replacement_level[{pos}] = {rv:.4f}")

    artifact = {
        "beta_players": beta_players,
        "beta_elo": beta_elo,
        "replacement_levels": replacement_levels,
        "fallback_rule": (
            f"Jogadores sem histórico (estreantes/transferências) recebem "
            f"VORP = replacement_level[posição] × {ROOKIE_PENALTY} "
            f"(já aplicado — média dos {int(REPLACEMENT_PERCENTILE*100)}% "
            f"inferiores da posição, penalidade Rookie incluída). "
            f"Posição desconhecida → chave 'UNKNOWN'."
        ),
        "train_seasons": list(TRAIN_SEASONS),
        "test_seasons": list(TEST_SEASONS),
        "ridge_alpha": alpha,
        "n_players": len(player_index),
        "n_train_matches": len(train_matches),
    }
    return artifact


def main():
    parser = argparse.ArgumentParser(description="VORP Ridge — extração causal de valor de jogador")
    parser.add_argument("--db",    default="data/matches.db")
    parser.add_argument("--alpha", type=float, default=1.0, help="regularização Ridge")
    parser.add_argument("--out",   default=None, help="salvar artefato JSON neste caminho")
    args = parser.parse_args()

    artifact = run(str(ROOT / args.db), alpha=args.alpha)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False))
        print(f"[vorp_ridge] artefato salvo em {out_path}")
    else:
        # resumo compacto
        top = sorted(artifact["beta_players"].items(), key=lambda x: -x[1])[:10]
        print("\nTop 10 VORP (contribuição ao xG diferencial):")
        for player, v in top:
            print(f"  {player:<30} {v:+.4f}")


if __name__ == "__main__":
    main()
