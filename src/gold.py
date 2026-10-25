"""Capa Gold: esquema estrella del proceso Ventas en el almacenamiento analítico.

Orden de carga: primero las dimensiones, después el hecho, porque
una fila de hechos no puede apuntar a una dimensión que aún no existe.

    dim_fecha     generada (calendario con feriados)
    dim_canal     catálogo fijo
    dim_sucursal  SCD tipo 1
    dim_producto  SCD tipo 1 + SCD tipo 3 (categoría)
    dim_cliente   SCD tipo 2 (comuna/región/zona y segmento)
    fact_ventas   transaccional, carga incremental e idempotente
"""
import subprocess
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import create_engine, event, text

from . import config
from . import reglas_calidad as rc

INICIO_VIGENCIA = "1900-01-01"
FIN_VIGENCIA = "9999-12-31"
SIN_INFORMACION = "Sin información"

CANALES = [(1, "TIENDA", "Tienda física", "Presencial"),
           (2, "WEB", "Sitio web", "Digital"),
           (3, "APP", "App móvil", "Digital")]
DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto",
         "Septiembre", "Octubre", "Noviembre", "Diciembre"]
# Calendario referencial de feriados nacionales.
FERIADOS = {
    **{date(anio, m, d): nombre for anio in (2024, 2025, 2026) for (m, d), nombre in {
        (1, 1): "Año Nuevo", (5, 1): "Día del Trabajo", (5, 21): "Día de las Glorias Navales",
        (6, 29): "San Pedro y San Pablo", (7, 16): "Virgen del Carmen", (8, 15): "Asunción de la Virgen",
        (9, 18): "Independencia Nacional", (9, 19): "Glorias del Ejército",
        (10, 12): "Encuentro de Dos Mundos", (10, 31): "Día de las Iglesias Evangélicas",
        (11, 1): "Día de Todos los Santos", (12, 8): "Inmaculada Concepción", (12, 25): "Navidad",
    }.items()},
    date(2024, 3, 29): "Viernes Santo", date(2024, 3, 30): "Sábado Santo",
    date(2025, 4, 18): "Viernes Santo", date(2025, 4, 19): "Sábado Santo",
    date(2026, 4, 3): "Viernes Santo", date(2026, 4, 4): "Sábado Santo",
    date(2024, 6, 20): "Día de los Pueblos Indígenas", date(2025, 6, 20): "Día de los Pueblos Indígenas",
    date(2026, 6, 21): "Día de los Pueblos Indígenas",
}


# ------------------------------------------------------------- infraestructura
def motor():
    config.GOLD.mkdir(parents=True, exist_ok=True)
    engine = create_engine(config.DWH_URL)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def _activar_claves_foraneas(conexion_dbapi, _):
            conexion_dbapi.execute("PRAGMA foreign_keys = ON")
    return engine


def _sentencias(ruta) -> list[str]:
    sentencias = []
    for bloque in ruta.read_text(encoding="utf-8").split(";"):
        codigo = "\n".join(l for l in bloque.splitlines() if not l.strip().startswith("--")).strip()
        if codigo:
            sentencias.append(bloque.strip())
    return sentencias


def crear_esquema(engine) -> None:
    with engine.begin() as con:
        for archivo in ("ddl_gold.sql", "vistas_semanticas.sql"):
            for sentencia in _sentencias(config.SQL / archivo):
                con.execute(text(sentencia))
        con.execute(text("INSERT OR IGNORE INTO dim_canal VALUES (:sk, :cod, :nombre, :tipo)"),
                    [dict(zip(["sk", "cod", "nombre", "tipo"], c)) for c in CANALES])


def reiniciar(engine) -> None:
    """Borra el almacenamiento analítico para reconstruirlo desde cero."""
    engine.dispose()
    if engine.dialect.name == "sqlite" and engine.url.database:
        from pathlib import Path
        Path(engine.url.database).unlink(missing_ok=True)


def version_codigo() -> str:
    """Commit de Git con el que corre la carga (trazabilidad del código)."""
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=config.RAIZ,
                                capture_output=True, text=True, check=True).stdout.strip()
        cambios = subprocess.run(["git", "status", "--porcelain"], cwd=config.RAIZ,
                                 capture_output=True, text=True, check=True).stdout.strip()
        return commit + ("+cambios-sin-commit" if cambios else "")
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "sin-git"


