"""predictor-core.testing.prequential — motor walk-forward via Template Method (Onda 2, v1.3.0).

Promoção do padrão prequential ("predictive sequential": treinar até t, prever
t+1, avançar) que CS, LoL e F1 reimplementavam com calendários diferentes. O
perigo de promover como FUNÇÃO rígida é engessar o ritmo de cada esporte; a
solução é o Template Method: o core é uma ABC que controla o FATIAMENTO
TEMPORAL (a parte onde vaza dado se errar), e o consumidor herda implementando
`train_step`/`predict_step` (a parte de domínio que o core nunca vê).

Garantia estrutural anti-leakage: `train_step` recebe SOMENTE observações com
índice < corte; `predict_step` recebe a observação do corte SEM o resultado
(o campo `target_key` é removido do dict antes de entregar). O consumidor não
tem como treinar no futuro nem espiar o resultado — não por disciplina, por
construção (mesmo espírito do replay.PastView)."""
from __future__ import annotations

import abc

__all__ = ["PrequentialEvaluator"]


class PrequentialEvaluator(abc.ABC):
    """ABC do walk-forward puro. Herde e implemente os dois hooks:

    class MeuAvaliador(PrequentialEvaluator):
        def train_step(self, history):    # history: list[dict], só o passado
            self.model = fit(history)
        def predict_step(self, features): # features: dict SEM o target
            return self.model.predict(features)

    result = MeuAvaliador(target_key="outcome").run(observations, min_history=30)
    # → lista de {"index", "prediction", "actual"} pareados p/ brier/rps/DM.

    `observations` deve vir ORDENADO no tempo (responsabilidade do consumidor —
    o core não conhece o campo de data do domínio; se houver dúvida, ordene por
    published_at antes de chamar)."""

    def __init__(self, *, target_key: str):
        if not target_key:
            raise ValueError("target_key é obrigatório — é o campo blindado do leakage")
        self.target_key = target_key

    @abc.abstractmethod
    def train_step(self, history: list) -> None:
        """Treina/atualiza o modelo com `history` (observações estritamente
        anteriores ao ponto de previsão, COM os targets)."""

    @abc.abstractmethod
    def predict_step(self, features: dict) -> object:
        """Prevê a observação corrente. `features` NÃO contém `target_key` —
        o core o removeu antes de chamar."""

    def run(self, observations: list, *, min_history: int = 1,
            retrain_every: int = 1) -> list:
        """Executa o walk-forward e retorna as previsões pareadas com o realizado.

        min_history: nº mínimo de observações antes da primeira previsão.
        retrain_every: chama train_step a cada k passos (k>1 amortiza treino
        caro; a previsão continua passo a passo). Cada item do retorno:
        {"index": i, "prediction": ..., "actual": observations[i][target_key]}."""
        if min_history < 1:
            raise ValueError("min_history >= 1 (prever sem passado nenhum não é avaliação)")
        if retrain_every < 1:
            raise ValueError("retrain_every >= 1")
        results = []
        steps_since_train = None
        for i in range(min_history, len(observations)):
            obs = observations[i]
            if self.target_key not in obs:
                raise KeyError(
                    f"observação [{i}] sem o campo target '{self.target_key}' — "
                    "sem realizado não há avaliação prequential")
            if steps_since_train is None or steps_since_train >= retrain_every:
                self.train_step(list(observations[:i]))
                steps_since_train = 0
            features = {k: v for k, v in obs.items() if k != self.target_key}
            prediction = self.predict_step(features)
            results.append({"index": i, "prediction": prediction,
                            "actual": obs[self.target_key]})
            steps_since_train += 1
        return results
