"""harness — controle positivo: um veredito só é interpretável se o pipeline tem PODER.

Um pipeline de avaliação que devolve NO-GO pode estar certo (não há edge) OU cego (não
detectaria edge nenhum). O controle positivo distingue os dois: injeta um edge sintético
e exige detecção (sensibilidade), depois injeta ruído e exige rejeição (especificidade).
Sem passar nos dois, nenhum GO/NO-GO do pipeline significa coisa alguma.
"""


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
