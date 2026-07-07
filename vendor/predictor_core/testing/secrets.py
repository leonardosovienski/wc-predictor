"""secrets — guard contra vazamento de credenciais na telemetria.

A telemetria (`obs.emit_event`) grava `metadata` livre em JSONL. Um descuido — colocar
uma resposta de API, um header ou um token no metadata — vazaria um segredo num arquivo
que pode ser inspecionado ou commitado por engano. Este guard varre o JSONL (ou um texto)
procurando o que PARECE credencial e falha explícito, para barrar o vazamento antes do commit.

Duas frentes:
  - padrões de PREFIXO conhecido (sk-, AIza, ghp_, ...) — alta confiança, baixo falso-positivo;
  - `known_values`: os VALORES reais dos segredos (do ambiente) — match verbatim, zero
    falso-positivo (a defesa mais forte: "algum segredo real aparece no texto?").
"""
from __future__ import annotations

import re
from pathlib import Path

# Prefixos de credenciais conhecidas (âncoras de alta confiança).
_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),            # OpenAI
    re.compile(r"AIza[0-9A-Za-z_\-]{35}"),         # Google / Gemini
    re.compile(r"ghp_[A-Za-z0-9]{36}"),            # GitHub PAT
    re.compile(r"gho_[A-Za-z0-9]{36}"),            # GitHub OAuth
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),   # Slack
    re.compile(r"AKIA[0-9A-Z]{16}"),               # AWS access key id
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}"),  # Authorization: Bearer
]

_MIN_KNOWN_LEN = 8   # valores curtos demais dariam falso-positivo (não são segredos reais)


def find_secrets(text: str, *, known_values=()) -> list[str]:
    """Trechos suspeitos de credencial em `text`. `known_values` = valores reais do
    ambiente (match verbatim). Retorna lista de achados (vazia = limpo)."""
    hits: list[str] = []
    for pat in _SECRET_PATTERNS:
        hits += pat.findall(text)
    for v in known_values:
        if v and len(v) >= _MIN_KNOWN_LEN and v in text:
            hits.append(f"<known-secret:{v[:4]}...>")
    return hits


def assert_no_secrets_in_events(path, *, known_values=()) -> None:
    """Levanta AssertionError se o JSONL de telemetria em `path` contiver algo que
    pareça credencial. Ausência do arquivo = nada a vazar (no-op). Use nas suítes dos
    domínios para transformar um vazamento acidental em falha de `pytest`."""
    p = Path(path)
    if not p.exists():
        return
    hits = find_secrets(p.read_text(encoding="utf-8"), known_values=known_values)
    assert not hits, (
        f"POSSÍVEL VAZAMENTO de credencial na telemetria {p}: {sorted(set(hits))} — "
        "remova o segredo do metadata do emit_event (nunca logue tokens/respostas de API).")
