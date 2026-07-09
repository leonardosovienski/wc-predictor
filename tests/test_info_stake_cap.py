"""Trava OPT-IN de stake para mercados sem CLV validado (auditoria 2026-07-09).
Sem BETLOG_MAX_INFO_STAKE nada muda (o protocolo atual permite informativas
com o stake que o operador quiser); com a env var, registrar informativa acima
do teto vira erro ANTES de gravar. Mercado validado (ou25) nunca é afetado.
"""
import pytest

from src import bet_log


@pytest.fixture()
def livro(tmp_path):
    return str(tmp_path / "bets.jsonl")


def test_sem_env_var_nada_muda(livro, monkeypatch):
    monkeypatch.delenv("BETLOG_MAX_INFO_STAKE", raising=False)
    rec = bet_log.add_bet("A", "B", "ou15_1t", "under", 1.5, stake=2.0, path=livro)
    assert rec["stake"] == 2.0


def test_teto_bloqueia_informativa_acima(livro, monkeypatch):
    monkeypatch.setenv("BETLOG_MAX_INFO_STAKE", "0.5")
    with pytest.raises(ValueError, match="SEM CLV"):
        bet_log.add_bet("A", "B", "ou15_1t", "under", 1.5, stake=1.0, path=livro)


def test_teto_permite_informativa_dentro(livro, monkeypatch):
    monkeypatch.setenv("BETLOG_MAX_INFO_STAKE", "0.5")
    rec = bet_log.add_bet("A", "B", "ou15_1t", "under", 1.5, stake=0.5, path=livro)
    assert rec["stake"] == 0.5


def test_mercado_validado_ignora_teto(livro, monkeypatch):
    monkeypatch.setenv("BETLOG_MAX_INFO_STAKE", "0.5")
    rec = bet_log.add_bet("A", "B", "ou25", "under", 1.9, stake=1.0, path=livro)
    assert rec["stake"] == 1.0
