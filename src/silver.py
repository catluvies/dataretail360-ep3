"""Capa Silver: dato validado, deduplicado y homologado.

Aplica las reglas del diagnóstico de calidad de la EP1. Cada fila que no pasa
una regla va a la tabla de rechazos con su código y motivo; las filas que se
descartan por regla de negocio (duplicados, transacciones anuladas) quedan
como EXCLUSION. Así se cumple: filas leídas = válidas + rechazadas + excluidas.
"""
import json
from dataclasses import dataclass, field

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from . import config
from . import reglas_calidad as rc

CAMPOS_PERSONALES = {"rut", "rut_cliente", "email", "email_cliente", "nombre", "telefono", "cliente"}
COLUMNAS_WEB = ["pedido_id", "fecha", "canal", "estado", "email_cliente", "rut_cliente",
                "nro_linea", "sku_web", "cantidad", "precio_unitario", "descuento"]
CANALES_VALIDOS = {"TIENDA", "WEB", "APP"}
SUCURSAL_ONLINE = "SUC-99"


class RegistroRechazos:
    """Tabla de rechazos: cada fila descartada queda registrada con su motivo."""

    def __init__(self, id_carga: str):
        self.id_carga = id_carga
        self._partes: list[pd.DataFrame] = []

    def agregar(self, df: pd.DataFrame, entidad: str, regla: str, motivo: str,
                columna_clave: str, columnas_origen: list[str], tipo: str = "RECHAZO") -> None:
        if df.empty:
            return
        registros = []
        for fila in df[columnas_origen].to_dict("records"):
            limpio = {}
            for clave, valor in fila.items():
                valor = None if pd.isna(valor) else str(valor)
                limpio[clave] = rc.enmascarar(valor) if clave in CAMPOS_PERSONALES else valor
            registros.append(json.dumps(limpio, ensure_ascii=False))
        self._partes.append(pd.DataFrame({
            "id_carga": self.id_carga, "tipo": tipo, "entidad": entidad, "regla": regla,
            "motivo": motivo, "archivo_origen": df["_archivo"].to_numpy(),
            "fila_origen": df["_fila_origen"].astype(int).to_numpy(),
            "clave_registro": df[columna_clave].astype("string").to_numpy(),
            "registro": registros,
        }))

    def como_df(self) -> pd.DataFrame:
        columnas = ["id_carga", "tipo", "entidad", "regla", "motivo", "archivo_origen",
                    "fila_origen", "clave_registro", "registro"]
        if not self._partes:
            return pd.DataFrame(columns=columnas)
        return pd.concat(self._partes, ignore_index=True)[columnas]


@dataclass
class ResultadoSilver:
    lote: int
    clientes: pd.DataFrame
    productos: pd.DataFrame
    sucursales: pd.DataFrame
    ventas: pd.DataFrame
    rechazos: pd.DataFrame
    conteos: dict = field(default_factory=dict)


def _aplicar_reglas(df, reglas, rechazos, entidad, clave, columnas_origen, tipo="RECHAZO"):
    """Evalúa las reglas en orden; cada fila se rechaza por la primera regla que no cumple."""
    for codigo, motivo, es_invalida in reglas:
        mascara = es_invalida(df).fillna(True).astype(bool)
        rechazos.agregar(df[mascara], entidad, codigo, motivo, clave, columnas_origen, tipo)
        df = df[~mascara]
    return df


# -------------------------------------------------------------- dimensiones
def _geografia(geo: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "comuna": rc.normalizar_texto(geo["comuna"]),
        "region": rc.normalizar_texto(geo["region"]),
        "zona": rc.normalizar_texto(geo["zona"]),
        "latitud": pd.to_numeric(geo["latitud"], errors="coerce"),
        "longitud": pd.to_numeric(geo["longitud"], errors="coerce"),
    }).drop_duplicates("comuna")


