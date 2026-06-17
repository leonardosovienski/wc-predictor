"""Resiliência de rede: retry com backoff exponencial — stdlib, sem dependência.

Endpoints de terceiros (Sofascore atrás de Cloudflare, raw do GitHub) dão timeout
intermitente. Sem retry, uma falha de madrugada mata a coleta inteira. O decorator
tenta de novo com espera crescente antes de desistir.
"""
import time
from functools import wraps

from .obs import get_logger

log = get_logger()


def retry(attempts: int = 4, base_delay: float = 1.0, backoff: float = 2.0,
          exceptions: tuple = (Exception,)):
    """Re-tenta a função com espera base_delay * backoff**n entre as tentativas.
    Propaga a exceção só depois de esgotar as tentativas."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            delay = base_delay
            for n in range(1, attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except exceptions as e:
                    if n == attempts:
                        log.error("%s falhou após %d tentativas: %s", fn.__name__, n, e)
                        raise
                    log.warning("%s falhou (tentativa %d/%d): %s — repetindo em %.1fs",
                                fn.__name__, n, attempts, e, delay)
                    time.sleep(delay)
                    delay *= backoff
        return wrapper
    return deco
