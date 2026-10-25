"""Orquestador del pipeline ETL DataRetail 360: Bronze -> Silver -> Gold.

Uso:
    python -m src.pipeline --lote 1 --reiniciar   # carga inicial desde cero
    python -m src.pipeline --lote 2               # carga incremental
    python -m src.pipeline --todo --reiniciar     # reconstruye todo (lotes 1 y 2)
"""
import argparse
import sys
import uuid
from datetime import datetime

import pandas as pd

from . import bronze, gold, silver, validaciones
from .registro import obtener_logger


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def ejecutar(lote: int, reiniciar: bool = False) -> dict:
    log = obtener_logger()
    engine = gold.motor()
    if reiniciar:
        log.warning("Se reinicia el almacenamiento analítico (Gold) antes de cargar")
        gold.reiniciar(engine)
        engine = gold.motor()
    gold.crear_esquema(engine)

    # Sufijo aleatorio: dos ejecuciones en el mismo segundo no comparten id.
    id_carga = f"L{lote}-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4]}"
    gold.registrar_inicio(engine, id_carga, lote, _ahora())
    log.info("===== Inicio carga %s (lote %d) =====", id_carga, lote)
    conteos = {}
    try:
        datos_bronze = bronze.ingestar(lote, id_carga, log)
        datos_silver = silver.transformar(datos_bronze, lote, id_carga, log)
        conteos.update(datos_silver.conteos)
        # Gold y validaciones en una sola transacción: todo o nada.
        with engine.begin() as con:
            conteos.update(gold.cargar(con, datos_silver, id_carga, log))
            validaciones.ejecutar(con, datos_silver, id_carga, log)
    except (bronze.ContratoError, FileNotFoundError) as exc:
        # Error esperable de las fuentes: se reporta sin traceback y la carga se detiene.
        log.error("Carga %s FALLIDA: %s", id_carga, exc)
        gold.registrar_fin(engine, id_carga, "FALLIDA", _ahora(), conteos, f"{type(exc).__name__}: {exc}")
        raise
    except validaciones.ValidacionError as exc:
        with engine.begin() as con:
            pd.DataFrame(exc.resultados).to_sql("etl_validaciones", con, if_exists="append", index=False)
        log.error("Carga %s FALLIDA: %s", id_carga, exc)
        gold.registrar_fin(engine, id_carga, "FALLIDA", _ahora(), conteos, str(exc))
        raise
    except Exception as exc:
        log.exception("Carga %s FALLIDA por error no controlado", id_carga)
        gold.registrar_fin(engine, id_carga, "FALLIDA", _ahora(), conteos, f"{type(exc).__name__}: {exc}"[:500])
        raise
    gold.registrar_fin(engine, id_carga, "EXITOSA", _ahora(), conteos)
    log.info("===== Fin carga %s: EXITOSA (%d líneas nuevas en fact_ventas, %d ya existían) =====",
             id_carga, conteos["fact_insertadas"], conteos["fact_omitidas"])
    engine.dispose()
    return {"id_carga": id_carga, **conteos}


def main() -> int:
    parser = argparse.ArgumentParser(description="Pipeline ETL DataRetail 360 (Bronze -> Silver -> Gold)")
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--lote", type=int, choices=[1, 2], help="lote a cargar")
    grupo.add_argument("--todo", action="store_true", help="carga los lotes 1 y 2 en orden")
    parser.add_argument("--reiniciar", action="store_true", help="borra Gold antes de cargar")
    args = parser.parse_args()
    try:
        if args.todo:
            ejecutar(1, reiniciar=args.reiniciar)
            ejecutar(2)
        else:
            ejecutar(args.lote, reiniciar=args.reiniciar)
    except Exception:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
