"""Guard de vazamento de segredos na telemetria deste domínio (predictor_core.testing.secrets).

Transforma um segredo acidental no metadata do emit_event em falha de pytest — antes do commit.
"""
from pathlib import Path

from predictor_core.testing.secrets import find_secrets, assert_no_secrets_in_events

EVENTS = Path(__file__).resolve().parents[1] / "events.jsonl"


def test_guard_catches_planted_secret():
    assert find_secrets("leak sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345")


def test_guard_passes_clean_text():
    assert find_secrets('{"score": 0.9, "team": "Brazil"}') == []


def test_real_telemetry_has_no_secrets():
    assert_no_secrets_in_events(EVENTS)   # no-op se ausente; falha se algum segredo vazou
