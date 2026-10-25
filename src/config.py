"""Configuración del proyecto.

Rutas, conexión y secretos se leen desde variables de entorno (o desde un
archivo .env local), nunca se escriben en el código.
"""
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def _cargar_env(ruta: Path) -> None:
    """Carga un .env simple (CLAVE=valor) sin pisar variables ya definidas."""
    if not ruta.exists():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        os.environ.setdefault(clave.strip(), valor.strip())


_cargar_env(RAIZ / ".env")

DATA = RAIZ / "data"
FUENTES = DATA / "fuentes"
BRONZE = DATA / "bronze"
SILVER = DATA / "silver"
GOLD = DATA / "gold"
LOGS = RAIZ / "logs"
SQL = RAIZ / "sql"
DOCS = RAIZ / "docs"


def _url_dwh() -> str:
    url = os.getenv("DR360_DWH_URL", "sqlite:///data/gold/dwh_dataretail360.db")
    # Las rutas SQLite relativas se resuelven desde la raíz del proyecto.
    if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
        url = f"sqlite:///{RAIZ / url[len('sqlite:///'):]}"
    return url


DWH_URL = _url_dwh()
SALT_PSEUDONIMO = os.getenv("DR360_SALT_PSEUDONIMO")
LOG_LEVEL = os.getenv("DR360_LOG_LEVEL", "INFO")

# Semilla de los datos simulados: misma semilla, mismos datos.
SEMILLA = 360

# Contratos de datos: columnas mínimas que cada fuente debe traer.
CONTRATOS = {
    "pos_ventas": [
        "nro_boleta", "linea", "fecha_hora", "cod_sucursal", "rut_cliente",
        "cod_producto", "cantidad", "precio_unitario", "descuento", "estado",
    ],
    "ecommerce_pedidos": [
        "pedido_id", "fecha", "canal", "cliente", "items", "estado",
    ],
    "crm_clientes": [
        "id_crm", "rut", "nombre", "email", "telefono", "comuna",
        "segmento", "fecha_registro", "fecha_actualizacion",
    ],
    "maestro_productos": [
        "cod_producto", "nombre", "categoria", "subcategoria", "marca",
        "linea", "precio_lista",
    ],
    "equivalencias_codigos": ["sku_web", "cod_producto"],
    "sucursales": [
        "cod_sucursal", "nombre", "tipo", "direccion", "comuna", "fecha_apertura",
    ],
    "geografia_comunas": ["comuna", "region", "zona", "latitud", "longitud"],
}

# Reglas de negocio con umbrales configurables.
MONTO_MAXIMO_LINEA = 5_000_000  # una línea sobre este valor se considera fuera de rango
CANTIDAD_MAXIMA_LINEA = 50