def _clientes(crm: pd.DataFrame, geografia: pd.DataFrame, rechazos: RegistroRechazos) -> tuple[pd.DataFrame, dict]:
    origen = config.CONTRATOS["crm_clientes"]
    df = crm.copy()
    df["rut_norm"] = df["rut"].map(rc.normalizar_rut)
    df["rut_ok"] = df["rut_norm"].map(rc.rut_valido)
    df = _aplicar_reglas(df, [
        ("CLI-01", "Cliente sin RUT: no es identificable", lambda d: d["rut_norm"].isna()),
        ("CLI-02", "RUT con dígito verificador inválido", lambda d: ~d["rut_ok"].astype(bool)),
    ], rechazos, "cliente", "id_crm", origen)

    df["email_norm"] = rc.normalizar_email(df["email"])
    invalido = ~rc.email_valido(df["email_norm"])
    df.loc[invalido, "email_norm"] = pd.NA  # se anula el correo, el cliente sigue siendo válido
    df["comuna_norm"] = rc.normalizar_texto(df["comuna"]).fillna("Sin información")
    df["fecha_act"] = pd.to_datetime(df["fecha_actualizacion"], errors="coerce")

    # Unicidad: una fila por RUT; gana la actualización más reciente del CRM.
    df = df.sort_values(["rut_norm", "fecha_act", "id_crm"], ascending=[True, False, True])
    duplicado = df.duplicated("rut_norm", keep="first")
    rechazos.agregar(df[duplicado], "cliente", "CLI-03",
                     "Registro duplicado del mismo RUT: se conserva el más reciente",
                     "id_crm", origen, tipo="EXCLUSION")
    df = df[~duplicado]

    df = df.merge(geografia[["comuna", "region", "zona"]], left_on="comuna_norm", right_on="comuna",
                  how="left", suffixes=("", "_geo"))
    salida = pd.DataFrame({
        "rut": df["rut_norm"].astype("string"),
        "email": df["email_norm"],
        "nombre": rc.nombre_propio(df["nombre"]),
        "comuna": df["comuna_norm"],
        "region": df["region"].fillna("Sin información"),
        "zona": df["zona"].fillna("Sin información"),
        "segmento": rc.normalizar_texto(df["segmento"]).fillna("Sin segmento"),
        "fecha_registro": pd.to_datetime(df["fecha_registro"], errors="coerce").dt.strftime("%Y-%m-%d"),
        "fecha_actualizacion": df["fecha_act"].dt.strftime("%Y-%m-%d"),
        "id_crm": df["id_crm"],
        "_id_carga": df["_id_carga"], "_archivo": df["_archivo"], "_fila_origen": df["_fila_origen"],
    }).reset_index(drop=True)
    avisos = {"correos_invalidos_anulados": int(invalido.sum()),
              "clientes_sin_comuna": int((salida["comuna"] == "Sin información").sum())}
    return salida, avisos


def _productos(maestro: pd.DataFrame, equivalencias: pd.DataFrame, rechazos: RegistroRechazos) -> pd.DataFrame:
    origen = config.CONTRATOS["maestro_productos"]
    df = maestro.copy()
    df["cod"] = rc.normalizar_texto(df["cod_producto"]).str.upper()
    df["precio_n"] = rc.parsear_monto(df["precio_lista"])
    df = _aplicar_reglas(df, [
        ("PRD-01", "Producto sin código", lambda d: d["cod"].isna()),
        ("PRD-02", "Precio de lista no positivo o ilegible", lambda d: ~(d["precio_n"] > 0)),
    ], rechazos, "producto", "cod_producto", origen)
    duplicado = df.duplicated("cod", keep="last")
    rechazos.agregar(df[duplicado], "producto", "PRD-03", "Código de producto repetido en el maestro",
                     "cod_producto", origen, tipo="EXCLUSION")
    df = df[~duplicado]

    nombre = rc.normalizar_texto(df["nombre"])
    en_minusculas = nombre == nombre.str.lower()
    nombre = nombre.where(~en_minusculas, nombre.str.title())

    eq = pd.DataFrame({"sku_web": rc.normalizar_texto(equivalencias["sku_web"]).str.upper(),
                       "cod": rc.normalizar_texto(equivalencias["cod_producto"]).str.upper()})
    eq = eq.dropna().drop_duplicates("cod")
    salida = pd.DataFrame({
        "cod_producto": df["cod"], "nombre_producto": nombre,
        "marca": rc.normalizar_texto(df["marca"]), "linea": rc.normalizar_texto(df["linea"]),
        "categoria": rc.normalizar_texto(df["categoria"]),
        "subcategoria": rc.normalizar_texto(df["subcategoria"]),
        "precio_lista": df["precio_n"].astype("int64"),
        "_id_carga": df["_id_carga"], "_archivo": df["_archivo"], "_fila_origen": df["_fila_origen"],
    }).merge(eq.rename(columns={"cod": "cod_producto"}), on="cod_producto", how="left")
    return salida.reset_index(drop=True)


