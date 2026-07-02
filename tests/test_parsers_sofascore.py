"""Gaps #2 e #3 da auditoria: parsers de odds (fronteira com formato externo) e
o guard is_pre_match. Funções puras — dicts fixos, sem rede, sem disco.

Os 4 bugs achados na auditoria (substring do handicap, fração não-string,
decimal malformado, timestamp em ms) nasceram aqui como xfail e viraram verdes
com os consertos aprovados — os testes agora fixam o comportamento correto."""
from src.ingest_sofascore import (frac_to_decimal, is_pre_match, parse_match,
                                  parse_odds, parse_ou)


# ------------------------------------------------------------- frac_to_decimal
def test_fracao_valida():
    assert frac_to_decimal({"fractionalValue": "5/2"}) == 3.5


def test_fracao_menor_que_um():
    assert frac_to_decimal({"fractionalValue": "1/2"}) == 1.5


def test_divisao_por_zero_vira_none():
    assert frac_to_decimal({"fractionalValue": "5/0"}) is None


def test_fracao_malformada_vira_none():
    assert frac_to_decimal({"fractionalValue": "abc"}) is None


def test_fracao_com_tres_termos_vira_none():
    assert frac_to_decimal({"fractionalValue": "5/2/3"}) is None


def test_fallback_para_decimal_value():
    assert frac_to_decimal({"decimalValue": "2.75"}) == 2.75


def test_sem_valor_nenhum_vira_none():
    assert frac_to_decimal({}) is None


def test_decimal_zero_vira_none():
    # odd 0 não existe; o falsy-check engole — comportamento aceitável.
    assert frac_to_decimal({"decimalValue": 0}) is None


def test_fracao_nao_string_nao_estoura():
    # payload externo pode mandar número onde se espera string de fração.
    assert frac_to_decimal({"fractionalValue": 2.5}) is None


def test_decimal_malformado_nao_estoura():
    assert frac_to_decimal({"decimalValue": "abc"}) is None


def test_frac_to_decimal_key_abertura():
    # initialFractionalValue = abertura; fractionalValue = fechamento. Mesmo choice.
    c = {"fractionalValue": "4/5", "initialFractionalValue": "73/100"}
    assert frac_to_decimal(c) == 1.8                          # default = fechamento
    assert frac_to_decimal(c, "initialFractionalValue") == 1.73   # abertura


def test_frac_to_decimal_initial_ausente_vira_none_sem_fallback():
    # o fallback para decimalValue só vale para o fechamento; abertura ausente = None
    assert frac_to_decimal({"decimalValue": "2.0"}, "initialFractionalValue") is None


def test_parse_odds_initial_le_abertura():
    odds = {"markets": [{"marketId": 1, "choices": [
        {"name": "1", "fractionalValue": "1/1", "initialFractionalValue": "9/10"},
        {"name": "X", "fractionalValue": "2/1", "initialFractionalValue": "21/10"},
        {"name": "2", "fractionalValue": "3/1", "initialFractionalValue": "5/2"}]}]}
    assert parse_odds(odds) == (2.0, 3.0, 4.0)                       # fechamento
    assert parse_odds(odds, initial=True) == (1.9, 3.1, 3.5)        # abertura


# ------------------------------------------------------------- parse_odds
def test_payload_vazio_devolve_nones():
    assert parse_odds(None) == (None, None, None)
    assert parse_odds({}) == (None, None, None)
    assert parse_odds({"markets": []}) == (None, None, None)


def test_market_id_1_sem_nome_e_aceito():
    odds = {"markets": [{"marketId": 1, "choices": [
        {"name": "1", "fractionalValue": "1/1"},
        {"name": "X", "fractionalValue": "2/1"},
        {"name": "2", "fractionalValue": "3/1"}]}]}
    assert parse_odds(odds) == (2.0, 3.0, 4.0)


def test_choice_sem_nome_nao_estoura():
    odds = {"markets": [{"marketId": 1, "choices": [
        {"fractionalValue": "1/1"}]}]}
    assert parse_odds(odds) == (None, None, None)


def test_mercado_parcial_e_aceito_sem_aviso():
    # Documenta a origem do crash do backtest (test_backtest_odds): uma fração
    # malformada numa seleção produz mercado PARCIAL (home presente, resto None)
    # e nada barra essa linha antes do banco.
    odds = {"markets": [{"marketName": "Full time", "choices": [
        {"name": "1", "fractionalValue": "1/1"},
        {"name": "X", "fractionalValue": "lixo"},
        {"name": "2", "fractionalValue": "3/1"}]}]}
    assert parse_odds(odds) == (2.0, None, 4.0)


