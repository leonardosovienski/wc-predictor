"""MarketPricer — precifica mercados a partir da grade de placares do modelo.

ZONA 3 (purista): zero dependência de banco/config/rede. Entrada = grade
bivariada `grid[i][j] = P(casa marca i, fora marca j)` (a mesma que
`model.predict_match` já expõe em `r["grid"]`). Saída = probabilidades por
mercado, prontas para o backtest comparar com as odds.

NÃO reimplementa o modelo. A grade já carrega NB + Dixon-Coles; aqui só somamos
células. Todos os mercados de GOLS derivam desta grade — sem feature nova, sem λ
novo (ver HANDOFF da expansão Fase 1).

SEMÂNTICA DE PUSH (devolução de stake):
  - BTTS, Double Chance, Over/Under em linha .5  → binário (sem push)
  - Draw No Bet                                   → push no empate
  - Handicap asiático                             → push em linha inteira;
    linha de quarto (.25/.75) divide o stake em duas meias-apostas
Funções que podem dar push retornam as TRÊS probabilidades (win/push/lose) para
o settlement liquidar corretamente.
"""
import numpy as np

# Margem de tolerância para somatórios de probabilidade.
_EPS = 1e-12


def _grid(grid) -> np.ndarray:
    g = np.asarray(grid, dtype=float)
    if g.ndim != 2 or g.shape[0] != g.shape[1]:
        raise ValueError("grid deve ser uma matriz quadrada NxN")
    return g


def _margin_indices(n: int):
    """Índices de margem m = i - j para uma grade NxN."""
    i = np.arange(n).reshape(-1, 1)
    j = np.arange(n).reshape(1, -1)
    return i, j


# ------------------------------------------------------------------ #
# 1X2 e derivados sem push                                            #
# ------------------------------------------------------------------ #

def result_1x2(grid) -> dict:
    """Probabilidades 1X2 a partir da grade (casa/empate/fora)."""
    g = _grid(grid)
    p_home = float(np.tril(g, -1).sum())   # i > j
    p_draw = float(np.trace(g))            # i == j
    p_away = float(np.triu(g, 1).sum())    # i < j
    return {"1": p_home, "X": p_draw, "2": p_away}


def double_chance(grid) -> dict:
    """Dupla chance: 1X, X2, 12 (sem push)."""
    o = result_1x2(grid)
    return {"1X": o["1"] + o["X"], "X2": o["X"] + o["2"], "12": o["1"] + o["2"]}


def both_teams_to_score(grid) -> dict:
    """BTTS: Yes = P(casa≥1 ∧ fora≥1), No = complemento (sem push)."""
    g = _grid(grid)
    i, j = _margin_indices(g.shape[0])
    yes = float(g[(i >= 1) & (j >= 1)].sum())
    return {"Yes": yes, "No": 1.0 - yes}


def over_under(grid, line: float) -> dict:
    """Over/Under do total de gols numa linha. Retorna Over/Under/Push.
    Em linhas .5 (padrão de gols) o Push é 0. Em linha inteira (ex.: cartões)
    o total pode igualar a linha → Push > 0."""
    g = _grid(grid)
    i, j = _margin_indices(g.shape[0])
    total = i + j
    over = float(g[total > line].sum())
    push = float(g[total == line].sum())
    under = float(g[total < line].sum())
    return {"Over": over, "Under": under, "Push": push}


def exact_score(grid, home_goals: int, away_goals: int) -> float:
    """P(placar exato). Fora do alcance da grade → 0.0."""
    g = _grid(grid)
    n = g.shape[0]
    if not (0 <= home_goals < n and 0 <= away_goals < n):
        return 0.0
    return float(g[home_goals, away_goals])


# ------------------------------------------------------------------ #
# Mercados com PUSH                                                   #
# ------------------------------------------------------------------ #

def draw_no_bet(grid) -> dict:
    """Draw No Bet: empate devolve o stake (push).

    Retorna win/push/lose para cada lado. A prob condicional (excluindo empate)
    serve para comparar com 1/odd; a prob de push é necessária no settlement.
    """
    o = result_1x2(grid)
    return {
        "1": {"win": o["1"], "push": o["X"], "lose": o["2"]},
        "2": {"win": o["2"], "push": o["X"], "lose": o["1"]},
    }


def _ah_single(grid, home_line: float) -> dict:
    """Handicap asiático de LINHA ÚNICA (inteira ou meia) para o lado da CASA.
    home_line é o handicap aplicado à casa (ex.: -1.0). Margem ajustada =
    (i - j) + home_line. >0 win, ==0 push, <0 lose."""
    g = _grid(grid)
    i, j = _margin_indices(g.shape[0])
    adj = (i - j) + home_line
    win = float(g[adj > _EPS].sum())
    push = float(g[np.abs(adj) <= _EPS].sum())
    lose = float(g[adj < -_EPS].sum())
    return {"win": win, "push": push, "lose": lose}


def asian_handicap(grid, home_line: float) -> dict:
    """Handicap asiático para o lado da CASA, com suporte a linha de QUARTO.

    Linha de quarto (ex.: -0.75) divide o stake em duas meias-apostas nas linhas
    inteira/meia adjacentes (-0.5 e -1.0); win/push/lose são a média das duas.
    Para o lado de FORA, chame com -home_line e troque win↔lose.
    """
    # quarto de linha se a parte fracionária é .25 ou .75
    frac = abs(home_line) % 1.0
    if abs(frac - 0.25) < 1e-9 or abs(frac - 0.75) < 1e-9:
        lo = home_line - 0.25
        hi = home_line + 0.25
        a = _ah_single(grid, lo)
        b = _ah_single(grid, hi)
        return {k: (a[k] + b[k]) / 2.0 for k in ("win", "push", "lose")}
    return _ah_single(grid, home_line)
