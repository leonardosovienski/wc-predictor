"""predictor-core.kernel.rating — motor de ratings generalizado (trueskill-like).

Motivação (masterplan de agosto/2026): CS, LoL, F1 e NBA precisam do MESMO
padrão matemático — "cada `Entity` tem uma força latente; um `Context`
(partida/corrida) observa um resultado ORDENADO entre entidades e atualiza as
forças" — mas cada domínio reimplementava seu próprio Elo com convenções
diferentes de K-factor e de agregação de time. Este módulo abstrai a interface
(`Entity`, `Context`, `Aggregation`) sobre o Elo clássico de 2 jogadores E sobre
resultados multi-entidade (corridas, ranqueamentos de N).

Zero dependências externas. Não é TrueSkill bayesiano completo (isso exigiria
inferência gaussiana correlacionada) — é Elo generalizado com expectativa
pairwise, suficiente para o pedágio estatístico do core; o domínio decide se
precisa de algo mais rico."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

__all__ = ["Entity", "expected_score", "update_pair", "RatingBook"]

_DEFAULT_RATING = 1500.0
_DEFAULT_K = 32.0
_SCALE = 400.0  # base-10 logística padrão do Elo


@dataclass(frozen=True)
class Entity:
    """Snapshot imutável do rating de uma entidade (jogador/time/piloto) em um instante.

    `rating` é a força latente na escala Elo (1500 = média convencional).
    `games` conta atualizações sofridas — usado por esquemas de K-factor
    dinâmico (ex.: K maior enquanto `games` é baixo, "provisional")."""

    name: str
    rating: float = _DEFAULT_RATING
    games: int = 0


def expected_score(rating_a: float, rating_b: float, *, scale: float = _SCALE) -> float:
    """P(A vence B) sob o modelo logístico Elo, dado as forças latentes.

    Simétrico: expected_score(a, b) + expected_score(b, a) == 1."""
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / scale))


def update_pair(rating_a: float, rating_b: float, score_a: float, *,
                k: float = _DEFAULT_K, scale: float = _SCALE) -> tuple:
    """Atualização Elo de um confronto par-a-par.

    `score_a`: resultado realizado da perspectiva de A ∈ {0, 0.5, 1} (derrota,
    empate, vitória) — mas aceita qualquer valor em [0,1] para agregações
    (ex.: fração de rounds vencidos em CS). Retorna (nova_rating_a, nova_rating_b);
    a soma dos deltas é sempre zero (o rating é um jogo de soma-zero, como o
    Ledger é uma partida dobrada)."""
    if not (0.0 <= score_a <= 1.0):
        raise ValueError(f"score_a fora de [0,1]: {score_a!r}")
    exp_a = expected_score(rating_a, rating_b, scale=scale)
    delta = k * (score_a - exp_a)
    return rating_a + delta, rating_b - delta


@dataclass
class RatingBook:
    """Fachada com estado: dict `name -> Entity` + histórico de atualizações.

    book = RatingBook()
    book.record_match("messi", "mbappe", score_a=1.0)   # messi venceu
    book.rating("messi")  # força atual

    `k_factor`: callback opcional `(Entity) -> float` para K dinâmico (ex.:
    K=40 enquanto games<30, K=20 depois) — se None, usa `k` fixo do construtor."""

    default_rating: float = _DEFAULT_RATING
    k: float = _DEFAULT_K
    scale: float = _SCALE
    k_factor: object = None
    _entities: dict = field(default_factory=dict)

    def get(self, name: str) -> Entity:
        return self._entities.setdefault(name, Entity(name=name, rating=self.default_rating))

    def rating(self, name: str) -> float:
        return self.get(name).rating

    def _k_for(self, entity: Entity) -> float:
        return self.k_factor(entity) if self.k_factor is not None else self.k

    def record_match(self, name_a: str, name_b: str, *, score_a: float) -> tuple:
        """Registra um confronto par-a-par e retorna (Entity_a, Entity_b) atualizados."""
        ea, eb = self.get(name_a), self.get(name_b)
        k = max(self._k_for(ea), self._k_for(eb))
        new_a, new_b = update_pair(ea.rating, eb.rating, score_a, k=k, scale=self.scale)
        ea2 = Entity(name=name_a, rating=new_a, games=ea.games + 1)
        eb2 = Entity(name=name_b, rating=new_b, games=eb.games + 1)
        self._entities[name_a] = ea2
        self._entities[name_b] = eb2
        return ea2, eb2

    def record_ranking(self, ranking: list) -> list:
        """Resultado multi-entidade (ex.: N pilotos de uma corrida), melhor→pior.

        Decompõe em todos os pares (i, j) com i antes de j na `ranking` como uma
        vitória de i sobre j, e aplica `record_match` para cada par com K
        dividido por (N-1) — evita que uma corrida de N pilotos mova o rating
        N-1x mais que um confronto 1x1. Retorna a lista de `Entity` atualizados
        na ordem de `ranking`."""
        n = len(ranking)
        if n < 2:
            raise ValueError("record_ranking exige >= 2 entidades")
        base_k = self.k
        try:
            self.k = base_k / (n - 1)
            for i in range(n):
                for j in range(i + 1, n):
                    self.record_match(ranking[i], ranking[j], score_a=1.0)
        finally:
            self.k = base_k
        return [self.get(name) for name in ranking]
