"""Observabilidade: logging estruturado da stdlib (não loguru — sem dependência).

Um logger nomeado 'wc' com dois destinos: console (nível INFO, limpo para o
operador) e arquivo rotativo data/wc.log (nível DEBUG, para investigar a falha
das 3h da manhã). setup_logging é idempotente — chamável de qualquer entrypoint.
"""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_NAME = "wc"
_CONFIGURED = False


def setup_logging(log_dir: Path | None = None, level: int = logging.INFO):
    global _CONFIGURED
    logger = logging.getLogger(_NAME)
    if _CONFIGURED:
        return logger
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(fmt)
    logger.addHandler(console)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        fileh = RotatingFileHandler(log_dir / "wc.log", maxBytes=1_000_000,
                                    backupCount=3, encoding="utf-8")
        fileh.setLevel(logging.DEBUG)
        fileh.setFormatter(fmt)
        logger.addHandler(fileh)

    logger.propagate = False
    _CONFIGURED = True
    return logger


def get_logger():
    return logging.getLogger(_NAME)
