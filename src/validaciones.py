"""Validaciones de cierre de la carga: se valida el dato antes de entregarlo al negocio.

Corren dentro de la misma transacción que la carga a Gold: si alguna falla,
la carga completa se revierte y Gold queda como estaba.
"""
import pandas as pd
from sqlalchemy import text

from . import config


class ValidacionError(Exception):
    def __init__(self, mensaje: str, resultados: list[dict]):
        super().__init__(mensaje)
        self.resultados = resultados


def _escalar(con, sql: str, **parametros):
    return con.execute(text(sql), parametros).scalar()


def _validar_inventario(con, silver, chequear) -> None:
    c = silver.conteos
    suma = c["inv_filas_validas"] + c["inv_filas_rechazadas"] + c["inv_filas_excluidas"]
    chequear("V10 Inventario: conservación de filas Bronze -> Silver", c["inv_filas_leidas"] == suma,
             f"{c['inv_filas_leidas']} leídas = {c['inv_filas_validas']} válidas + "
             f"{c['inv_filas_rechazadas']} rechazadas + {c['inv_filas_excluidas']} excluidas")

    huerfanas = _escalar(con, """
        SELECT COUNT(*) FROM fact_inventario f
        LEFT JOIN dim_fecha d    ON d.sk_fecha = f.sk_fecha
        LEFT JOIN dim_producto p ON p.sk_producto = f.sk_producto
        LEFT JOIN dim_sucursal s ON s.sk_sucursal = f.sk_sucursal
        WHERE d.sk_fecha IS NULL OR p.sk_producto IS NULL OR s.sk_sucursal IS NULL""")
    chequear("V11 Inventario: integridad referencial del hecho", huerfanas == 0, f"{huerfanas} filas huérfanas")

    inv = silver.inventario
    inicio, fin = inv["fecha"].min(), inv["fecha"].max()
    periodo = {"desde": int(inicio.strftime("%Y%m%d")), "hasta": int(fin.strftime("%Y%m%d"))}
    filas_gold, stock_gold, vendidas_inv = con.execute(text("""
        SELECT COUNT(*), COALESCE(SUM(stock_cierre), 0), COALESCE(SUM(unidades_vendidas), 0)
        FROM fact_inventario WHERE sk_fecha BETWEEN :desde AND :hasta"""), periodo).one()
    stock_silver = int(inv["stock_cierre"].sum())
    chequear("V12 Inventario: cuadratura Silver -> Gold (filas y stock del período)",
             filas_gold == len(inv) and stock_gold == stock_silver,
             f"Silver {len(inv)} filas / {stock_silver:,} unidades vs Gold {filas_gold} filas / {stock_gold:,} unidades")

    # Completitud del snapshot: cada producto del maestro, en cada sucursal abierta, cada día.
    aperturas = pd.to_datetime(silver.sucursales["fecha_apertura"])
    dias_abiertos = ((fin - aperturas.clip(lower=inicio)).dt.days + 1).clip(lower=0).sum()
    esperadas = int(len(silver.productos) * dias_abiertos)
    completitud = filas_gold / esperadas if esperadas else 0
    chequear("V13 Inventario: completitud del snapshot diario",
             completitud >= config.COMPLETITUD_MINIMA_INVENTARIO,
             f"{filas_gold:,} de {esperadas:,} combinaciones producto-sucursal-día ({completitud:.2%}); "
             f"mínimo {config.COMPLETITUD_MINIMA_INVENTARIO:.0%}")

    vendidas_ventas = _escalar(con, """SELECT COALESCE(SUM(cantidad), 0) FROM fact_ventas
                                       WHERE sk_fecha BETWEEN :desde AND :hasta""", **periodo)
    diferencia = abs(vendidas_inv - vendidas_ventas) / vendidas_ventas if vendidas_ventas else 1
    chequear("V14 Cuadratura entre hechos: unidades vendidas de inventario vs fact_ventas",
             diferencia <= config.TOLERANCIA_CUADRATURA_UNIDADES,
             f"inventario {vendidas_inv:,} vs ventas {vendidas_ventas:,} unidades (diferencia {diferencia:.2%}; "
             f"tolerancia {config.TOLERANCIA_CUADRATURA_UNIDADES:.0%}, explicada por filas rechazadas en Silver)")


