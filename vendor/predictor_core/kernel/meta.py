"""predictor-core.meta — fingerprint determinístico de artefatos treinados.

Unifica duas defesas que nasceram separadas nos domínios contra o MESMO bug:
servir um artefato (modelo .pkl, cache de parâmetros) treinado sob um CONTRATO
antigo com código novo — incoerência silenciosa e cara.
  - previsao-cripto: `regime_engine._model_fingerprint()` (schema_version + features
    de emissão + tipo de covariância) validado no load do .pkl.
  - wc-predictor: `config_hash` do cache de serving (Elo + params materializados),
    que detecta staleness de configuração.

O contrato de um artefato é: (1) a versão de schema — a alavanca MANUAL para mudança
de SEMÂNTICA que um hash de valores não pega (ex.: realized_vol passa de 24h p/ 12h);
(2) a tupla ORDENADA de features que ele consome (ordem = colunas); (3) o hash dos
hiperparâmetros. `validate` levanta em incompatibilidade (falha explícita) e avisa em
artefato legado sem fingerprint (compatibilidade de migração).
"""
from predictor_core.kernel.infra import config_hash


class StaleModelError(RuntimeError):
    """Artefato carregado sob contrato de features/schema/params incompatível com o
    código atual — retreine em vez de servir previsões incoerentes."""


def fingerprint(schema_version: int, features, params: dict | None = None) -> dict:
    """Contrato estrutural de um artefato — o que o torna compatível (ou não).

    schema_version: alavanca manual de versão semântica (incremente quando o
        SIGNIFICADO das features mudar sem mudar seus nomes).
    features: sequência ORDENADA de nomes de feature (a ordem importa — são colunas).
    params: dict de hiperparâmetros; entra como hash determinístico (config_hash).
    Retorna um dict canônico, comparável por igualdade e serializável (JSON-safe).
    """
    return {
        "schema_version": int(schema_version),
        "features": list(features),
        "params_hash": config_hash(params or {}),
    }


def validate(saved: dict | None, current: dict) -> None:
    """Compara o fingerprint SALVO com o do código ATUAL.

    - saved is None  → artefato legado (salvo antes do guard): avisa via warnings e
      segue (o próximo save carimba). Compatibilidade de migração, não erro.
    - saved != current → StaleModelError: contrato divergiu, artefato incoerente.
    - saved == current → ok, retorna None.
    """
    if saved is None:
        import warnings
        warnings.warn(
            "meta.validate: artefato sem fingerprint de procedência — "
            "compatibilidade de features não verificável; recomendado retreinar.",
            RuntimeWarning, stacklevel=2)
        return
    if saved != current:
        raise StaleModelError(
            f"artefato incompatível com o código atual.\n  salvo: {saved}\n"
            f"  atual: {current}\nRetreine o artefato em vez de servir previsões incoerentes.")
