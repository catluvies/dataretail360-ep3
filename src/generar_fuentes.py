"""Genera las fuentes simuladas de DataRetail 360.

Simula los sistemas que describe el caso, cada uno con su formato y con los
problemas de calidad que el caso declara:

    POS de tiendas físicas  -> pos_ventas_tiendas.csv  (CSV con ';')
    Comercio electrónico    -> ecommerce_pedidos.json  (JSON anidado)
    CRM de marketing        -> crm_clientes.db         (base SQLite transaccional)
    ERP / maestro           -> maestro_productos.csv, equivalencias_codigos.csv
    Operaciones             -> sucursales.csv, geografia_comunas.csv

Lote 1 = año 2025 (carga inicial). Lote 2 = primer semestre 2026 (carga
incremental), con cambios en clientes, productos y sucursales que ejercitan
las técnicas SCD.

Uso:  python -m src.generar_fuentes
"""
import json
import sqlite3
import unicodedata
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from . import config
from .reglas_calidad import digito_verificador

# ---------------------------------------------------------------- referencias
GEOGRAFIA = [
    # comuna, región, zona, latitud, longitud
    ("Santiago", "Metropolitana", "Centro", -33.4489, -70.6693),
    ("Providencia", "Metropolitana", "Centro", -33.4314, -70.6093),
    ("Las Condes", "Metropolitana", "Centro", -33.4080, -70.5670),
    ("Maipú", "Metropolitana", "Centro", -33.5100, -70.7570),
    ("Puente Alto", "Metropolitana", "Centro", -33.6110, -70.5750),
    ("La Florida", "Metropolitana", "Centro", -33.5230, -70.5990),
    ("Ñuñoa", "Metropolitana", "Centro", -33.4560, -70.5970),
    ("Valparaíso", "Valparaíso", "Centro", -33.0472, -71.6127),
    ("Viña del Mar", "Valparaíso", "Centro", -33.0245, -71.5518),
    ("Rancagua", "O'Higgins", "Centro", -34.1708, -70.7444),
    ("Talca", "Maule", "Centro", -35.4264, -71.6554),
    ("Concepción", "Biobío", "Sur", -36.8270, -73.0503),
    ("Talcahuano", "Biobío", "Sur", -36.7249, -73.1168),
    ("Temuco", "La Araucanía", "Sur", -38.7359, -72.5904),
    ("Valdivia", "Los Ríos", "Sur", -39.8142, -73.2459),
    ("Puerto Montt", "Los Lagos", "Sur", -41.4689, -72.9411),
    ("Antofagasta", "Antofagasta", "Norte", -23.6509, -70.3975),
    ("Iquique", "Tarapacá", "Norte", -20.2133, -70.1503),
    ("La Serena", "Coquimbo", "Norte", -29.9027, -71.2519),
    ("Coquimbo", "Coquimbo", "Norte", -29.9533, -71.3436),
    ("Arica", "Arica y Parinacota", "Norte", -18.4783, -70.3126),
    ("Punta Arenas", "Magallanes", "Austral", -53.1638, -70.9171),
    ("No aplica", "Canal online", "Online", None, None),
]

