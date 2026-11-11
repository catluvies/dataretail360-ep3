"""Exporta la capa Gold a CSV para construir el dashboard en la herramienta BI (guía 3.2.3).

    data/bi/powerbi/  modelo estrella completo: 5 dimensiones y 2 hechos (UTF-8 con BOM,
                      para que Power BI lea bien tildes y eñes)
    data/bi/looker/   tablas planas para Looker Studio, que no une tablas por relaciones:
                      ventas (detalle), inventario_mensual (K3 y K4) y quiebre_productos (tabla de detalle)

Uso (después de correr el pipeline):  python -m src.exportar_bi
"""
import pandas as pd
from sqlalchemy import create_engine, text

from . import config

DESTINO = config.DATA / "bi"
TABLAS_POWERBI = ["dim_fecha", "dim_producto", "dim_sucursal", "dim_cliente", "dim_canal",
                  "fact_ventas", "fact_inventario"]
# El linaje se queda en Gold: el dashboard no lo usa y triplica el peso del inventario.
LINAJE_HECHOS = {"id_carga", "archivo_origen", "fila_origen"}

CONSULTAS_LOOKER = {
    # Una fila por línea vendida, con los atributos para filtrar (sin datos personales).
    "ventas": """
        SELECT fecha, anio, semestre, mes, anio_mes, canal, tipo_canal, sucursal, region_sucursal AS region,
               zona_sucursal AS zona, categoria, subcategoria, producto, linea_producto, segmento_cliente,
               numero_documento, es_devolucion, unidades, venta_neta, monto_devuelto
        FROM vw_ventas""",
    # Componentes aditivos de K3 y K4 por mes, sucursal y categoría.
    "inventario_mensual": """
        SELECT anio_mes, CAST(substr(anio_mes, 1, 4) AS INTEGER) AS anio,
               CAST(substr(anio_mes, 6, 2) AS INTEGER) AS mes, cod_sucursal, sucursal, region, zona,
               categoria, registros, dias_quiebre, stock_cierre_mes, unidades_vendidas,
               unidades_vendidas_28d, unidades_recibidas
        FROM agg_inventario_mes""",
    # Detalle para la tabla "Productos con quiebre de stock": producto x sucursal x mes.
    "quiebre_productos": """
        WITH base AS (
            SELECT f.sk_producto, f.sk_sucursal, f.stock_cierre, f.unidades_vendidas, f.es_quiebre,
                   f.stock_minimo, d.anio_mes,
                   ROW_NUMBER() OVER (PARTITION BY f.sk_producto, f.sk_sucursal, d.anio_mes
                                      ORDER BY f.sk_fecha DESC) AS orden_desde_fin
            FROM fact_inventario f JOIN dim_fecha d ON d.sk_fecha = f.sk_fecha)
        SELECT b.anio_mes, s.nombre_sucursal AS sucursal, s.region, s.zona, p.cod_producto,
               p.nombre_producto AS producto, p.categoria, p.subcategoria,
               COUNT(*) AS dias_informados, SUM(b.es_quiebre) AS dias_quiebre,
               SUM(CASE WHEN b.orden_desde_fin = 1 THEN b.stock_cierre END) AS stock_cierre_mes,
               MAX(b.stock_minimo) AS stock_minimo, SUM(b.unidades_vendidas) AS unidades_vendidas
        FROM base b
        JOIN dim_sucursal s ON s.sk_sucursal = b.sk_sucursal
        JOIN dim_producto p ON p.sk_producto = b.sk_producto
        GROUP BY b.anio_mes, s.nombre_sucursal, s.region, s.zona, p.cod_producto, p.nombre_producto,
                 p.categoria, p.subcategoria""",
}


def exportar() -> None:
    engine = create_engine(config.DWH_URL)
    with engine.connect() as con:
        destino = DESTINO / "powerbi"
        destino.mkdir(parents=True, exist_ok=True)
        for tabla in TABLAS_POWERBI:
            df = pd.read_sql(text(f"SELECT * FROM {tabla}"), con)
            if tabla.startswith("fact"):
                df = df.drop(columns=sorted(LINAJE_HECHOS & set(df.columns)))
            df.to_csv(destino / f"{tabla}.csv", index=False, encoding="utf-8-sig")
            print(f"powerbi/{tabla}.csv: {len(df):,} filas")
        destino = DESTINO / "looker"
        destino.mkdir(parents=True, exist_ok=True)
        for nombre, consulta in CONSULTAS_LOOKER.items():
            df = pd.read_sql(text(consulta), con)
            df.to_csv(destino / f"{nombre}.csv", index=False, encoding="utf-8")
            print(f"looker/{nombre}.csv: {len(df):,} filas")
    engine.dispose()
    print("Archivos para la herramienta BI en", DESTINO)


if __name__ == "__main__":
    exportar()