def registrar_inicio(engine, id_carga: str, lote: int, inicio: str) -> None:
    with engine.begin() as con:
        con.execute(text("""INSERT INTO etl_control_cargas (id_carga, lote, inicio, estado, version_codigo)
                            VALUES (:id, :lote, :inicio, 'EN_PROCESO', :version)"""),
                    {"id": id_carga, "lote": lote, "inicio": inicio, "version": version_codigo()})


def registrar_fin(engine, id_carga: str, estado: str, fin: str, conteos: dict | None = None,
                  mensaje: str | None = None) -> None:
    conteos = conteos or {}
    with engine.begin() as con:
        con.execute(text("""
            UPDATE etl_control_cargas SET fin = :fin, estado = :estado,
                   lineas_leidas = :leidas, lineas_validas = :validas,
                   lineas_rechazadas = :rechazadas, lineas_excluidas = :excluidas,
                   filas_insertadas_fact = :insertadas, filas_omitidas_ya_cargadas = :omitidas,
                   mensaje = :mensaje
            WHERE id_carga = :id"""), {
            "id": id_carga, "fin": fin, "estado": estado, "mensaje": mensaje,
            "leidas": conteos.get("lineas_leidas"), "validas": conteos.get("lineas_validas"),
            "rechazadas": conteos.get("lineas_rechazadas"), "excluidas": conteos.get("lineas_excluidas"),
            "insertadas": conteos.get("fact_insertadas"), "omitidas": conteos.get("fact_omitidas"),
        })


def _distinto(a, b) -> bool:
    if pd.isna(a) and pd.isna(b):
        return False
    if pd.isna(a) or pd.isna(b):
        return True
    if isinstance(a, float) or isinstance(b, float):
        return abs(float(a) - float(b)) > 1e-9
    return str(a) != str(b)


# ---------------------------------------------------------------- dimensiones
def _cargar_dim_fecha(con, ventas: pd.DataFrame) -> int:
    """Calendario completo de los años que aparecen en las ventas."""
    inicio = date(int(ventas["fecha_hora"].min().year), 1, 1)
    fin = date(int(ventas["fecha_hora"].max().year), 12, 31)
    existentes = set(pd.read_sql(text("SELECT sk_fecha FROM dim_fecha"), con)["sk_fecha"])
    filas = []
    for dia in pd.date_range(inicio, fin).date:
        sk = int(dia.strftime("%Y%m%d"))
        if sk in existentes:
            continue
        festivo = FERIADOS.get(dia)
        filas.append({
            "sk_fecha": sk, "fecha": dia.isoformat(), "dia": dia.day,
            "dia_semana": dia.isoweekday(), "nombre_dia": DIAS[dia.weekday()],
            "semana_iso": dia.isocalendar()[1], "mes": dia.month, "nombre_mes": MESES[dia.month - 1],
            "anio_mes": dia.strftime("%Y-%m"), "trimestre": (dia.month - 1) // 3 + 1,
            "semestre": 1 if dia.month <= 6 else 2, "anio": dia.year,
            "es_fin_de_semana": int(dia.weekday() >= 5), "es_festivo": int(festivo is not None),
            "nombre_festivo": festivo,
        })
    if filas:
        pd.DataFrame(filas).to_sql("dim_fecha", con, if_exists="append", index=False)
    return len(filas)


ATRIBUTOS_SUCURSAL = ["nombre_sucursal", "tipo_sucursal", "direccion", "comuna", "region", "zona",
                      "pais", "latitud", "longitud", "fecha_apertura"]


