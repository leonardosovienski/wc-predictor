"""Regressão W5 (auditoria 2026-07-09): o consenso do odds_shop incluía casas
com last_update congelado — o melhor preço via max() podia ser um feed morto
que o operador não consegue executar. O filtro de frescor (max_stale_s)
descarta essas casas; None desliga (modo --from-file, onde o snapshot inteiro
é velho por definição).
"""
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

_spec = importlib.util.spec_from_file_location(
    "odds_shop", ROOT / "scripts" / "odds_shop.py")
odds_shop = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_spec and odds_shop)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _event(now):
    fresh = _iso(now - timedelta(minutes=2))
    stale = _iso(now - timedelta(hours=3))
    mk = lambda over, under: [{"key": "totals", "outcomes": [
        {"name": "Over", "price": over, "point": 2.5},
        {"name": "Under", "price": under, "point": 2.5}]}]
    return {"bookmakers": [
        {"key": "viva", "title": "CasaViva", "last_update": fresh,
         "markets": mk(1.90, 1.90)},
        # feed morto com o "melhor" preço do under — a isca do W5
        {"key": "morta", "title": "CasaMorta", "last_update": stale,
         "markets": mk(1.80, 2.50)},
        {"key": "semdata", "title": "CasaSemData",
         "markets": mk(1.95, 1.85)},
    ]}


def test_filtro_descarta_feed_morto():
    now = datetime.now(timezone.utc)
    c = odds_shop.consensus(_event(now), "totals", point=2.5,
                            max_stale_s=15 * 60)
    # melhor under vem da casa viva (1.90), não da morta (2.50)
    assert c["Under"]["best"][0] == 1.90
    assert c["Under"]["best"][1] == "CasaViva"
    # casa sem last_update é mantida (não dá pra julgar)
    assert c["Under"]["n_books"] == 2


def test_none_desliga_o_filtro():
    now = datetime.now(timezone.utc)
    c = odds_shop.consensus(_event(now), "totals", point=2.5, max_stale_s=None)
    assert c["Under"]["best"] == (2.50, "CasaMorta")
    assert c["Under"]["n_books"] == 3


def test_last_update_ilegivel_nao_trava():
    ev = _event(datetime.now(timezone.utc))
    ev["bookmakers"][0]["last_update"] = "ontem de manhã"
    c = odds_shop.consensus(ev, "totals", point=2.5, max_stale_s=15 * 60)
    assert c["Under"]["n_books"] == 2   # ilegível = mantida; morta = fora
