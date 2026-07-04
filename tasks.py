#!/usr/bin/env python
"""Atalhos dos comandos do projeto — em Python puro (não precisa de `make`).

Uso:  python tasks.py <alvo> [args...]
      python tasks.py              # lista os alvos
Exemplos:
      python tasks.py ingest
      python tasks.py predict Portugal Spain --neutral
      python tasks.py simulate 50000
      python tasks.py seasons 16
"""
import subprocess
import sys

PY = sys.executable  # o mesmo interpretador que rodou este script

# alvo -> (comando base, descrição). args extras da CLI são anexados ao comando.
TASKS = {
    "install":     (["-m", "pip", "install", "-r", "requirements.txt"], "Deps de runtime"),
    "install-dev": (["-m", "pip", "install", "-r", "requirements-dev.txt"], "Deps de dev (pytest)"),
    "ingest":      (["-m", "src.ingest"], "Baixa ~49k jogos (martj42) -> SQLite"),
    "sofascore":   (["-m", "src.ingest_sofascore"], "Coleta odds/xG/notas (rede limpa)"),
    "seasons":     (["-m", "src.ingest_sofascore", "--seasons"], "Descobre season_id — ex: tasks.py seasons 16"),
    "fbref":       (["-m", "src.ingest_fbref"], "Coleta stats de jogador (FBref)"),
    "cron":        (["-m", "src.cron_update_models"], "Elo + calibra params -> cache (após cada ingest)"),
    "predict":     (["-m", "src.predict"], "Prevê — ex: tasks.py predict Brazil France --neutral"),
    "fixtures":    (["-m", "src.predict", "--fixtures"], "Próximos N fixtures — ex: tasks.py fixtures 8"),
    "rankings":    (["-m", "src.predict", "--rankings"], "Top N do Elo — ex: tasks.py rankings 20"),
    "simulate":    (["-m", "src.simulator"], "Monte Carlo da Copa — ex: tasks.py simulate 10000"),
    "backtest":    (["-m", "src.backtest"], "P&L + CLV vs odds"),
    "bootstrap":   (["-m", "src.bootstrap"], "IC 95% do ROI e do CLV (após backtest)"),
    "status":      (["-m", "src.status"], "Painel do estado do banco"),
    "test":        (["-m", "pytest", "tests/", "-q"], "Roda a suíte de testes"),
}


def usage():
    print(__doc__)
    print("Alvos:")
    for name, (_, desc) in TASKS.items():
        print(f"  {name:12} {desc}")


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        usage()
        return 0
    target, extra = argv[0], argv[1:]
    if target not in TASKS:
        print(f"alvo desconhecido: {target}\n", file=sys.stderr)
        usage()
        return 2
    base, _ = TASKS[target]
    return subprocess.call([PY, *base, *extra])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