SUCURSALES = [
    # código, nombre, tipo, dirección, comuna, apertura
    ("SUC-01", "Santiago Centro", "Tienda calle", "Ahumada 210", "Santiago", "2015-03-01"),
    ("SUC-02", "Providencia", "Tienda calle", "Av. Providencia 2124", "Providencia", "2016-06-15"),
    ("SUC-03", "Mall Las Condes", "Mall", "Av. Kennedy 9001, local 2140", "Las Condes", "2017-11-20"),
    ("SUC-04", "Maipú", "Mall", "Av. Américo Vespucio 399, local 112", "Maipú", "2018-04-10"),
    ("SUC-05", "Puente Alto", "Mall", "Av. Concha y Toro 1477", "Puente Alto", "2019-08-01"),
    ("SUC-06", "Viña del Mar", "Tienda calle", "Av. Valparaíso 551", "Viña del Mar", "2016-09-01"),
    ("SUC-07", "Concepción", "Mall", "Av. Jorge Alessandri 3177", "Concepción", "2018-02-01"),
    ("SUC-08", "Temuco", "Tienda calle", "Av. Alemania 0671", "Temuco", "2020-05-15"),
    ("SUC-09", "Antofagasta", "Mall", "Av. Balmaceda 2355", "Antofagasta", "2019-03-01"),
    ("SUC-10", "La Serena", "Mall", "Av. Alberto Solari 1400", "La Serena", "2021-07-01"),
    ("SUC-11", "Rancagua", "Tienda calle", "Av. Independencia 645", "Rancagua", "2022-01-10"),
    ("SUC-12", "Puerto Montt", "Mall", "Av. Juan Soler Manfredini 11", "Puerto Montt", "2022-10-01"),
    ("SUC-99", "Tienda online", "Virtual", "", "No aplica", "2014-01-01"),
]
# Lote 2: nueva sucursal y corrección de dirección (SCD tipo 1).
SUCURSAL_NUEVA_LOTE2 = ("SUC-13", "Iquique", "Mall", "Av. Héroes de la Concepción 2555", "Iquique", "2026-03-01")
CORRECCION_DIRECCION_LOTE2 = ("SUC-04", "Av. Américo Vespucio 1001, local 112")

CATALOGO = {
    "Tecnología": {
        "Smartphones": (["Smartphone"], ["Samsung", "Xiaomi", "Apple", "Motorola"], (149990, 1299990)),
        "Notebooks": (["Notebook"], ["Lenovo", "HP", "Asus", "Apple"], (349990, 1899990)),
        "Televisores": (['Smart TV 50"', 'Smart TV 55"', 'Smart TV 65"'], ["Samsung", "LG", "TCL", "Sony"], (199990, 1499990)),
        "Audio": (["Audífonos inalámbricos", "Parlante Bluetooth", "Soundbar"], ["JBL", "Sony", "Xiaomi", "Bose"], (19990, 349990)),
    },
    "Hogar": {
        "Electrodomésticos": (["Microondas", "Freidora de aire", "Aspiradora", "Hervidor"], ["Oster", "Thomas", "Mademsa", "Samsung"], (19990, 399990)),
        "Cocina": (["Set de ollas", "Sartén antiadherente", "Batidora", "Juego de cuchillos"], ["Tramontina", "Oster", "Thomas", "DR Home"], (9990, 149990)),
        "Muebles": (["Escritorio", "Silla de oficina", "Repisa", "Mesa de centro"], ["DR Home", "Nórdico", "Madesa"], (39990, 299990)),
        "Decoración": (["Lámpara de pie", "Cojín", "Cuadro decorativo", "Espejo"], ["DR Home", "Nórdico"], (6990, 89990)),
    },
    "Accesorios": {
        "Cables y cargadores": (["Cargador USB-C", "Cable USB-C", "Power bank"], ["Xiaomi", "Belkin", "Samsung", "Anker"], (4990, 49990)),
        "Fundas y protección": (["Funda", "Lámina de vidrio templado"], ["Spigen", "Samsung", "Genérico"], (3990, 29990)),
        "Mochilas": (["Mochila para notebook", "Bolso de viaje"], ["Samsonite", "Targus", "DR Basics"], (19990, 129990)),
        "Smartwatches": (["Smartwatch", "Pulsera de actividad"], ["Apple", "Samsung", "Xiaomi", "Huawei"], (29990, 499990)),
    },
}
PREFIJO_WEB = {"Tecnología": "TEC", "Hogar": "HOG", "Accesorios": "ACC"}
PRODUCTOS_POR_SUBCATEGORIA = 12
PRODUCTOS_NUEVOS_LOTE2 = 10

NOMBRES = ["Juan", "María", "Pedro", "Ana", "Carlos", "Sofía", "Luis", "Camila", "Diego",
           "Valentina", "Jorge", "Francisca", "Matías", "Catalina", "José", "Javiera", "Felipe",
           "Constanza", "Tomás", "Fernanda", "Benjamín", "Isidora", "Cristóbal", "Antonia",
           "Ignacio", "Daniela", "Sebastián", "Paula", "Andrés", "Carolina", "Rodrigo",
           "Macarena", "Nicolás", "Bárbara", "Patricio", "Gabriela", "Héctor", "Rocío",
           "Vicente", "Josefa"]