def _cargar_dim_sucursal(con, sucursales: pd.DataFrame, id_carga: str, hoy: str) -> dict:
    """SCD tipo 1: una fila por sucursal; los cambios sobrescriben."""
    actual = pd.read_sql(text("SELECT * FROM dim_sucursal"), con)
    entrante = sucursales[["cod_sucursal"] + ATRIBUTOS_SUCURSAL]
    nuevas = entrante[~entrante["cod_sucursal"].isin(actual["cod_sucursal"])]
    if not nuevas.empty:
        nuevas.assign(fecha_actualizacion=hoy, id_carga=id_carga).to_sql(
            "dim_sucursal", con, if_exists="append", index=False)
    cambios = []
    for fila in entrante.merge(actual, on="cod_sucursal", suffixes=("", "_actual")).to_dict("records"):
        if any(_distinto(fila[a], fila[f"{a}_actual"]) for a in ATRIBUTOS_SUCURSAL):
            cambios.append({**{a: fila[a] for a in ATRIBUTOS_SUCURSAL},
                            "cod": fila["cod_sucursal"], "hoy": hoy, "id_carga": id_carga})
    if cambios:
        asignaciones = ", ".join(f"{a} = :{a}" for a in ATRIBUTOS_SUCURSAL)
        con.execute(text(f"""UPDATE dim_sucursal SET {asignaciones}, fecha_actualizacion = :hoy,
                             id_carga = :id_carga WHERE cod_sucursal = :cod"""), cambios)
    return {"sucursales_nuevas": len(nuevas), "sucursales_scd1": len(cambios)}


SCD1_PRODUCTO = ["sku_web", "nombre_producto", "marca", "linea", "subcategoria", "precio_lista"]


def _cargar_dim_producto(con, productos: pd.DataFrame, id_carga: str, hoy: str) -> dict:
    """SCD tipo 1 en atributos descriptivos; SCD tipo 3 en la categoría."""
    actual = pd.read_sql(text("SELECT * FROM dim_producto"), con)
    entrante = productos[["cod_producto", "categoria"] + SCD1_PRODUCTO]
    nuevos = entrante[~entrante["cod_producto"].isin(actual["cod_producto"])]
    if not nuevos.empty:
        nuevos.assign(fecha_actualizacion=hoy, id_carga=id_carga).to_sql(
            "dim_producto", con, if_exists="append", index=False)
    scd1, scd3 = 0, 0
    for fila in entrante.merge(actual, on="cod_producto", suffixes=("", "_actual")).to_dict("records"):
        cambios = {a: fila[a] for a in SCD1_PRODUCTO if _distinto(fila[a], fila[f"{a}_actual"])}
        scd1 += bool(cambios)
        if _distinto(fila["categoria"], fila["categoria_actual"]):
            cambios.update(categoria=fila["categoria"], categoria_anterior=fila["categoria_actual"],
                           fecha_cambio_categoria=hoy)
            scd3 += 1
        if cambios:
            asignaciones = ", ".join(f"{a} = :{a}" for a in cambios)
            con.execute(text(f"""UPDATE dim_producto SET {asignaciones}, fecha_actualizacion = :hoy,
                                 id_carga = :id_carga WHERE cod_producto = :cod"""),
                        {**cambios, "hoy": hoy, "id_carga": id_carga, "cod": fila["cod_producto"]})
    return {"productos_nuevos": len(nuevos), "productos_scd1": scd1, "productos_scd3": scd3}


