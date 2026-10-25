"""Capa Bronze: ingesta del dato crudo, tal como llega de cada fuente.

Aquí no se corrige nada. Todo se guarda como texto para no perder el valor
original, y cada fila recibe metadatos de linaje (_id_carga, _archivo,
_fila_origen, _hash_archivo) que permiten rastrear cada venta de Gold
hasta su registro fuente.
"""
import hashlib
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

from . import config
from .registro import con_reintentos


class ContratoError(Exception):
    """La fuente no trae las columnas acordadas: error fatal, se detiene la carga."""


def _hash(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()[:12]


def _leer_csv(ruta: Path, separador: str = ",") -> pd.DataFrame:
    return pd.read_csv(ruta, sep=separador, dtype=str, keep_default_na=False, encoding="utf-8")


def _leer_pedidos(ruta: Path) -> pd.DataFrame:
    """Un pedido por fila; cliente e items quedan como JSON crudo."""
    pedidos = json.loads(ruta.read_text(encoding="utf-8"))
    filas = [{
        "pedido_id": p.get("pedido_id"),
        "fecha": p.get("fecha"),
        "canal": p.get("canal"),
        "cliente": json.dumps(p.get("cliente"), ensure_ascii=False),
        "items": json.dumps(p.get("items"), ensure_ascii=False),
        "estado": p.get("estado"),
    } for p in pedidos]
    return pd.DataFrame(filas, dtype="string")


@con_reintentos(intentos=3, espera=1.0, errores=(OperationalError, OSError))
def _leer_crm(ruta: Path) -> pd.DataFrame:
    """Extracción desde la base transaccional del CRM (con reintentos ante fallas de conexión)."""
    motor = create_engine(f"sqlite:///{ruta}")
    try:
        with motor.connect() as conexion:
            df = pd.read_sql("SELECT * FROM clientes", conexion)
    finally:
        motor.dispose()
    return df.astype("string")


# fuente -> (archivo, lector)
FUENTES = {
    "pos_ventas": ("pos_ventas_tiendas.csv", lambda r: _leer_csv(r, ";")),
    "ecommerce_pedidos": ("ecommerce_pedidos.json", _leer_pedidos),
    "crm_clientes": ("crm_clientes.db", _leer_crm),
    "maestro_productos": ("maestro_productos.csv", _leer_csv),
    "equivalencias_codigos": ("equivalencias_codigos.csv", _leer_csv),
    "sucursales": ("sucursales.csv", _leer_csv),
    "geografia_comunas": ("geografia_comunas.csv", _leer_csv),
}


def validar_contrato(fuente: str, df: pd.DataFrame) -> None:
    faltantes = set(config.CONTRATOS[fuente]) - set(df.columns)
    if faltantes:
        raise ContratoError(f"La fuente {fuente} no trae las columnas {sorted(faltantes)}")
    if df.empty:
        raise ContratoError(f"La fuente {fuente} llegó vacía")


def ingestar(lote: int, id_carga: str, log) -> dict[str, pd.DataFrame]:
    origen = config.FUENTES / f"lote_{lote}"
    if not origen.exists():
        raise FileNotFoundError(f"No existe la carpeta de fuentes {origen}")
    ahora = datetime.now().isoformat(timespec="seconds")
    resultado = {}
    for fuente, (archivo, lector) in FUENTES.items():
        ruta = origen / archivo
        if not ruta.exists():
            raise FileNotFoundError(f"Falta la fuente obligatoria {archivo}")
        df = lector(ruta)
        validar_contrato(fuente, df)
        # La fila 1 del CSV es el encabezado: la primera fila de datos es la 2.
        desfase = 2 if ruta.suffix == ".csv" else 1
        df = df.assign(
            _id_carga=id_carga, _lote=str(lote), _fuente=fuente, _archivo=archivo,
            _fila_origen=(pd.RangeIndex(len(df)) + desfase).astype(str),
            _hash_archivo=_hash(ruta), _fecha_ingesta=ahora,
        )
        destino = config.BRONZE / fuente / f"lote={lote}"
        destino.mkdir(parents=True, exist_ok=True)
        df.to_parquet(destino / "datos.parquet", index=False)
        log.info("Bronze | %-22s | %6d filas | %s (sha256 %s)", fuente, len(df), archivo, df["_hash_archivo"].iat[0])
        resultado[fuente] = df
    return resultado
