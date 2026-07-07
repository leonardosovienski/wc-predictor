"""Blindagem de regressao — CI minima local (auditoria 2026-07-02).

Roda as barreiras que impedem a reintroducao dos bugs corrigidos:
  1. pytest — a suite inteira (173+ testes) tem que passar.
  2. Pesquisa somente-leitura (P12) — nenhum modulo de pesquisa pode abrir o
     banco em modo escrita (db.connect sem read_only=True / sqlite sem mode=ro).
  3. Elo forward-only (P3) — current_elo/load_elo so em modulos de SERVING.
     Pesquisa usa ratings.ratings_asof. Excecoes conhecidas (divida da v3,
     ver docs/V3_READINESS.md) geram WARN, nao FAIL — mas nenhuma NOVA entra.
  4. Smoke test do predict — o caminho de serving produz um 1X2 que soma ~100%.
     (pulado com aviso se data/matches.db nao existir — ex.: checkout limpo)
  5. Smoke test do live prediction (--segundo-tempo) — mesmo caminho de codigo
     que o item 4 nao exercita (auditoria 2026-07-07: era o unico fluxo de
     previsao do sistema sem cobertura de CI).

Uso:
    python scripts/ci_check.py            # tudo
    python scripts/ci_check.py --fast     # pula o pytest (so as barreiras estaticas)

Como hook de pre-commit (opcional), crie .git/hooks/pre-commit com:
    #!/bin/sh
    .venv/Scripts/python.exe scripts/ci_check.py --fast || exit 1
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _smoke_env() -> dict:
    """Ambiente pros smoke tests: predições de teste NÃO entram no log de
    produção. Sem isto cada rodada do CI gravava um 'Brazil x France' falso em
    data/predictions.jsonl (achado 2026-07-07: 18 linhas de lixo acumuladas —
    o log é a janela out-of-sample da Copa, poluí-lo distorce a avaliação)."""
    env = dict(os.environ)
    env["PREDICTIONS_LOG_PATH"] = str(Path(tempfile.gettempdir()) / "ci_smoke_predictions.jsonl")
    return env

# Modulos de PESQUISA: banco estritamente somente-leitura (P12).
RESEARCH_DB_FILES = [
    "src/backtest_event.py",
    "src/diagnose_event_data.py",
    "src/check_coverage.py",
    "src/research/verify_calibration.py",
    "src/research/test_combinations.py",
    "src/research/vorp_ridge.py",
    "src/research/survival_test.py",
]

# Modulos de SERVING: unicos autorizados a tocar current_elo/load_elo.
SERVING_ALLOWLIST = {
    "src/db.py",                  # definicao do schema e load/save
    "src/cron_update_models.py",  # unico ESCRITOR do cache
    "src/predict.py",             # leitor de serving
    "src/simulator.py",           # leitor de serving
    "src/status.py",              # painel (leitura de contagens)
    "src/kernel_daemon.py",       # daemon de serving (v3)
}

# Divida conhecida da v3 (lookahead documentado): WARN, nao FAIL.
# Remover daqui quando forem migrados para ratings_asof — nunca ampliar.
KNOWN_DEBT = {
    "src/research/vorp_ridge.py",
    "src/research/survival_test.py",
}

failures: list[str] = []
warnings_: list[str] = []


def _rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def check_pytest() -> None:
    print("[1/5] pytest (suite completa)...")
    r = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q"],
                       cwd=ROOT, capture_output=True, text=True)
    tail = (r.stdout or "").strip().splitlines()[-1:] or ["(sem saida)"]
    print(f"      {tail[0]}")
    if r.returncode != 0:
        failures.append(f"pytest falhou (exit {r.returncode}) — rode: python -m pytest tests/")


def check_research_readonly() -> None:
    print("[2/5] pesquisa somente-leitura (P12)...")
    # janela de 200 chars apos cada chamada: argumentos podem conter parenteses
    # aninhados (str(db_path)), entao regex ate o 1o ')' nao serve
    for rel in RESEARCH_DB_FILES:
        f = ROOT / rel
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"db\.connect\s*\(", text):
            window = text[m.start():m.start() + 200]
            if "read_only=True" not in window:
                failures.append(f"{rel}: db.connect sem read_only=True — pesquisa "
                                f"nao pode abrir o banco em modo escrita")
        # sqlite3.connect direto: exige URI mode=ro no mesmo arquivo
        if "sqlite3.connect" in text and "mode=ro" not in text:
            failures.append(f"{rel}: sqlite3.connect sem mode=ro")
    # feature_builder conecta via sqlite3 puro — precisa do mode=ro
    fb = ROOT / "src" / "feature_builder.py"
    if fb.exists() and "mode=ro" not in fb.read_text(encoding="utf-8", errors="replace"):
        failures.append("src/feature_builder.py: conexao sem mode=ro (P12 regrediu)")
    print(f"      {len(RESEARCH_DB_FILES)} modulos verificados")


def check_current_elo_containment() -> None:
    print("[3/5] current_elo/load_elo contido no serving (P3)...")
    # USO real, nao mencao em prosa: chamada db.load_elo(...) ou SQL que toca a
    # tabela current_elo. Docstrings dos fixes citam 'current_elo' como
    # historico — isso nao pode disparar o alarme.
    usage = re.compile(
        r"load_elo\s*\(|FROM\s+current_elo|INTO\s+current_elo|"
        r"TABLE\s+current_elo|UPDATE\s+current_elo|DELETE\s+FROM\s+current_elo",
        re.IGNORECASE)
    n = 0
    for f in sorted((ROOT / "src").rglob("*.py")):
        rel = _rel(f)
        text = f.read_text(encoding="utf-8", errors="replace")
        if "current_elo" not in text and "load_elo" not in text:
            continue
        n += 1
        if rel in SERVING_ALLOWLIST:
            continue
        code_hits = [ln for ln in text.splitlines()
                     if usage.search(ln) and not ln.lstrip().startswith("#")]
        if not code_hits:
            continue
        if rel in KNOWN_DEBT:
            warnings_.append(f"{rel}: usa current_elo/load_elo (divida v3 conhecida "
                             f"— corrigir com ratings_asof antes de usar em conclusao)")
        else:
            failures.append(f"{rel}: current_elo/load_elo fora do serving — "
                            f"lookahead; use ratings.ratings_asof")
    print(f"      {n} arquivos com mencao inspecionados")


def check_predict_smoke() -> None:
    print("[4/5] smoke test do predict...")
    if not (ROOT / "data" / "matches.db").exists():
        warnings_.append("smoke do predict PULADO: data/matches.db ausente")
        print("      PULADO (sem banco)")
        return
    # --json em vez de regex sobre texto formatado (Fase 2 do redesign de
    # output): o smoke test agora le o mesmo dict estruturado que
    # src/display.py produz, sem depender de uma substring de exibicao que
    # pode mudar de layout a qualquer reformulacao futura do terminal.
    r = subprocess.run([sys.executable, "-X", "utf8", "-m", "src.predict",
                        "Brazil", "France", "--neutral", "--json"],
                       cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=_smoke_env())
    out = r.stdout or ""
    if r.returncode != 0:
        failures.append(f"predict saiu com exit {r.returncode}: {(r.stderr or '')[-200:]}")
        return
    try:
        data = json.loads(out)
        core = data["core"]
        p_win, p_draw, p_loss = core["p_win"], core["p_draw"], core["p_loss"]
    except (ValueError, KeyError) as e:
        failures.append(f"predict --json nao produziu o dict esperado ({e})")
        return
    total = (p_win + p_draw + p_loss) * 100
    if not 99.0 <= total <= 101.0:
        failures.append(f"probabilidades 1X2 somam {total:.1f}% (esperado ~100%) — "
                        f"possivel regressao do P5 (max_goals/delta_vorp)")
    print(f"      1X2 = {p_win:.1%} / {p_draw:.1%} / {p_loss:.1%} (soma {total:.1f}%)")


def _check_live_flag(flag: str, extra_args: list[str], result_key: str) -> None:
    """Roda `prever.py <flag> --json` e valida que p_win+p_draw+p_loss de
    `result_key` (p.ex. 'final' pro --segundo-tempo, 'period' pro
    --primeiro-tempo) soma ~100%."""
    r = subprocess.run([sys.executable, "-X", "utf8", "scripts/prever.py",
                        "Brazil", "France", *extra_args, "--json"],
                       cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=_smoke_env())
    out = r.stdout or ""
    if r.returncode != 0:
        failures.append(f"prever.py {flag} saiu com exit {r.returncode}: "
                        f"{(r.stderr or '')[-200:]}")
        return
    try:
        data = json.loads(out)
        block = data[result_key]
        p_win, p_draw, p_loss = block["p_win"], block["p_draw"], block["p_loss"]
    except (ValueError, KeyError) as e:
        failures.append(f"prever.py {flag} --json nao produziu o dict esperado "
                        f"({e}) — schema de compute_live() mudou?")
        return
    total = (p_win + p_draw + p_loss) * 100
    if not 99.0 <= total <= 101.0:
        failures.append(f"{flag}: p_win+p_draw+p_loss ({result_key}) = {total:.1f}% "
                        f"(esperado ~100%) — possivel regressao do compute_live")
    print(f"      {flag} ({result_key}) = {p_win:.1%} / {p_draw:.1%} / {p_loss:.1%} "
         f"(soma {total:.1f}%)")


def check_live_smoke() -> None:
    print("[5/5] smoke test do live prediction (--segundo-tempo / --primeiro-tempo)...")
    if not (ROOT / "data" / "matches.db").exists():
        warnings_.append("smoke do live prediction PULADO: data/matches.db ausente")
        print("      PULADO (sem banco)")
        return
    _check_live_flag("--segundo-tempo", ["--segundo-tempo", "0-0"], "final")
    _check_live_flag("--primeiro-tempo", ["--primeiro-tempo"], "period")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="pula o pytest")
    args = ap.parse_args()

    if not args.fast:
        check_pytest()
    else:
        print("[1/5] pytest PULADO (--fast)")
    check_research_readonly()
    check_current_elo_containment()
    check_predict_smoke()
    check_live_smoke()

    print()
    for w in warnings_:
        print(f"WARN: {w}")
    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        print(f"\nCI: {len(failures)} falha(s) — commit bloqueado.")
        return 1
    print("CI: todas as barreiras verdes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
