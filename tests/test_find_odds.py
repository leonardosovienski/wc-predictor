"""Testes do casamento odds↔jogo e do SWAP de orientação — o gap "MAIS PERIGOSO"
do HANDOFF: um bug aqui aposta na odd do time errado sem exceção, com ledger
plausível e P&L/CLV lixo. Estes testes travam a garantia: o mando (home) SEMPRE
recebe a própria odd, qualquer que seja a orientação com que as odds foram
armazenadas. (2ª leva de pytest — Red Team jun/2026.)
"""
from src.backtest import _find_odds
from src.predict import _canon


def _cand(od_date="2022-12-18", ch="argentina",
          oh=2.0, odr=3.0, oa=4.0, oov=1.8, oun=2.1,
          oh_o=2.1, od_o=3.1, oa_o=4.1, oov_o=1.85, oun_o=2.15):
    """Candidato como _build_odds_index monta: stored-home=ch, oh/oa orientados a ch."""
    return (od_date, ch, oh, odr, oa, oov, oun, oh_o, od_o, oa_o, oov_o, oun_o)


def _odds(*cands, home="argentina", away="brazil"):
    return {frozenset((_canon(home), _canon(away))): list(cands)}


# ---------------------------------------------------- swap de orientação (1X2)
def test_sem_swap_quando_armazenado_bate_com_mando():
    # stored-home = argentina; consultamos com home=argentina → sem swap
    odds = _odds(_cand(ch="argentina"))
    close_1x2, close_ou, open_1x2, open_ou = _find_odds(odds, "argentina", "brazil", "2022-12-18")
    assert close_1x2 == (2.0, 3.0, 4.0)        # (home, empate, away) na ordem armazenada
    assert open_1x2 == (2.1, 3.1, 4.1)


def test_swap_quando_armazenado_invertido_vs_mando():
    # stored-home = argentina, mas o JOGO tem home=brazil → precisa inverter 1X2
    odds = _odds(_cand(ch="argentina"))
    close_1x2, close_ou, open_1x2, open_ou = _find_odds(odds, "brazil", "argentina", "2022-12-18")
    # brazil é o mando: deve receber a odd que estava armazenada como 'away' (oa=4.0)
    assert close_1x2 == (4.0, 3.0, 2.0)
    assert open_1x2 == (4.1, 3.1, 2.1)


def test_home_recebe_sempre_a_propria_odd_independente_da_orientacao():
    # a invariante central: a odd do mando é a MESMA das duas formas de consultar
    odds = _odds(_cand(ch="argentina"))
    arg_home, *_ = _find_odds(odds, "argentina", "brazil", "2022-12-18")
    bra_home, *_ = _find_odds(odds, "brazil", "argentina", "2022-12-18")
    # argentina como mando → 2.0 ; brazil como mando → 4.0 (sua odd armazenada como 'away')
    assert arg_home[0] == 2.0
    assert bra_home[0] == 4.0


# ------------------------------------------------ Over/Under NÃO é orientado
def test_over_under_independe_da_orientacao():
    odds = _odds(_cand(oov=1.8, oun=2.1, oov_o=1.85, oun_o=2.15))
    _, ou_a, _, ou_open_a = _find_odds(odds, "argentina", "brazil", "2022-12-18")
    _, ou_b, _, ou_open_b = _find_odds(odds, "brazil", "argentina", "2022-12-18")
    assert ou_a == ou_b == (1.8, 2.1)          # OU é simétrico — swap não pode mexer
    assert ou_open_a == ou_open_b == (1.85, 2.15)


# --------------------------------------------------- tolerância de data
def test_data_dentro_da_tolerancia_de_3_dias_casa():
    odds = _odds(_cand(od_date="2022-12-18"))
    assert _find_odds(odds, "argentina", "brazil", "2022-12-21") is not None  # dd=3, ok


def test_data_fora_da_tolerancia_nao_casa():
    odds = _odds(_cand(od_date="2022-12-18"))
    assert _find_odds(odds, "argentina", "brazil", "2022-12-25") is None      # dd=7, fora


def test_escolhe_candidato_de_data_mais_proxima():
    perto = _cand(od_date="2022-12-18", oh=2.0)
    longe = _cand(od_date="2022-12-16", oh=9.0)
    odds = _odds(longe, perto)                  # ordem proposital: o mais perto vem depois
    close_1x2, *_ = _find_odds(odds, "argentina", "brazil", "2022-12-18")
    assert close_1x2[0] == 2.0                  # dd=0 vence dd=2


# --------------------------------------------------- sem casamento
def test_par_inexistente_devolve_none():
    odds = _odds(_cand())
    assert _find_odds(odds, "france", "england", "2022-12-18") is None


def test_data_malformada_no_candidato_e_ignorada_sem_estourar():
    odds = _odds(_cand(od_date="data-ruim"))
    assert _find_odds(odds, "argentina", "brazil", "2022-12-18") is None


# --------------------------------------------------- _canon (reconciliação de nomes)
def test_canon_aplica_alias():
    assert _canon("South Korea") == "korea republic"
    assert _canon("United States") == "usa"
    assert _canon("Czechia") == "czech republic"


def test_canon_reconcilia_bosnia_e_comercial():
    # Sofascore usa 'Bosnia & Herzegovina'; a base (martj42) usa '... and ...'.
    # Sem o alias o confronto orfanava e a aposta sumia do CLV calada.
    assert _canon("Bosnia & Herzegovina") == _canon("Bosnia and Herzegovina")


def test_canon_normaliza_caixa_e_espaco():
    assert _canon("  Brazil  ") == "brazil"
    assert _canon("ARGENTINA") == "argentina"


def test_canon_passthrough_sem_alias():
    assert _canon("Portugal") == "portugal"
