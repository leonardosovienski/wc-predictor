"""predictor-core.net — rede unificada do núcleo.

Duas camadas: (1) download stdlib (urllib) para bulk corporativo (COTAHIST do stocks);
(2) camada async resiliente (httpx) para REST — CoinGecko/SerpAPI/LLM do cripto, com
retry/backoff. httpx é importado LAZY (dentro das funções) — consumidores stdlib-first
que só usam o download (stocks) vendorizam este módulo SEM precisar de httpx.
"""
import asyncio
import functools
import hashlib
import logging
import pathlib
import random
import shutil
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

_USER_AGENT = "predictor-stocks/0.1 (research)"


def download_file(url: str, dest: pathlib.Path, timeout: int = 120,
                  retries: int = 3, backoff: float = 5.0) -> pathlib.Path:
    """Baixa url para dest (cria diretórios necessários). Retorna dest."""
    dest = pathlib.Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    for attempt in range(1, retries + 1):
        try:
            logger.info("download attempt %d/%d: %s", attempt, retries, url)
            req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp, open(tmp, "wb") as out:
                shutil.copyfileobj(resp, out)
            tmp.replace(dest)
            logger.info("saved to %s", dest)
            return dest
        except (urllib.error.URLError, TimeoutError) as exc:
            logger.warning("attempt %d failed: %s", attempt, exc)
            if attempt < retries:
                time.sleep(backoff * attempt)
            else:
                raise
    raise RuntimeError("unreachable")


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# --- Camada async resiliente (REST: CoinGecko/SerpAPI/LLM) ------------------
# httpx é LAZY: consumidores stdlib-first que só usam o download acima
# (stocks/COTAHIST) vendorizam este módulo sem precisar de httpx instalado.

TRANSIENT_STATUS = {429, 500, 502, 503, 504}
TRANSIENT_MARKERS = (
    "unavailable", "overloaded", "high demand", "rate limit",
    "temporarily", "timeout", "try again", "resource_exhausted",
)
# Cota DIÁRIA/por projeto: retry só desperdiça tempo (espere o reset). Não reententar.
DAILY_QUOTA_MARKERS = ("per day", "perday", "requests per day", "generaterequestsperday")


def get_http_client(timeout: int = 30):
    """Cliente HTTP async unificado e blindado do núcleo (httpx, SSL verificado).
    Lazy: só exige httpx quem de fato faz rede."""
    import httpx
    return httpx.AsyncClient(timeout=timeout)


def _status_of(exc):
    code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if isinstance(code, int):
        return code
    resp = getattr(exc, "response", None)
    if resp is not None and isinstance(getattr(resp, "status_code", None), int):
        return resp.status_code
    return None


def is_transient(exc: Exception) -> bool:
    """True se o erro vale retry. Cota DIÁRIA e 404 NÃO são transitórios."""
    msg = str(exc).lower()
    if any(m in msg for m in DAILY_QUOTA_MARKERS):
        return False
    if _status_of(exc) in TRANSIENT_STATUS:
        return True
    try:
        import httpx
        if isinstance(exc, (httpx.TransportError, httpx.TimeoutException)):
            return True
    except Exception:
        pass
    return any(m in msg for m in TRANSIENT_MARKERS)


def with_retry(attempts: int = 4, base_delay: float = 2.0, max_delay: float = 30.0):
    """Decorator para corotinas: reexecuta em erro transitório com backoff exp + jitter."""
    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            delay = base_delay
            for attempt in range(1, attempts + 1):
                try:
                    return await fn(*args, **kwargs)
                except Exception as exc:
                    if attempt == attempts or not is_transient(exc):
                        raise
                    sleep = min(delay, max_delay) + random.uniform(0, 1)
                    logger.warning("%s: transitório (%s); tentativa %d/%d, aguardando %.1fs",
                                   fn.__name__, type(exc).__name__, attempt, attempts - 1, sleep)
                    await asyncio.sleep(sleep)
                    delay *= 2
        return wrapper
    return decorator