def _cargar_dim_cliente(con, clientes: pd.DataFrame, sal: str, id_carga: str, hoy: str) -> dict:
    """SCD tipo 2: un cambio de comuna/región o de segmento abre una nueva versión.

    Reglas de supervivencia:
      * comuna 'Sin información' que luego se informa -> se completa en todas
        las versiones (corrección, tipo 1), no es una mudanza;
      * comuna informada que llega vacía -> se conserva la conocida.
    """
    entrante = clientes.assign(id_cliente=clientes["rut"].map(lambda r: rc.seudonimizar(r, sal)))
    entrante = entrante[["id_cliente", "comuna", "region", "zona", "segmento",
                         "fecha_registro", "fecha_actualizacion"]]
    actual = pd.read_sql(text("SELECT * FROM dim_cliente WHERE es_actual = 1 AND sk_cliente <> -1"), con)

    nuevos = entrante[~entrante["id_cliente"].isin(actual["id_cliente"])]
    if not nuevos.empty:
        nuevos.drop(columns="fecha_actualizacion").assign(
            fecha_inicio_vigencia=INICIO_VIGENCIA, fecha_fin_vigencia=FIN_VIGENCIA,
            es_actual=1, version=1, id_carga=id_carga,
        ).to_sql("dim_cliente", con, if_exists="append", index=False)

    completados, corregidos, cierres, versiones = [], [], [], []
    for fila in entrante.merge(actual, on="id_cliente", suffixes=("", "_actual")).to_dict("records"):
        geo = {k: fila[k] for k in ("comuna", "region", "zona")}
        if fila["comuna"] == SIN_INFORMACION:
            geo = {k: fila[f"{k}_actual"] for k in ("comuna", "region", "zona")}
        elif fila["comuna_actual"] == SIN_INFORMACION:
            completados.append({**geo, "id": fila["id_cliente"]})
            fila.update({f"{k}_actual": v for k, v in geo.items()})
        if _distinto(fila["fecha_registro"], fila["fecha_registro_actual"]):
            corregidos.append({"fecha_registro": fila["fecha_registro"], "id": fila["id_cliente"]})

        cambia = _distinto(geo["comuna"], fila["comuna_actual"]) or _distinto(fila["segmento"], fila["segmento_actual"])
        if not cambia:
            continue
        efectiva = fila["fecha_actualizacion"]
        if not efectiva or efectiva <= fila["fecha_inicio_vigencia"]:
            efectiva = hoy
        cierre = (date.fromisoformat(efectiva) - timedelta(days=1)).isoformat()
        cierres.append({"sk": fila["sk_cliente"], "cierre": cierre})
        versiones.append({
            "id_cliente": fila["id_cliente"], **geo, "segmento": fila["segmento"],
            "fecha_registro": fila["fecha_registro"], "fecha_inicio_vigencia": efectiva,
            "fecha_fin_vigencia": FIN_VIGENCIA, "es_actual": 1, "version": fila["version"] + 1,
            "id_carga": id_carga,
        })

    if completados:
        con.execute(text("""UPDATE dim_cliente SET comuna = :comuna, region = :region, zona = :zona
                            WHERE id_cliente = :id"""), completados)
    if corregidos:
        con.execute(text("UPDATE dim_cliente SET fecha_registro = :fecha_registro WHERE id_cliente = :id"),
                    corregidos)
    if cierres:
        con.execute(text("""UPDATE dim_cliente SET fecha_fin_vigencia = :cierre, es_actual = 0
                            WHERE sk_cliente = :sk"""), cierres)
        pd.DataFrame(versiones).to_sql("dim_cliente", con, if_exists="append", index=False)
    return {"clientes_nuevos": len(nuevos), "clientes_scd2_nuevas_versiones": len(versiones),
            "clientes_scd1_comuna_completada": len(completados)}


# --------------------------------------------------------------------- hecho
COLUMNAS_FACT = ["sk_fecha", "sk_cliente", "sk_producto", "sk_sucursal", "sk_canal", "fuente_origen",
                 "numero_documento", "nro_linea", "hora", "cantidad", "precio_unitario", "monto_bruto",
                 "descuento", "monto_neto", "es_devolucion", "id_carga", "archivo_origen", "fila_origen"]
CLAVE_NATURAL = ["fuente_origen", "numero_documento", "nro_linea"]


def _buscar(con, tabla: str, codigo: str, sk: str) -> pd.Series:
    return pd.read_sql(text(f"SELECT {codigo}, {sk} FROM {tabla}"), con).set_index(codigo)[sk]