def _sucursales(sucursales: pd.DataFrame, geografia: pd.DataFrame, rechazos: RegistroRechazos) -> pd.DataFrame:
    origen = config.CONTRATOS["sucursales"]
    df = sucursales.copy()
    df["cod"] = rc.normalizar_texto(df["cod_sucursal"]).str.upper()
    df["comuna_norm"] = rc.normalizar_texto(df["comuna"])
    comunas = set(geografia["comuna"])
    df = _aplicar_reglas(df, [
        ("SUC-01", "Sucursal sin código", lambda d: d["cod"].isna()),
        ("SUC-02", "Comuna de la sucursal no existe en la tabla geográfica",
         lambda d: ~d["comuna_norm"].isin(comunas)),
    ], rechazos, "sucursal", "cod_sucursal", origen)
    df = df.merge(geografia, left_on="comuna_norm", right_on="comuna", how="left", suffixes=("_src", ""))
    return pd.DataFrame({
        "cod_sucursal": df["cod"], "nombre_sucursal": rc.normalizar_texto(df["nombre"]),
        "tipo_sucursal": rc.normalizar_texto(df["tipo"]),
        "direccion": rc.normalizar_texto(df["direccion"]).fillna("No aplica"),
        "comuna": df["comuna_norm"], "region": df["region"], "zona": df["zona"], "pais": "Chile",
        "latitud": df["latitud"], "longitud": df["longitud"],
        "fecha_apertura": pd.to_datetime(df["fecha_apertura"], errors="coerce").dt.strftime("%Y-%m-%d"),
        "_id_carga": df["_id_carga"], "_archivo": df["_archivo"], "_fila_origen": df["_fila_origen"],
    }).reset_index(drop=True)


# ------------------------------------------------------------------- ventas
def _reglas_calidad_venta(sucursales: pd.DataFrame, productos: pd.DataFrame) -> list:
    cod_sucursales = set(sucursales["cod_sucursal"])
    cod_productos = set(productos["cod_producto"])
    return [
        ("VEN-04", "Fecha inválida o con formato no reconocido", lambda d: d["fecha_dt"].isna()),
        ("VEN-05", "Venta sin sucursal asociada", lambda d: d["cod_suc"].isna()),
        ("VEN-06", "Sucursal inexistente en el maestro", lambda d: ~d["cod_suc"].isin(cod_sucursales)),
        ("VEN-07", "Venta sin código de producto", lambda d: d["cod_prod"].isna()),
        ("VEN-08", "Producto inexistente en el maestro", lambda d: ~d["cod_prod"].isin(cod_productos)),
        ("VEN-10", "Cantidad fuera de rango (cero, negativa o excesiva)",
         lambda d: ~d["cantidad_n"].between(1, config.CANTIDAD_MAXIMA_LINEA)),
        ("VEN-11", "Precio unitario no positivo o ilegible", lambda d: ~(d["precio_n"] > 0)),
        ("VEN-12", "Monto de la línea fuera de rango",
         lambda d: d["cantidad_n"] * d["precio_n"] > config.MONTO_MAXIMO_LINEA),
        ("VEN-13", "Descuento negativo o mayor al monto bruto",
         lambda d: (d["descuento_n"] < 0) | (d["descuento_n"] > d["cantidad_n"] * d["precio_n"])),
    ]