APELLIDOS = ["González", "Muñoz", "Rojas", "Díaz", "Pérez", "Soto", "Contreras", "Silva",
             "Martínez", "Sepúlveda", "Morales", "Rodríguez", "López", "Fuentes", "Hernández",
             "Torres", "Araya", "Flores", "Espinoza", "Valenzuela", "Castillo", "Tapia", "Reyes",
             "Gutiérrez", "Castro", "Pizarro", "Álvarez", "Vásquez", "Sánchez", "Fernández",
             "Ramírez", "Carrasco", "Gómez", "Cortés", "Herrera", "Núñez", "Jara", "Vergara",
             "Rivera", "Figueroa"]
DOMINIOS = ["gmail.com", "hotmail.com", "outlook.com", "yahoo.com"]
SEGMENTOS = ["Ocasional", "Frecuente", "Nuevo", "VIP"]

PERSONAS_BASE = 1500
PERSONAS_NUEVAS_LOTE2 = 120

PERIODOS = {1: (date(2025, 1, 1), date(2025, 12, 31)), 2: (date(2026, 1, 1), date(2026, 6, 30))}
# Días de alta demanda online (CyberDay y Black Friday simulados).
EVENTOS_ONLINE = {
    date(2025, 6, 2), date(2025, 6, 3), date(2025, 6, 4),
    date(2025, 10, 6), date(2025, 10, 7), date(2025, 10, 8),
    date(2025, 11, 28), date(2026, 6, 1), date(2026, 6, 2), date(2026, 6, 3),
}


