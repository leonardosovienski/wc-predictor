"""harness — controle positivo: um veredito só é interpretável se o pipeline tem PODER.

Um pipeline de avaliação que devolve NO-GO pode estar certo (não há edge) OU cego (não
detectaria edge nenhum). O controle positivo distingue os dois: injeta um edge sintético
e exige detecção (sensibilidade), depois injeta ruído e exige rejeição (especificidade).
Sem passar nos dois, nenhum GO/NO-GO do pipeline significa coisa alguma.

Integração com o Experiment Registry (2026-07-09): `attest_pipeline_power` roda o
controle positivo E emite um ATESTADO em arquivo — o que `measurement.trials.
register_trial` exige para aceitar uma trial NOVA. Arquivo (não flag em memória)
porque o harness roda na suíte e o registro roda no pipeline: processos distintos.
"""
import json
from datetime import datetime, timezone
from pathlib import Path


class PipelineHasNoPowerError(AssertionError):
    """O pipeline de avaliação falhou o controle positivo — seus vereditos são
    ininterpretáveis até isto ser corrigido."""


def assert_pipeline_has_power(evaluate_func, edge_generator, noise_generator,
                              *, edge_verdict: str = "COMPROVADA",
                              null_verdict: str = "REFUTADA") -> bool:
    """Valida que `evaluate_func` detecta edge e rejeita ruído.

    evaluate_func(series) -> dict com chave 'verdict'.
    edge_generator()  -> série COM edge (deve produzir `edge_verdict`).
    noise_generator() -> série SEM edge (NÃO pode produzir `edge_verdict`).

    Levanta PipelineHasNoPowerError se: (a) o edge não for detectado — falso negativo,
    o pipeline é cego; ou (b) o ruído for confirmado — falso positivo, o pipeline
    fabrica significância. Retorna True se ambos os braços passarem."""
    v_edge = evaluate_func(edge_generator())
    got_edge = v_edge.get("verdict")
    if got_edge != edge_verdict:
        raise PipelineHasNoPowerError(
            f"SENSIBILIDADE falhou: edge sintético não detectado "
            f"(verdict={got_edge!r}, esperado {edge_verdict!r}) — pipeline cego.")

    v_noise = evaluate_func(noise_generator())
    got_noise = v_noise.get("verdict")
    if got_noise == edge_verdict:
        raise PipelineHasNoPowerError(
            f"ESPECIFICIDADE falhou: ruído confirmado como edge "
            f"(verdict={got_noise!r}) — pipeline fabrica significância.")
    return True


def attest_pipeline_power(evaluate_func, edge_generator, noise_generator,
                          *, attestation_path: Path | str, note: str = "",
                          edge_verdict: str = "COMPROVADA",
                          null_verdict: str = "REFUTADA",
                          metric: str = "") -> dict:
    """Roda o controle positivo e, PASSANDO, emite o atestado que destrava a
    criação de trials novas no Experiment Registry (measurement.trials).

    `attestation_path`: onde gravar — use `trials.attestation_path_for(trials_json)`
    para o local canônico (irmão do trials.json). Falhando o controle, levanta
    PipelineHasNoPowerError e NÃO grava nada. Retorna o dict do atestado.

    `metric` (v1.3.0, punição global): nome da métrica que o pipeline atestado
    usa (ex.: "brier" para binário, "rps" para ordinal). Vai no atestado; o
    registry pode então exigir que a trial declare a MESMA métrica — um
    pipeline atestado com Brier não cobre vereditos emitidos com RPS."""
    assert_pipeline_has_power(evaluate_func, edge_generator, noise_generator,
                              edge_verdict=edge_verdict, null_verdict=null_verdict)
    record = {
        "passed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "evaluate": getattr(evaluate_func, "__name__", repr(evaluate_func)),
        "edge_verdict": edge_verdict,
        "note": note,
        "metric": metric,
    }
    ap = Path(attestation_path)
    ap.parent.mkdir(parents=True, exist_ok=True)
    ap.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                  encoding="utf-8")
    return record
