"""Shin e a contabilidade do CLV — as duas peças matemáticas que, se errarem,
contaminam silenciosamente todo o veredito do modelo. Funções puras, sem I/O."""
import math

import numpy as np
import pytest

from src.math_utils import shin_probabilities
from src.backtest import _settle


# ---------------------------------------------------------------- Shin
def test_shin_probs_somam_um():
    p, z, over = shin_probabilities([2.5, 3.3, 3.0])
    assert math.isclose(p.sum(), 1.0, abs_tol=1e-9)


def test_shin_sem_margem_recai_na_normalizacao():
    # odds cuja implícita já soma <= 1: não há overround pra remover, z=0,
    # Shin tem que devolver a normalização proporcional simples.
    odds = [4.0, 4.0, 4.0]          # implícita 0.75 < 1
    p, z, over = shin_probabilities(odds)
    assert z == 0.0
    assert over < 0.0
    np.testing.assert_allclose(p, [1 / 3, 1 / 3, 1 / 3], atol=1e-9)


def test_shin_overround_positivo_quando_ha_vig():
    # book com margem: implícita soma > 1, overround tem que sair positivo.
    p, z, over = shin_probabilities([1.8, 3.6, 4.5])
    assert over > 0.0
    assert math.isclose(p.sum(), 1.0, abs_tol=1e-9)


def test_shin_penaliza_longshot_bias():
    # Shin desconta mais a probabilidade implícita do favorito do que a do azarão
    # (corrige o favorite-longshot bias). A prob real do azarão fica ABAIXO da
    # implícita crua, e a do favorito ACIMA da sua fração normalizada ingênua.
    odds = [1.5, 4.5, 7.0]
    pi = np.array([1 / o for o in odds])
    p, z, over = shin_probabilities(odds)
    assert z > 0.0
    # azarão (índice 2): Shin puxa pra baixo vs. a implícita normalizada
    naive = pi / pi.sum()
    assert p[2] < naive[2]
    assert p[0] > naive[0]


def test_shin_duas_saidas_over_under():
    # mercado de totais (2 resultados) — mesma propriedade de soma 1.
    p, z, over = shin_probabilities([1.95, 1.95])
    assert len(p) == 2
    assert math.isclose(p.sum(), 1.0, abs_tol=1e-9)


# ---------------------------------------------------------------- CLV / ledger
def _ctx(**over):
    base = dict(date="2026-06-20", competition="WC", home="Brazil", away="Serbia",
                elo_diff=120.0, lambda_home=1.8, lambda_away=0.9,
                score="2-0", result="home")
    base.update(over)
    return base


def test_clv_mede_contra_shin_do_fechamento():
    # CLV = odd pactuada * p_shin_close - 1. Aposta na abertura 2.10, fechamento
    # com prob justa 0.52 → 2.10*0.52-1 = 0.092.
    row = _settle("1x2", "home", p_model=0.60, p_shin_close=0.52,
                  odd_open=2.10, odd_close=1.95, won=1, ctx=_ctx(),
                  min_edge=0.0, max_edge=1.0)
    assert row is not None
    assert row["clv"] == round(2.10 * 0.52 - 1.0, 4)
    assert row["beat_close"] == 1          # clv > 0


def test_pnl_liquida_no_preco_pactuado():
    # vitória paga odd_open-1 (apostou na abertura), não no fechamento.
    win = _settle("1x2", "home", 0.60, 0.52, 2.10, 1.95, 1, _ctx(),
                  0.0, 1.0)
    assert win["pnl"] == round(2.10 - 1.0, 3)
    loss = _settle("1x2", "home", 0.60, 0.52, 2.10, 1.95, 0,
                   _ctx(result="away", score="0-1"), 0.0, 1.0)
    assert loss["pnl"] == -1.0


def test_bet_at_open_quando_ha_abertura():
    row = _settle("1x2", "home", 0.60, 0.52, 2.10, 1.95, 1, _ctx(), 0.0, 1.0)
    assert row["bet_at"] == "open"
    assert row["offered_odd"] == 2.10      # apostou na abertura


def test_bet_at_close_no_fallback():
    # base histórica: abertura desconhecida (None) → cai pro fechamento.
    row = _settle("1x2", "home", 0.60, 0.52, None, 1.95, 1, _ctx(), 0.0, 1.0)
    assert row["bet_at"] == "close"
    assert row["offered_odd"] == 1.95


def test_settle_rejeita_fora_da_janela_de_edge():
    # edge vs preço = p_model - 1/odd. Com p_model baixo e odd baixa, edge < min.
    out = _settle("1x2", "home", p_model=0.30, p_shin_close=0.50,
                  odd_open=1.95, odd_close=1.95, won=0, ctx=_ctx(),
                  min_edge=0.05, max_edge=0.20)
    assert out is None


# ---------------------------------------------------------------- guard in-play
from src.ingest_sofascore import is_pre_match


def test_pre_match_quando_apito_no_futuro():
    assert is_pre_match(start_ts=1_000_100, now=1_000_000) is True


def test_nao_pre_match_durante_o_jogo():
    # jogo começou há 15 min: odd é in-play, NUNCA abertura.
    assert is_pre_match(start_ts=1_000_000, now=1_000_900) is False


def test_nao_pre_match_no_apito_exato():
    # fronteira: start == now não é estritamente futuro → não é pré-jogo.
    assert is_pre_match(start_ts=1_000_000, now=1_000_000) is False


def test_sem_timestamp_assume_nao_pre_match():
    # conservador: melhor perder uma abertura do que gravar uma falsa.
    assert is_pre_match(start_ts=None, now=1_000_000) is False
    assert is_pre_match(start_ts=0, now=1_000_000) is False