def _cargar_fact(con, ventas: pd.DataFrame, sal: str, id_carga: str) -> dict:
    v = ventas.reset_index(drop=True).copy()
    v["sk_fecha"] = v["fecha_hora"].dt.strftime("%Y%m%d").astype("int64")
    v["fecha"] = v["fecha_hora"].dt.strftime("%Y-%m-%d")
    v["hora"] = v["fecha_hora"].dt.hour
    v["sk_canal"] = v["cod_canal"].map(_buscar(con, "dim_canal", "cod_canal", "sk_canal"))
    v["sk_sucursal"] = v["cod_sucursal"].map(_buscar(con, "dim_sucursal", "cod_sucursal", "sk_sucursal"))
    v["sk_producto"] = v["cod_producto"].map(_buscar(con, "dim_producto", "cod_producto", "sk_producto"))

    # Cliente (SCD 2): la versión cuya vigencia contiene la fecha de la venta.
    v["id_cliente"] = v["rut_cliente"].map(lambda r: rc.seudonimizar(r, sal) if pd.notna(r) else None)
    versiones = pd.read_sql(text("""SELECT sk_cliente, id_cliente, fecha_inicio_vigencia, fecha_fin_vigencia
                                    FROM dim_cliente WHERE sk_cliente <> -1"""), con)
    cruce = v[["id_cliente", "fecha"]].reset_index().merge(versiones, on="id_cliente")
    cruce = cruce[(cruce["fecha"] >= cruce["fecha_inicio_vigencia"]) & (cruce["fecha"] <= cruce["fecha_fin_vigencia"])]
    v["sk_cliente"] = cruce.set_index("index")["sk_cliente"].reindex(v.index).fillna(-1).astype("int64")
    sin_version = int((v["id_cliente"].notna() & (v["sk_cliente"] == -1)).sum())

    claves = ["sk_canal", "sk_sucursal", "sk_producto"]
    faltantes = v[claves].isna().any(axis=1)
    if faltantes.any():
        raise ValueError(f"{int(faltantes.sum())} ventas sin clave de dimensión: revisar orden de carga")
    v = v.astype({c: "int64" for c in claves}).assign(
        id_carga=id_carga, archivo_origen=v["_archivo"], fila_origen=v["_fila_origen"].astype("int64"))

    # Idempotencia: solo se insertan líneas cuya clave natural aún no está en Gold.
    existentes = pd.read_sql(text("SELECT fuente_origen, numero_documento, nro_linea FROM fact_ventas"), con)
    marca = v.merge(existentes.assign(_ya_cargada=True), on=CLAVE_NATURAL, how="left")
    nuevas = v[marca["_ya_cargada"].isna().to_numpy()]
    if not nuevas.empty:
        nuevas[COLUMNAS_FACT].to_sql("fact_ventas", con, if_exists="append", index=False, chunksize=5000)
    return {"fact_insertadas": len(nuevas), "fact_omitidas": len(v) - len(nuevas),
            "ventas_cliente_sin_version": sin_version}


def refrescar_agregados(con) -> int:
    """Refresca el agregado precalculado (emulación de vista materializada)."""
    con.execute(text("DELETE FROM agg_ventas_mes_region"))
    resultado = con.execute(text("""
        INSERT INTO agg_ventas_mes_region
        SELECT anio_mes, region_sucursal, canal,
               SUM(venta_neta), SUM(monto_devuelto),
               SUM(CASE WHEN es_devolucion = 0 THEN unidades ELSE 0 END),
               COUNT(DISTINCT CASE WHEN es_devolucion = 0 THEN numero_documento END),
               ROUND(SUM(venta_neta) * 1.0 /
                     NULLIF(COUNT(DISTINCT CASE WHEN es_devolucion = 0 THEN numero_documento END), 0)),
               datetime('now', 'localtime')
        FROM vw_ventas GROUP BY anio_mes, region_sucursal, canal"""))
    return resultado.rowcount


def cargar(con, silver, id_carga: str, log) -> dict:
    sal = config.SALT_PSEUDONIMO
    if not sal:
        log.warning("Gold | DR360_SALT_PSEUDONIMO no definido: se usa una sal de desarrollo (no usar en producción)")
        sal = "solo-desarrollo"
    hoy = date.today().isoformat()
    resultado = {"dim_fecha_nuevas": _cargar_dim_fecha(con, silver.ventas)}
    resultado.update(_cargar_dim_sucursal(con, silver.sucursales, id_carga, hoy))
    resultado.update(_cargar_dim_producto(con, silver.productos, id_carga, hoy))
    resultado.update(_cargar_dim_cliente(con, silver.clientes, sal, id_carga, hoy))
    resultado.update(_cargar_fact(con, silver.ventas, sal, id_carga))
    silver.rechazos.to_sql("etl_rechazos", con, if_exists="append", index=False)
    resultado["agregados_refrescados"] = refrescar_agregados(con)
    for clave, valor in resultado.items():
        log.info("Gold   | %-34s | %6d", clave, valor)
    return resultado