# ------------------------------------------------------------- parse_ou
def test_ou_linha_inexistente_vira_none():
    odds = {"markets": [{"marketName": "Total goals", "choices": [
        {"name": "Over 1.5", "fractionalValue": "1/2"},
        {"name": "Under 1.5", "fractionalValue": "2/1"}]}]}
    assert parse_ou(odds, 2.5) == (None, None)


def test_ou_sem_under_vira_none():
    odds = {"markets": [{"marketName": "Total goals", "choices": [
        {"name": "Over 2.5", "fractionalValue": "4/5"}]}]}
    assert parse_ou(odds, 2.5) == (None, None)


def test_ou_via_choice_group():
    # handicap no market.choiceGroup, choices só "Over"/"Under".
    odds = {"markets": [{"marketName": "Total goals", "choiceGroup": "2.5",
                         "choices": [
        {"name": "Over", "fractionalValue": "4/5"},
        {"name": "Under", "fractionalValue": "1/1"}]}]}
    assert parse_ou(odds, 2.5) == (1.8, 2.0)


def test_ou_payload_vazio():
    assert parse_ou(None, 2.5) == (None, None)


def test_linha_2_5_nao_pega_odd_da_12_5():
    # o bug mais caro da auditoria: '2.5' in 'over 12.5' era True e a linha
    # 12.5 sobrescrevia a 2.5 calada. Agora o handicap é comparado como número.
    odds = {"markets": [{"marketName": "Total goals", "choices": [
        {"name": "Over 2.5", "fractionalValue": "4/5"},     # 1.8 — a certa
        {"name": "Under 2.5", "fractionalValue": "1/1"},    # 2.0 — a certa
        {"name": "Over 12.5", "fractionalValue": "100/1"},  # 101.0
        {"name": "Under 12.5", "fractionalValue": "1/100"}]}]}
    assert parse_ou(odds, 2.5) == (1.8, 2.0)


# ------------------------------------------------------------- is_pre_match
# Fronteiras já cobertas em test_math.py (futuro/durante/exato/nulo/zero).
# Aqui: a falha SILENCIOSA de unidade — timestamp em MILISSEGUNDOS fica ~1000×
# maior que o epoch em segundos, sempre "futuro", e o guard aprova TUDO como
# pré-jogo, inclusive jogo encerrado. O guard parece ativo e está desligado.
NOW = 1_750_000_000          # ~jun/2025, epoch em segundos (10 dígitos)


def test_jogo_de_2022_visto_em_2026_nao_e_pre():
    # escala real: final de 2022 (epoch ~1.67e9) observada em 2026.
    assert is_pre_match(1_671_375_600, now=1_780_000_000) is False


def test_timestamp_em_ms_nao_e_pre_match():
    # ms fica ~1000× maior que o epoch em segundos: sempre "futuro". Sem o
    # guard de ordem de grandeza, jogo começado há 1h passava como pré-jogo e
    # odd in-play virava abertura — o guard parecia ativo estando desligado.
    started_1h_atras_em_ms = (NOW - 3600) * 1000
    assert is_pre_match(started_1h_atras_em_ms, now=NOW) is False
    # nem jogo realmente futuro passa em ms: unidade suspeita ⇒ conservador.
    assert is_pre_match((NOW + 3600) * 1000, now=NOW) is False


def test_parse_match_normaliza_timestamp_em_ms():
    # se o Sofascore trocar a unidade pra ms, parse_match normaliza (com
    # warning) em vez de estourar no datetime (ano ~57000) — a coleta segue
    # viva com data e start_ts corretos em segundos.
    ev = {"id": 99, "startTimestamp": 1_671_375_600_000,   # 2022-12-18 em ms
          "status": {"type": "notstarted"},
          "homeTeam": {"name": "A"}, "awayTeam": {"name": "B"},
          "homeScore": {}, "awayScore": {}}
    m = parse_match(ev)
    assert m["date"] == "2022-12-18"
    assert m["start_ts"] == 1_671_375_600


def test_parse_match_data_em_utc():
    # sanidade da conversão na unidade correta (segundos).
    ev = {"id": 1, "startTimestamp": 1_671_375_600,   # 2022-12-18 15:00 UTC
          "status": {"type": "finished"},
          "homeTeam": {"name": "Argentina"}, "awayTeam": {"name": "France"},
          "homeScore": {"current": 3}, "awayScore": {"current": 3}}
    m = parse_match(ev)
    assert m["date"] == "2022-12-18"
    assert m["home_score"] == 3
