"""predictor-core.measurement.ledger — contabilidade de partidas dobradas (beancount-like).

Motivação (masterplan de agosto/2026): `bet_log` (wc-predictor) e
`close_trial_sharpes` (previsao-cripto) cada um reinventava seu próprio jeito de
registrar "dinheiro/unidade entrou, dinheiro/unidade saiu" — o mesmo padrão do
`PredictionPoint` (emissão→maturação) mas para o lado FINANCEIRO do ciclo. Este
módulo generaliza para um **livro-razão de partidas dobradas**: toda transação é
uma lista de `Posting`s (conta, valor) cuja soma é ZERO — a invariante contábil
que torna erros de digitação/duplicação detectáveis por construção, não por
auditoria manual depois.

Não é um sistema de contas a pagar. É o contrato mínimo: `Posting` (imutável),
`Transaction` (grupo de postings que soma zero, timestamp `at`), `Ledger`
(lista append-only de transações + `balance(account)` e `balances()`).
Unidade é opaca ao core (BRL, USDT, "unidades de stake") — quem dá sentido é o
domínio; o core só garante a partida dobrada.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

__all__ = ["Posting", "Transaction", "Ledger", "UnbalancedTransactionError"]

_EPS = 1e-9


class UnbalancedTransactionError(ValueError):
    """Uma transação cujos postings não somam zero — partida dobrada violada."""


@dataclass(frozen=True)
class Posting:
    """Uma perna de uma transação: `amount` credita (>0) ou debita (<0) `account`.

    `account` é um path livre do domínio (ex.: "assets:cripto:btc",
    "equity:pnl:trial-v3"). `amount` é float na unidade da transação."""

    account: str
    amount: float

    def __post_init__(self) -> None:
        if not self.account:
            raise ValueError("Posting exige account não-vazio")
        if not math.isfinite(self.amount):
            raise ValueError(f"Posting({self.account!r}): amount não-finito ({self.amount!r})")


@dataclass(frozen=True)
class Transaction:
    """Grupo de `Posting`s que soma exatamente zero (tolerância `_EPS`).

    `at`: instante da transação (âncora temporal — histórico é bitemporal se o
    domínio quiser adicionar `recorded_at` no metadata). `narration`: descrição
    livre. `metadata`: contexto de domínio (trial, mercado, modelo)."""

    at: datetime
    postings: tuple
    narration: str = ""
    metadata: dict | None = None

    def __post_init__(self) -> None:
        if len(self.postings) < 2:
            raise ValueError("Transaction exige >= 2 postings (partida dobrada)")
        total = sum(p.amount for p in self.postings)
        if abs(total) > _EPS:
            raise UnbalancedTransactionError(
                f"transação '{self.narration}' não balanceia: soma={total!r} "
                f"(esperado 0, tolerância {_EPS})")


@dataclass
class Ledger:
    """Livro-razão append-only: histórico imutável de `Transaction`s + saldos derivados.

    `post(...)` é a única forma de escrita — cria a `Transaction` (valida a
    partida dobrada na construção) e a anexa. Nada é removido ou editado: um
    estorno é uma transação nova com os sinais invertidos, preservando o
    histórico (mesmo espírito do `PredictionPoint`/`TrialRegistry`: correção é
    entrada nova, não reescrita silenciosa)."""

    transactions: list = field(default_factory=list)

    def post(self, at: datetime, postings: list, *, narration: str = "",
             metadata: dict | None = None) -> Transaction:
        txn = Transaction(at=at, postings=tuple(postings), narration=narration,
                          metadata=metadata)
        self.transactions.append(txn)
        return txn

    def balance(self, account: str) -> float:
        """Saldo de `account` = soma de todos os postings dessa conta, exata."""
        return sum(p.amount for t in self.transactions for p in t.postings
                   if p.account == account)

    def balances(self) -> dict:
        """Saldo de TODAS as contas com atividade — {account: saldo}."""
        out: dict = {}
        for t in self.transactions:
            for p in t.postings:
                out[p.account] = out.get(p.account, 0.0) + p.amount
        return out

    def history(self, account: str) -> list:
        """Transações que tocam `account`, em ordem de postagem (não por `at`)."""
        return [t for t in self.transactions
                if any(p.account == account for p in t.postings)]
