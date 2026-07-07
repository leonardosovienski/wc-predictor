"""Onda 5 — drift-check automático do vendor na suíte da Copa.

O wc-predictor-v2 passou a consumir o predictor_core via vendor (Onda 5, desparkado:
a coleta é independente da análise; o dado fica congelado no SQLite). Este teste valida
a integridade dos arquivos vendorizados contra o CORE_MANIFEST.json — adulteração local,
dessincronia ou órfão viram falha de pytest. Puro file-hash (não importa predictor_core),
então roda sem depender do sys.path do vendor.
"""
import hashlib
import json
from pathlib import Path

import pytest

VENDOR = Path(__file__).resolve().parents[1] / "vendor" / "predictor_core"
MANIFEST = VENDOR / "CORE_MANIFEST.json"


def _iter_payload(root: Path):
    for p in root.rglob("*"):
        if not p.is_file() or "__pycache__" in p.parts:
            continue
        if p.suffix == ".py" or p.name == "VERSION":
            yield p


@pytest.mark.skipif(not VENDOR.is_dir(), reason="domínio sem vendor/predictor_core/")
def test_vendor_manifest_present():
    assert MANIFEST.exists(), (
        "vendor/predictor_core/CORE_MANIFEST.json ausente — rode `sync_core.py --write`")


@pytest.mark.skipif(not MANIFEST.exists(), reason="manifesto ausente (coberto por outro teste)")
def test_each_file_hash_matches_manifest():
    files = json.loads(MANIFEST.read_text(encoding="utf-8"))["files"]
    for rel, expected in files.items():
        f = VENDOR / rel
        assert f.exists(), f"arquivo do manifesto ausente no vendor: {rel}"
        got = hashlib.sha256(f.read_bytes()).hexdigest()
        assert got == expected, (
            f"DRIFT em {rel}: sha256 {got[:12]} != manifesto {expected[:12]} — "
            "NUNCA edite vendor/predictor_core/ à mão; corrija no canônico e rode o sync.")


@pytest.mark.skipif(not MANIFEST.exists(), reason="manifesto ausente")
def test_no_orphan_files_in_vendor():
    declared = set(json.loads(MANIFEST.read_text(encoding="utf-8"))["files"])
    present = {p.relative_to(VENDOR).as_posix() for p in _iter_payload(VENDOR)}
    assert present == declared, (
        f"árvore do vendor diverge do manifesto: "
        f"só no vendor={present - declared}, só no manifesto={declared - present}")


@pytest.mark.skipif(not MANIFEST.exists(), reason="manifesto ausente")
def test_aggregate_reproduces():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    recomputed = hashlib.sha256(
        json.dumps(manifest["files"], sort_keys=True).encode()).hexdigest()[:16]
    assert recomputed == manifest["aggregate"]