def ejecutar(con, silver, id_carga: str, log) -> list[dict]:
    resultados = []

    def chequear(nombre: str, correcto: bool, detalle: str) -> None:
        resultados.append({"id_carga": id_carga, "validacion": nombre,
                           "resultado": "OK" if correcto else "FALLA", "detalle": detalle})

    c = silver.conteos
    suma = c["lineas_validas"] + c["lineas_rechazadas"] + c["lineas_excluidas"]
    chequear("V01 Conservación de filas Bronze -> Silver", c["lineas_leidas"] == suma,
             f"{c['lineas_leidas']} leídas = {c['lineas_validas']} válidas + "
             f"{c['lineas_rechazadas']} rechazadas + {c['lineas_excluidas']} excluidas")

    huerfanas = _escalar(con, """
        SELECT COUNT(*) FROM fact_ventas f
        LEFT JOIN dim_fecha d    ON d.sk_fecha = f.sk_fecha
        LEFT JOIN dim_cliente cl ON cl.sk_cliente = f.sk_cliente
        LEFT JOIN dim_producto p ON p.sk_producto = f.sk_producto
        LEFT JOIN dim_sucursal s ON s.sk_sucursal = f.sk_sucursal
        LEFT JOIN dim_canal ca   ON ca.sk_canal = f.sk_canal
        WHERE d.sk_fecha IS NULL OR cl.sk_cliente IS NULL OR p.sk_producto IS NULL
           OR s.sk_sucursal IS NULL OR ca.sk_canal IS NULL""")
    chequear("V02 Integridad referencial del hecho", huerfanas == 0, f"{huerfanas} filas huérfanas")

    # Un cliente dado de baja en el CRM queda sin versión vigente; nunca puede tener más de una.
    varias_vigentes, de_baja = con.execute(text("""
        SELECT COALESCE(SUM(vigentes > 1), 0), COALESCE(SUM(vigentes = 0), 0)
        FROM (SELECT SUM(es_actual) AS vigentes FROM dim_cliente GROUP BY id_cliente)""")).one()
    mal_marcadas = _escalar(con, """
        SELECT COUNT(*) FROM dim_cliente WHERE es_actual <> (fecha_fin_vigencia = '9999-12-31')""")
    chequear("V03 SCD2: una sola versión vigente por cliente (ninguna si está de baja)",
             varias_vigentes == 0 and mal_marcadas == 0,
             f"{varias_vigentes} clientes con más de 1 versión vigente; {mal_marcadas} versiones con la marca "
             f"de vigencia inconsistente; {de_baja} clientes de baja")

    traslapes = _escalar(con, """
        SELECT COUNT(*) FROM dim_cliente a JOIN dim_cliente b
          ON a.id_cliente = b.id_cliente AND a.sk_cliente < b.sk_cliente
         AND a.fecha_inicio_vigencia <= b.fecha_fin_vigencia
         AND b.fecha_inicio_vigencia <= a.fecha_fin_vigencia""")
    invertidas = _escalar(con, "SELECT COUNT(*) FROM dim_cliente WHERE fecha_inicio_vigencia > fecha_fin_vigencia")
    chequear("V04 SCD2: vigencias sin traslape ni fechas invertidas", traslapes == 0 and invertidas == 0,
             f"{traslapes} pares de versiones traslapadas; {invertidas} versiones que terminan antes de empezar")

    mal_asignadas = _escalar(con, """
        SELECT COUNT(*) FROM fact_ventas f
        JOIN dim_fecha d    ON d.sk_fecha = f.sk_fecha
        JOIN dim_cliente cl ON cl.sk_cliente = f.sk_cliente
        WHERE f.sk_cliente <> -1
          AND d.fecha NOT BETWEEN cl.fecha_inicio_vigencia AND cl.fecha_fin_vigencia""")
    chequear("V05 SCD2: cada venta apunta a la versión vigente en su fecha", mal_asignadas == 0,
             f"{mal_asignadas} ventas asignadas a una versión no vigente")

    ventas = silver.ventas
    desde = int(ventas["fecha_hora"].min().strftime("%Y%m%d"))
    hasta = int(ventas["fecha_hora"].max().strftime("%Y%m%d"))
    filas_gold, monto_gold = con.execute(text("""
        SELECT COUNT(*), COALESCE(SUM(monto_neto), 0) FROM fact_ventas
        WHERE sk_fecha BETWEEN :desde AND :hasta"""), {"desde": desde, "hasta": hasta}).one()
    monto_silver = int(ventas["monto_neto"].sum())
    chequear("V06 Cuadratura Silver -> Gold (filas y monto neto del período)",
             filas_gold == len(ventas) and monto_gold == monto_silver,
             f"Silver {len(ventas)} filas / ${monto_silver:,} vs Gold {filas_gold} filas / ${monto_gold:,}")

    descuadres = _escalar(con, "SELECT COUNT(*) FROM fact_ventas WHERE monto_neto <> monto_bruto - descuento")
    chequear("V07 Regla de cálculo: monto_neto = monto_bruto - descuento", descuadres == 0,
             f"{descuadres} filas con monto neto mal calculado")

    duplicadas = _escalar(con, """
        SELECT COUNT(*) FROM (SELECT 1 FROM fact_ventas
                              GROUP BY fuente_origen, numero_documento, nro_linea HAVING COUNT(*) > 1)""")
    chequear("V08 Sin líneas duplicadas en el hecho", duplicadas == 0, f"{duplicadas} claves naturales repetidas")

    tablas = pd.read_sql(text("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"),
                         con)["name"]
    personales = sorted(f"{t}.{c}" for t in tablas
                        for c in pd.read_sql(text(f"PRAGMA table_info({t})"), con)["name"]
                        if c in {"rut", "email", "nombre", "telefono", "rut_cliente", "email_cliente"})
    chequear("V09 Gold sin datos personales directos", not personales,
             f"columnas personales en Gold: {personales or 'ninguna'}")

    _validar_inventario(con, silver, chequear)

    for r in resultados:
        nivel = log.info if r["resultado"] == "OK" else log.error
        nivel("Valid. | %-5s | %s | %s", r["resultado"], r["validacion"], r["detalle"])
    fallas = [r for r in resultados if r["resultado"] == "FALLA"]
    if fallas:
        raise ValidacionError(f"{len(fallas)} validaciones fallaron: se revierte la carga", resultados)
    pd.DataFrame(resultados).to_sql("etl_validaciones", con, if_exists="append", index=False)
    return resultados