def _reglas_estado(df, rechazos, clave, origen):
    df = _aplicar_reglas(df, [
        ("VEN-02", "Estado de transacción no reconocido", lambda d: d["estado_n"].isna()),
    ], rechazos, "venta", clave, origen)
    return _aplicar_reglas(df, [
        ("VEN-03", "Transacción anulada: no constituye venta", lambda d: d["estado_n"] == "ANULADA"),
    ], rechazos, "venta", clave, origen, tipo="EXCLUSION")


def _salida_ventas(df: pd.DataFrame, fuente: str, documento: str) -> pd.DataFrame:
    cantidad = df["cantidad_n"].astype("int64")
    precio = df["precio_n"].astype("int64")
    descuento = df["descuento_n"].astype("int64")
    return pd.DataFrame({
        "fuente_origen": fuente,
        "numero_documento": df[documento].astype("string"),
        "nro_linea": df["nro_linea"].astype("int64"),
        "fecha_hora": df["fecha_dt"],
        "cod_sucursal": df["cod_suc"], "cod_canal": df["cod_canal"],
        "rut_cliente": df["rut_resuelto"].astype("string"),
        "cod_producto": df["cod_prod"],
        "cantidad": cantidad, "precio_unitario": precio,
        "monto_bruto": cantidad * precio, "descuento": descuento,
        "monto_neto": cantidad * precio - descuento,
        "es_devolucion": (df["estado_n"] == "DEVUELTA").astype("int64"),
        "_id_carga": df["_id_carga"], "_archivo": df["_archivo"], "_fila_origen": df["_fila_origen"],
    })


def _ventas_pos(pos, sucursales, productos, ruts_clientes, rechazos) -> tuple[pd.DataFrame, int]:
    origen = config.CONTRATOS["pos_ventas"]
    df = pos.copy()
    df["_clave"] = df["nro_boleta"] + "#" + df["linea"]
    duplicado = df.duplicated(subset=origen, keep="first")
    rechazos.agregar(df[duplicado], "venta", "VEN-01", "Línea duplicada (doble exportación)",
                     "_clave", origen, tipo="EXCLUSION")
    df = df[~duplicado].copy()

    df["estado_n"] = rc.normalizar_estado(df["estado"])
    df["fecha_dt"] = rc.parsear_fecha(df["fecha_hora"])
    df["cod_suc"] = rc.normalizar_texto(df["cod_sucursal"]).str.upper()
    df["cod_prod"] = rc.normalizar_texto(df["cod_producto"]).str.upper()
    df["cantidad_n"] = pd.to_numeric(df["cantidad"], errors="coerce")
    df["precio_n"] = rc.parsear_monto(df["precio_unitario"])
    df["descuento_n"] = rc.parsear_monto(df["descuento"]).fillna(0)
    df["nro_linea"] = pd.to_numeric(df["linea"], errors="coerce")
    df["cod_canal"] = "TIENDA"

    df = _reglas_estado(df, rechazos, "_clave", origen)
    df = _aplicar_reglas(df, _reglas_calidad_venta(sucursales, productos), rechazos, "venta", "_clave", origen)

    rut = df["rut_cliente"].map(rc.normalizar_rut)
    conocido = rut.isin(ruts_clientes)
    df["rut_resuelto"] = rut.where(conocido)
    rut_no_encontrado = int((rut.notna() & ~conocido).sum())
    return _salida_ventas(df, "POS", "nro_boleta"), rut_no_encontrado


