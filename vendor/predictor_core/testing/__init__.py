"""predictor_core.testing — harness de validação da RÉGUA por propriedade mecânica.

Distribuído no payload (os domínios usam nas próprias suítes para provar que seus
pipelines de avaliação têm poder). Três peças:
  synth    — geradores de séries sintéticas onde a VERDADE é conhecida (média, edge,
             autocorrelação AR(1), previsor probabilístico calibrável).
  coverage — teste de cobertura de IC: um IC 95% deve cobrir a verdade em 95%±tol das
             simulações. Um bootstrap com a geometria de blocos errada FALHA aqui.
  harness  — controle positivo: um pipeline deve DETECTAR edge sintético (sensibilidade)
             e REJEITAR ruído (especificidade). Sem isso, um NO-GO é ininterpretável.

stdlib-first: zero numpy (o princípio do core > a conveniência). Séries são list[float];
a aleatoriedade vem de random.Random(seed) — determinística e reprodutível.
"""
