"""Higiene do repositório — guarda contra o bug da classe "clone quebrado".

Portado do previsao-cripto (incidente 2026-07-07 lá; encontrado VIVO aqui em
2026-07-09): a regra não-ancorada `data/` no .gitignore engolia o PACOTE
vendor/predictor_core/data/ (código, não dados) — 7 arquivos .py declarados no
CORE_MANIFEST estavam presentes no disco mas invisíveis ao git. A suíte passava
na máquina do dono e qualquer clone fresco quebraria. Este módulo fecha a
lacuna: todo .py importável do projeto precisa estar VISÍVEL ao git
(não-ignorado), e todo arquivo do manifesto do vendor precisa estar rastreado.

O mesmo padrão já mordeu este repo de outro jeito: o merge da consolidação
(2026-07-07) apagou data/predictions.jsonl do disco porque git trata ignorado
como descartável na troca de branch. data/ na RAIZ segue não-versionado por
decisão (produção read-only) — a regra agora é ancorada (`/data/`).

Usa `git check-ignore` (barato, offline). Sem git/.git os testes são pulados.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

_git = shutil.which("git")
_is_repo = (ROOT / ".git").exists()

pytestmark = pytest.mark.skipif(
    not (_git and _is_repo), reason="git indisponível ou fora de um clone")


def _python_payload() -> list[Path]:
    """Todos os .py dos pacotes de código do projeto (fora de venvs/caches)."""
    files = []
    for pkg in ("src", "scripts", "tests", "vendor"):
        base = ROOT / pkg
        if not base.is_dir():
            continue
        for p in base.rglob("*.py"):
            parts = p.parts
            if "__pycache__" in parts or ".venv" in parts or "env" in parts:
                continue
            files.append(p)
    return files


def test_no_code_file_is_gitignored():
    """Nenhum .py de pacote de código pode casar com regra do .gitignore.

    `git check-ignore` sai 0 quando ALGUM caminho passado está ignorado e
    imprime quais — a asserção mostra a lista exata para o diagnóstico.
    """
    files = _python_payload()
    assert files, "payload vazio — layout do repositório mudou?"
    rels = [str(p.relative_to(ROOT)) for p in files]
    # Em lotes, para não estourar o limite de linha de comando do Windows.
    ignored: list[str] = []
    for i in range(0, len(rels), 100):
        proc = subprocess.run(
            [_git, "-C", str(ROOT), "check-ignore", *rels[i:i + 100]],
            capture_output=True, text=True)
        if proc.returncode == 0:
            ignored.extend(proc.stdout.splitlines())
    assert not ignored, (
        "arquivos de CÓDIGO ignorados pelo .gitignore (clone fresco quebraria): "
        f"{ignored} — ancore a regra (ex.: '/data/' em vez de 'data/')")


def test_vendor_manifest_files_are_tracked():
    """Todo arquivo do CORE_MANIFEST está rastreado pelo git (não só presente).

    Presente-mas-untracked foi exatamente o modo de falha do incidente: a
    suíte local passa e o clone quebra. `git ls-files` é a verdade do índice.
    """
    manifest = ROOT / "vendor" / "predictor_core" / "CORE_MANIFEST.json"
    if not manifest.exists():
        pytest.skip("sem manifesto do vendor")
    declared = json.loads(manifest.read_text(encoding="utf-8"))["files"]
    proc = subprocess.run(
        [_git, "-C", str(ROOT), "ls-files", "vendor/predictor_core"],
        capture_output=True, text=True, check=True)
    tracked = set(proc.stdout.splitlines())
    missing = [f"vendor/predictor_core/{rel}" for rel in declared
               if f"vendor/predictor_core/{rel}" not in tracked]
    assert not missing, (
        f"arquivos do manifesto NÃO rastreados pelo git: {missing} — "
        "commite-os (um clone fresco não os terá)")