def _lineas_web(pedidos: pd.DataFrame) -> pd.DataFrame:
    """Desanida los pedidos: una fila por item (el grano del modelo)."""
    filas = []
    for pedido in pedidos.to_dict("records"):
        cliente = json.loads(pedido["cliente"]) if pd.notna(pedido["cliente"]) else None
        cliente = cliente or {}
        items = json.loads(pedido["items"]) if pd.notna(pedido["items"]) else []
        for numero, item in enumerate(items or [], start=1):
            filas.append({
                "pedido_id": pedido["pedido_id"], "fecha": pedido["fecha"], "canal": pedido["canal"],
                "estado": pedido["estado"], "email_cliente": cliente.get("email"),
                "rut_cliente": cliente.get("rut"), "nro_linea": numero,
                "sku_web": item.get("sku_web"), "cantidad": item.get("cantidad"),
                "precio_unitario": item.get("precio_unitario"), "descuento": item.get("descuento"),
                "_id_carga": pedido["_id_carga"], "_archivo": pedido["_archivo"],
                "_fila_origen": pedido["_fila_origen"],
            })
    return pd.DataFrame(filas).astype("string")


def _ventas_web(pedidos, sucursales, productos, clientes, rechazos) -> tuple[pd.DataFrame, int]:
    df = _lineas_web(pedidos)
    df["_clave"] = df["pedido_id"] + "#" + df["nro_linea"]
    duplicado = df.duplicated(subset=["pedido_id", "nro_linea"], keep="first")
    rechazos.agregar(df[duplicado], "venta", "VEN-01", "Línea duplicada (doble exportación)",
                     "_clave", COLUMNAS_WEB, tipo="EXCLUSION")
    df = df[~duplicado].copy()

    df["estado_n"] = rc.normalizar_estado(df["estado"])
    df["fecha_dt"] = rc.parsear_fecha(df["fecha"])
    df["cod_canal"] = rc.normalizar_texto(df["canal"]).str.upper()
    df["cod_suc"] = SUCURSAL_ONLINE
    df["sku"] = rc.normalizar_texto(df["sku_web"]).str.upper()
    homologacion = productos.dropna(subset=["sku_web"]).set_index("sku_web")["cod_producto"]
    df["cod_prod"] = df["sku"].map(homologacion)
    df["cantidad_n"] = pd.to_numeric(df["cantidad"], errors="coerce")
    df["precio_n"] = pd.to_numeric(df["precio_unitario"], errors="coerce")
    df["descuento_n"] = pd.to_numeric(df["descuento"], errors="coerce").fillna(0)
    df["nro_linea"] = pd.to_numeric(df["nro_linea"], errors="coerce")

    df = _reglas_estado(df, rechazos, "_clave", COLUMNAS_WEB)
    df = _aplicar_reglas(df, [
        ("VEN-14", "Canal digital no reconocido", lambda d: ~d["cod_canal"].isin(CANALES_VALIDOS)),
        ("VEN-09", "Producto web sin homologar (SKU sin equivalencia en el maestro)",
         lambda d: d["sku"].notna() & d["cod_prod"].isna()),
    ], rechazos, "venta", "_clave", COLUMNAS_WEB)
    df = _aplicar_reglas(df, _reglas_calidad_venta(sucursales, productos), rechazos, "venta", "_clave", COLUMNAS_WEB)

    # Cliente: primero por correo (como lo identifica el e-commerce), luego por RUT.
    por_email = clientes.dropna(subset=["email"]).set_index("email")["rut"]
    rut_por_email = rc.normalizar_email(df["email_cliente"]).map(por_email)
    rut_directo = df["rut_cliente"].map(rc.normalizar_rut)
    rut_directo = rut_directo.where(rut_directo.isin(set(clientes["rut"])))
    df["rut_resuelto"] = rut_por_email.fillna(rut_directo)
    no_identificados = int(df["rut_resuelto"].isna().sum())
    return _salida_ventas(df, "ECOMMERCE", "pedido_id"), no_identificados