# ------------------------------------------------------------------ utilidades
def _ascii(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def _formatear_rut(numero: int, dv: str, rng) -> str:
    estilo = rng.choice(3, p=[0.5, 0.4, 0.1])
    if estilo == 0:
        return f"{numero:,}".replace(",", ".") + f"-{dv}"
    if estilo == 1:
        return f"{numero}-{dv}"
    return f"{numero}{dv}".lower()


def _fecha_aleatoria(rng, inicio: date, fin: date) -> date:
    return inicio + timedelta(days=int(rng.integers(0, (fin - inicio).days + 1)))


def _precio_retail(valor: float) -> int:
    """Redondea al estilo retail: 149.990, 19.990, etc."""
    return int(np.ceil(valor / 1000) * 1000) - 10


class _SelectorClientes:
    """Elige clientes ya registrados a una fecha dada (sin compras antes del registro)."""

    def __init__(self, personas: pd.DataFrame):
        self.personas = personas.sort_values("fecha_registro").reset_index(drop=True)
        self.fechas = self.personas["fecha_registro"].to_numpy()

    def elegir(self, rng, dia: date) -> pd.Series:
        disponibles = int(np.searchsorted(self.fechas, dia.isoformat(), side="right"))
        return self.personas.iloc[int(rng.integers(0, disponibles))]


# --------------------------------------------------------------------- maestro
def _catalogo() -> pd.DataFrame:
    """Catálogo base (igual en ambos lotes) más los productos nuevos del lote 2."""
    rng = np.random.default_rng(config.SEMILLA)
    filas, n = [], 0
    for categoria, subcategorias in CATALOGO.items():
        for subcategoria, (tipos, marcas, (pmin, pmax)) in subcategorias.items():
            precios = np.sort(rng.uniform(pmin, pmax, PRODUCTOS_POR_SUBCATEGORIA))
            for i, precio in enumerate(precios):
                n += 1
                marca = marcas[i % len(marcas)]
                modelo = f"{chr(65 + int(rng.integers(0, 26)))}{int(rng.integers(10, 99))}"
                linea = "Básica" if i < 4 else "Estándar" if i < 8 else "Premium"
                filas.append({
                    "cod_producto": f"P{n:04d}",
                    "sku_web": f"{PREFIJO_WEB[categoria]}-{n:04d}-W",
                    "nombre": f"{tipos[i % len(tipos)]} {marca} {modelo}",
                    "categoria": categoria, "subcategoria": subcategoria, "marca": marca,
                    "linea": linea, "precio_lista": _precio_retail(precio),
                    "nuevo_lote2": False,
                })
    # Productos nuevos del lote 2 (lanzamientos 2026).
    nuevos = [("Tecnología", "Smartphones", "Smartphone", "Samsung", 899990),
              ("Tecnología", "Notebooks", "Notebook", "Lenovo", 1099990),
              ("Tecnología", "Audio", "Audífonos inalámbricos", "Sony", 249990),
              ("Accesorios", "Smartwatches", "Smartwatch", "Xiaomi", 79990),
              ("Accesorios", "Cables y cargadores", "Power bank", "Anker", 39990),
              ("Hogar", "Electrodomésticos", "Freidora de aire", "Thomas", 89990),
              ("Hogar", "Cocina", "Batidora", "Oster", 59990),
              ("Hogar", "Muebles", "Silla de oficina", "DR Home", 129990),
              ("Hogar", "Decoración", "Lámpara de pie", "Nórdico", 49990),
              ("Tecnología", "Televisores", 'Smart TV 55"', "LG", 599990)]
    for categoria, subcategoria, tipo, marca, precio in nuevos:
        n += 1
        filas.append({
            "cod_producto": f"P{n:04d}", "sku_web": f"{PREFIJO_WEB[categoria]}-{n:04d}-W",
            "nombre": f"{tipo} {marca} X{n}", "categoria": categoria, "subcategoria": subcategoria,
            "marca": marca, "linea": "Estándar", "precio_lista": precio, "nuevo_lote2": True,
        })
    return pd.DataFrame(filas)


def _productos_lote(lote: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Devuelve (verdad del negocio, versión como la exporta el ERP)."""
    rng = np.random.default_rng(config.SEMILLA + 11)
    base = _catalogo()
    errores_marca = rng.choice(base.index[~base["nuevo_lote2"]], 5, replace=False)
    textos_sucios = rng.choice(base.index[~base["nuevo_lote2"]], 8, replace=False)
    cambios_precio = rng.choice(base.index[~base["nuevo_lote2"]], 20, replace=False)

    verdad = base if lote == 2 else base[~base["nuevo_lote2"]]
    verdad = verdad.copy()
    if lote == 2:
        # SCD tipo 3: reclasificación de Smartwatches desde Accesorios a Tecnología.
        verdad.loc[verdad["subcategoria"] == "Smartwatches", "categoria"] = "Tecnología"
        # SCD tipo 1: actualización de precios de lista.
        cambia = verdad.index.isin(cambios_precio)
        verdad.loc[cambia, "precio_lista"] = [_precio_retail(p * 1.08) for p in verdad.loc[cambia, "precio_lista"]]

    erp = verdad.copy()
    if lote == 1:
        # Errores de digitación en marca: se corrigen en el lote 2 (SCD tipo 1).
        typos = {"Samsung": "Samsumg", "Xiaomi": "Xiaomy", "Lenovo": "Lenovoo", "Apple": "Aple",
                 "Sony": "Sonny", "LG": "L.G.", "HP": "H P", "Oster": "Ostter"}
        for i in errores_marca:
            erp.loc[i, "marca"] = typos.get(erp.loc[i, "marca"], erp.loc[i, "marca"] + "x")
    for i in textos_sucios:
        if i in erp.index:
            erp.loc[i, "nombre"] = "  " + erp.loc[i, "nombre"].lower().replace(" ", "   ") + " "
    return verdad, erp


def _equivalencias(productos: pd.DataFrame, lote: int) -> pd.DataFrame:
    rng = np.random.default_rng(config.SEMILLA + 12)
    faltantes = rng.choice(productos.index[~productos["nuevo_lote2"]], 4, replace=False)
    sin_homologar = set(faltantes) if lote == 1 else set(faltantes[:2])
    eq = productos.loc[~productos.index.isin(sin_homologar), ["sku_web", "cod_producto"]]
    return eq.reset_index(drop=True)


# ------------------------------------------------------------------- clientes
def _personas() -> pd.DataFrame:
    """Personas reales (la 'verdad'); el CRM las registra con errores."""
    rng = np.random.default_rng(config.SEMILLA + 21)
    total = PERSONAS_BASE + PERSONAS_NUEVAS_LOTE2
    ruts = rng.choice(np.arange(5_000_000, 26_000_000), size=total, replace=False)
    comunas = [g for g in GEOGRAFIA if g[0] != "No aplica"]
    pesos = np.array([3.0 if g[1] == "Metropolitana" else 1.0 for g in comunas])
    pesos /= pesos.sum()
    filas = []
    for i in range(total):
        nombre = NOMBRES[int(rng.integers(0, len(NOMBRES)))]
        ap1, ap2 = rng.choice(APELLIDOS, 2, replace=False)
        if i < PERSONAS_BASE:
            registro = _fecha_aleatoria(rng, date(2019, 1, 1), date(2024, 12, 31))
        else:
            registro = _fecha_aleatoria(rng, date(2026, 1, 2), date(2026, 6, 15))
        dominio = DOMINIOS[int(rng.integers(0, len(DOMINIOS)))]
        filas.append({
            "id_crm": 100000 + i,
            "rut_num": int(ruts[i]), "dv": digito_verificador(int(ruts[i])),
            "nombre": f"{nombre} {ap1} {ap2}",
            "email": f"{_ascii(nombre)}.{_ascii(ap1)}{i}@{dominio}".lower(),
            "telefono": f"9{int(rng.integers(10_000_000, 99_999_999))}",
            "comuna": comunas[int(rng.choice(len(comunas), p=pesos))][0],
            "segmento": rng.choice(SEGMENTOS, p=[0.40, 0.35, 0.15, 0.10]),
            "fecha_registro": registro.isoformat(),
            "fecha_actualizacion": registro.isoformat(),
        })
    return pd.DataFrame(filas)


def _personas_lote(lote: int) -> pd.DataFrame:
    personas = _personas()
    if lote == 1:
        return personas.iloc[:PERSONAS_BASE].copy()
    rng = np.random.default_rng(config.SEMILLA + 22)
    personas = personas.copy()
    region_de = {g[0]: g[1] for g in GEOGRAFIA}
    comunas = [g[0] for g in GEOGRAFIA if g[0] != "No aplica"]
    # SCD tipo 2: 90 clientes se mudan de región durante 2026.
    for i in rng.choice(PERSONAS_BASE, 90, replace=False):
        actual = personas.at[i, "comuna"]
        opciones = [c for c in comunas if region_de[c] != region_de[actual]]
        personas.at[i, "comuna"] = opciones[int(rng.integers(0, len(opciones)))]
        personas.at[i, "fecha_actualizacion"] = _fecha_aleatoria(rng, date(2026, 1, 5), date(2026, 5, 31)).isoformat()
    # SCD tipo 2: 50 clientes cambian de segmento.
    for i in rng.choice(PERSONAS_BASE, 50, replace=False):
        actual = personas.at[i, "segmento"]
        personas.at[i, "segmento"] = rng.choice([s for s in SEGMENTOS if s not in (actual, "Nuevo")])
        fecha = _fecha_aleatoria(rng, date(2026, 1, 5), date(2026, 5, 31)).isoformat()
        personas.at[i, "fecha_actualizacion"] = max(fecha, personas.at[i, "fecha_actualizacion"])
    return personas


def _crm_lote(lote: int, personas: pd.DataFrame) -> pd.DataFrame:
    """Exportación del CRM con los problemas de calidad del caso."""
    rng = np.random.default_rng(config.SEMILLA + 30 + lote)
    crm = personas.copy()
    crm["rut"] = [_formatear_rut(r, d, rng) for r, d in zip(crm["rut_num"], crm["dv"])]
    # Nombres con mayúsculas/minúsculas inconsistentes.
    for i in rng.choice(crm.index, 80, replace=False):
        crm.at[i, "nombre"] = crm.at[i, "nombre"].upper() if rng.random() < 0.5 else crm.at[i, "nombre"].lower()
    # Correos mal formados (validez).
    for i in rng.choice(crm.index, 30, replace=False):
        email = crm.at[i, "email"]
        crm.at[i, "email"] = email.replace("@", "@@") if rng.random() < 0.5 else email.rsplit(".", 1)[0]
    # Comuna vacía (completitud).
    for i in rng.choice(crm.index, 30, replace=False):
        crm.at[i, "comuna"] = ""
    # Duplicados: misma persona registrada otra vez con otro formato (unicidad).
    duplicados = crm.loc[rng.choice(crm.index, 60, replace=False)].copy()
    duplicados["id_crm"] = 900000 + np.arange(len(duplicados)) + lote * 1000
    duplicados["rut"] = [_formatear_rut(r, d, rng) for r, d in zip(duplicados["rut_num"], duplicados["dv"])]
    duplicados["email"] = [e.upper() + " " if rng.random() < 0.5 else e for e in duplicados["email"]]
    duplicados["nombre"] = [_ascii(n) for n in duplicados["nombre"]]
    duplicados["fecha_actualizacion"] = "2018-06-30"  # registro más antiguo: pierde la deduplicación
    # Registros no identificables y RUT con dígito verificador inválido (se rechazan).
    basura = []
    for k in range(8):
        basura.append({"id_crm": 950000 + lote * 100 + k, "rut": "", "nombre": "cliente sin datos",
                       "email": "sin-correo", "telefono": "", "comuna": "", "segmento": "Ocasional",
                       "fecha_registro": "2024-01-01", "fecha_actualizacion": "2024-01-01"})
    for k in range(6):
        numero = int(rng.integers(5_000_000, 25_000_000))
        dv_malo = "1" if digito_verificador(numero) != "1" else "2"
        basura.append({"id_crm": 960000 + lote * 100 + k, "rut": f"{numero}-{dv_malo}",
                       "nombre": "Registro con RUT erróneo", "email": f"rut.erroneo{k}@gmail.com",
                       "telefono": "", "comuna": "Santiago", "segmento": "Ocasional",
                       "fecha_registro": "2024-01-01", "fecha_actualizacion": "2024-01-01"})
    crm = pd.concat([crm, duplicados, pd.DataFrame(basura)], ignore_index=True)
    columnas = config.CONTRATOS["crm_clientes"]
    return crm[columnas].sample(frac=1, random_state=lote).reset_index(drop=True)


# --------------------------------------------------------------------- ventas
def _pos_ventas(lote: int, productos: pd.DataFrame, personas: pd.DataFrame) -> pd.DataFrame:
    rng = np.random.default_rng(config.SEMILLA + 40 + lote)
    inicio, fin = PERIODOS[lote]
    sucursales = [s for s in SUCURSALES if s[2] != "Virtual"]
    if lote == 2:
        sucursales.append(SUCURSAL_NUEVA_LOTE2)
    peso_producto = 1 / np.sqrt(productos["precio_lista"].to_numpy())
    peso_producto /= peso_producto.sum()
    selector = _SelectorClientes(personas)
    filas, correlativo = [], 1 if lote == 1 else 500_000
    dia = inicio
    while dia <= fin:
        factor = (1.4 if dia.weekday() >= 5 else 1.0) * (1.6 if dia.month == 12 else 1.0)
        for cod, _, tipo, _, _, apertura in sucursales:
            if dia < date.fromisoformat(apertura):
                continue
            for _ in range(rng.poisson((3.0 if tipo == "Mall" else 2.0) * factor)):
                correlativo += 1
                boleta = f"B{cod[-2:]}-{correlativo:07d}"
                momento = datetime.combine(dia, datetime.min.time()) + timedelta(
                    hours=int(rng.integers(10, 21)), minutes=int(rng.integers(0, 60)))
                estado = rng.choice(["COMPLETADA", "ANULADA", "DEVUELTA"], p=[0.95, 0.025, 0.025])
                rut = ""
                if rng.random() < 0.65:
                    persona = selector.elegir(rng, dia)
                    rut = _formatear_rut(persona["rut_num"], persona["dv"], rng)
                for linea in range(1, int(rng.choice([1, 2, 3, 4], p=[0.55, 0.28, 0.12, 0.05])) + 1):
                    producto = productos.iloc[int(rng.choice(len(productos), p=peso_producto))]
                    cantidad = int(rng.choice([1, 2, 3], p=[0.85, 0.12, 0.03]))
                    precio = int(producto["precio_lista"])
                    descuento = 0
                    if rng.random() < 0.2:
                        descuento = int(round(precio * cantidad * rng.choice([5, 10, 15, 20]) / 100, -1))
                    filas.append({
                        "nro_boleta": boleta, "linea": linea, "momento": momento,
                        "cod_sucursal": cod, "rut_cliente": rut,
                        "cod_producto": producto["cod_producto"], "cantidad": cantidad,
                        "precio": precio, "descuento": descuento, "estado": estado,
                    })
        dia += timedelta(days=1)
    df = pd.DataFrame(filas)

    # Formatos de fecha mezclados (validez).
    formato = rng.choice(3, size=len(df), p=[0.85, 0.10, 0.05])
    df["fecha_hora"] = np.select(
        [formato == 0, formato == 1],
        [df["momento"].dt.strftime("%d/%m/%Y %H:%M"), df["momento"].dt.strftime("%Y-%m-%d %H:%M:%S")],
        df["momento"].dt.strftime("%d-%m-%Y %H:%M"))
    # Montos exportados a veces con formato de moneda.
    con_signo = rng.random(len(df)) < 0.15
    df["precio_unitario"] = np.where(
        con_signo, ["$" + f"{p:,}".replace(",", ".") for p in df["precio"]], df["precio"].astype(str))
    # Estados escritos de distintas formas.
    variantes = rng.random(len(df))
    df["estado"] = np.where(variantes < 0.05, df["estado"].str.lower(),
                            np.where(variantes < 0.08, df["estado"].str.title() + " ", df["estado"]))
    df["cantidad"] = df["cantidad"].astype(str)
    df["descuento"] = df["descuento"].astype(str)
    df = df.drop(columns=["momento", "precio"])

    def marcar(n, columna, valor):
        idx = rng.choice(df.index, n, replace=False)
        df.loc[idx, columna] = valor(idx) if callable(valor) else valor

    anio = inicio.year
    marcar(12, "fecha_hora", lambda idx: [rng.choice([f"30/02/{anio} 13:10", f"31/09/{anio} 11:00",
                                                       f"{anio}-13-05 10:00:00", "sin fecha"]) for _ in idx])
    marcar(15, "precio_unitario", lambda idx: ["-" + df.at[i, "precio_unitario"].lstrip("$") for i in idx])
    marcar(6, "precio_unitario", "99999999")
    marcar(6, "cantidad", "0")
    marcar(10, "cod_producto", "")
    marcar(8, "cod_producto", "P9999")
    # Ventas sin sucursal asociada (completitud): boletas completas.
    sin_sucursal = rng.choice(df["nro_boleta"].unique(), int(df["nro_boleta"].nunique() * 0.008), replace=False)
    df.loc[df["nro_boleta"].isin(sin_sucursal), "cod_sucursal"] = ""
    # Líneas duplicadas por doble exportación (unicidad).
    df = pd.concat([df, df.sample(frac=0.005, random_state=lote)], ignore_index=True)
    return df[config.CONTRATOS["pos_ventas"]]


def _pedidos_web(lote: int, productos: pd.DataFrame, personas: pd.DataFrame) -> list[dict]:
    rng = np.random.default_rng(config.SEMILLA + 50 + lote)
    inicio, fin = PERIODOS[lote]
    peso_producto = 1 / np.sqrt(productos["precio_lista"].to_numpy())
    peso_producto /= peso_producto.sum()
    selector = _SelectorClientes(personas)
    pedidos, correlativo = [], 0 if lote == 1 else 300_000
    dia = inicio
    while dia <= fin:
        tasa = 12 * (1.8 if dia.month == 12 else 1.0) * (3.0 if dia in EVENTOS_ONLINE else 1.0)
        for _ in range(rng.poisson(tasa)):
            correlativo += 1
            momento = datetime.combine(dia, datetime.min.time()) + timedelta(seconds=int(rng.integers(0, 86400)))
            if rng.random() < 0.88:
                persona = selector.elegir(rng, dia)
                email = persona["email"].upper() if rng.random() < 0.15 else persona["email"]
                rut = f"{persona['rut_num']}-{persona['dv']}" if rng.random() < 0.4 else None
            else:
                email, rut = f"invitado{correlativo}@correo.cl", None
            items = []
            for _ in range(int(rng.choice([1, 2, 3], p=[0.7, 0.22, 0.08]))):
                producto = productos.iloc[int(rng.choice(len(productos), p=peso_producto))]
                cantidad = int(rng.choice([1, 2], p=[0.9, 0.1]))
                precio = int(producto["precio_lista"])
                descuento = int(round(precio * cantidad * 0.1, -1)) if rng.random() < 0.3 else 0
                items.append({"sku_web": producto["sku_web"], "cantidad": cantidad,
                              "precio_unitario": precio, "descuento": descuento})
            pedidos.append({
                "pedido_id": f"WEB-{correlativo:07d}",
                "fecha": momento.isoformat(timespec="seconds"),
                "canal": "WEB" if rng.random() < 0.62 else "APP",
                "cliente": {"email": email, "rut": rut},
                "items": items,
                "estado": rng.choice(["PAGADO", "ANULADO", "DEVUELTO"], p=[0.94, 0.03, 0.03]),
            })
        dia += timedelta(days=1)
    for i in rng.choice(len(pedidos), 5, replace=False):
        pedidos[i]["fecha"] = None
    for i in rng.choice(len(pedidos), 6, replace=False):
        pedidos[i]["items"][0]["precio_unitario"] *= -1
    for i in rng.choice(len(pedidos), 4, replace=False):
        pedidos[i]["items"][0]["cantidad"] = 0
    return pedidos


# ---------------------------------------------------------------- escritura
def generar(lote: int) -> None:
    destino = config.FUENTES / f"lote_{lote}"
    destino.mkdir(parents=True, exist_ok=True)

    productos, erp = _productos_lote(lote)
    personas = _personas_lote(lote)
    equivalencias = _equivalencias(productos, lote)

    erp[config.CONTRATOS["maestro_productos"]].to_csv(destino / "maestro_productos.csv", index=False)
    equivalencias.to_csv(destino / "equivalencias_codigos.csv", index=False)

    sucursales = pd.DataFrame(SUCURSALES + ([SUCURSAL_NUEVA_LOTE2] if lote == 2 else []),
                              columns=["cod_sucursal", "nombre", "tipo", "direccion", "comuna", "fecha_apertura"])
    if lote == 2:
        cod, direccion = CORRECCION_DIRECCION_LOTE2
        sucursales.loc[sucursales["cod_sucursal"] == cod, "direccion"] = direccion
    sucursales.to_csv(destino / "sucursales.csv", index=False)
    pd.DataFrame(GEOGRAFIA, columns=config.CONTRATOS["geografia_comunas"]).to_csv(
        destino / "geografia_comunas.csv", index=False)

    crm = _crm_lote(lote, personas)
    ruta_crm = destino / "crm_clientes.db"
    ruta_crm.unlink(missing_ok=True)
    with sqlite3.connect(ruta_crm) as conexion:
        crm.to_sql("clientes", conexion, index=False)

    _pos_ventas(lote, productos, personas).to_csv(destino / "pos_ventas_tiendas.csv", sep=";", index=False)
    pedidos = _pedidos_web(lote, productos, personas)
    (destino / "ecommerce_pedidos.json").write_text(
        json.dumps(pedidos, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> None:
    for lote in (1, 2):
        generar(lote)
        print(f"Fuentes del lote {lote} generadas en {config.FUENTES / f'lote_{lote}'}")


if __name__ == "__main__":
    main()
