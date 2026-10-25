"""Logging del pipeline y utilidades de robustez (reintentos)."""
import functools
import logging
import time

from . import config

_FORMATO = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def obtener_logger(nombre: str = "dr360") -> logging.Logger:
    """Logger que escribe en consola y en logs/pipeline.log.

    Regla del proyecto: nunca registrar datos personales (RUT, correo, nombre)
    ni secretos; solo conteos, claves técnicas y mensajes de control.
    """
    logger = logging.getLogger(nombre)
    if logger.handlers:
        return logger
    logger.setLevel(config.LOG_LEVEL)
    config.LOGS.mkdir(parents=True, exist_ok=True)
    formato = logging.Formatter(_FORMATO, datefmt="%Y-%m-%d %H:%M:%S")
    archivo = logging.FileHandler(config.LOGS / "pipeline.log", encoding="utf-8")
    archivo.setFormatter(formato)
    consola = logging.StreamHandler()
    consola.setFormatter(formato)
    logger.addHandler(archivo)
    logger.addHandler(consola)
    logger.propagate = False
    return logger


def con_reintentos(intentos: int = 3, espera: float = 1.0, factor: float = 2.0,
                   errores: tuple = (OSError,)):
    """Reintenta una función ante fallas transitorias con espera creciente (backoff).

    Si se agotan los intentos, el error se relanza: deja de ser recuperable
    y el pipeline lo trata como fatal.
    """
    def decorador(funcion):
        @functools.wraps(funcion)
        def envoltura(*args, **kwargs):
            log = obtener_logger("dr360.reintentos")
            demora = espera
            for intento in range(1, intentos + 1):
                try:
                    return funcion(*args, **kwargs)
                except errores as exc:
                    if intento == intentos:
                        log.error("%s falló tras %d intentos: %s", funcion.__name__, intentos, exc)
                        raise
                    log.warning("%s falló (intento %d/%d): %s. Reintentando en %.1fs",
                                funcion.__name__, intento, intentos, exc, demora)
                    time.sleep(demora)
                    demora *= factor
        return envoltura
    return decorador