# ------------------------------------------------------------------ escritura
def _escribir(df: pd.DataFrame, entidad: str, lote: int) -> None:
    destino = config.SILVER / entidad
    destino.mkdir(parents=True, exist_ok=True)
    df.to_parquet(destino / f"lote={lote}.parquet", index=False)


def _escribir_ventas_particionadas(ventas: pd.DataFrame, lote: int) -> None:
    """Particiona por año y mes: una consulta por período lee solo su carpeta."""
    base = config.SILVER / "ventas"
    for previo in base.glob(f"anio=*/mes=*/lote{lote}-*.parquet"):
        previo.unlink()  # re-ejecutar el lote reemplaza sus archivos (idempotencia)
    tabla = pa.Table.from_pandas(ventas.assign(
        anio=ventas["fecha_hora"].dt.strftime("%Y"), mes=ventas["fecha_hora"].dt.strftime("%m")),
        preserve_index=False)
    pq.write_to_dataset(tabla, base, partition_cols=["anio", "mes"],
                        basename_template=f"lote{lote}-{{i}}.parquet",
                        existing_data_behavior="overwrite_or_ignore")


def transformar(bronze: dict[str, pd.DataFrame], lote: int, id_carga: str, log) -> ResultadoSilver:
    rechazos = RegistroRechazos(id_carga)
    geografia = _geografia(bronze["geografia_comunas"])
    clientes, avisos = _clientes(bronze["crm_clientes"], geografia, rechazos)
    productos = _productos(bronze["maestro_productos"], bronze["equivalencias_codigos"], rechazos)
    sucursales = _sucursales(bronze["sucursales"], geografia, rechazos)

    lineas_pos, lineas_web = len(bronze["pos_ventas"]), len(_lineas_web(bronze["ecommerce_pedidos"]))
    ventas_pos, rut_no_encontrado = _ventas_pos(bronze["pos_ventas"], sucursales, productos,
                                                set(clientes["rut"]), rechazos)
    ventas_web, web_sin_cliente = _ventas_web(bronze["ecommerce_pedidos"], sucursales, productos,
                                              clientes, rechazos)
    ventas = pd.concat([ventas_pos, ventas_web], ignore_index=True)
    tabla_rechazos = rechazos.como_df()

    for entidad, df in {"clientes": clientes, "productos": productos, "sucursales": sucursales,
                        "rechazos": tabla_rechazos}.items():
        _escribir(df, entidad, lote)
    _escribir_ventas_particionadas(ventas, lote)

    de_ventas = tabla_rechazos[tabla_rechazos["entidad"] == "venta"]
    conteos = {
        "lineas_leidas": lineas_pos + lineas_web,
        "lineas_validas": len(ventas),
        "lineas_rechazadas": int((de_ventas["tipo"] == "RECHAZO").sum()),
        "lineas_excluidas": int((de_ventas["tipo"] == "EXCLUSION").sum()),
        "clientes_leidos": len(bronze["crm_clientes"]),
        "clientes_validos": len(clientes),
        "ventas_pos_rut_sin_match": rut_no_encontrado,
        "ventas_web_sin_cliente": web_sin_cliente,
        **avisos,
    }
    for (tipo, regla, motivo), n in tabla_rechazos.groupby(["tipo", "regla", "motivo"]).size().items():
        log.info("Silver | %-9s | %-6s | %5d | %s", tipo, regla, n, motivo)
    log.info("Silver | ventas: %d leídas = %d válidas + %d rechazadas + %d excluidas",
             conteos["lineas_leidas"], conteos["lineas_validas"],
             conteos["lineas_rechazadas"], conteos["lineas_excluidas"])
    log.info("Silver | clientes: %d registros CRM -> %d clientes únicos | avisos: %s",
             conteos["clientes_leidos"], conteos["clientes_validos"], avisos)
    return ResultadoSilver(lote, clientes, productos, sucursales, ventas, tabla_rechazos, conteos)
