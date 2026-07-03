"""Garante que `import src.*` funcione rodando o pytest da raiz do projeto.
Sem .venv (abandonada na Batalha 2), o pacote src é resolvido pela raiz do repo."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Onda 5: a Copa consome o predictor_core via vendor/ — no path dos testes.
_vendor = ROOT / "vendor"
if _vendor.is_dir() and str(_vendor) not in sys.path:
    sys.path.insert(0, str(_vendor))
