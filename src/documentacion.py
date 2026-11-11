"""Genera la documentación del modelo a partir del esquema real de Gold.

    docs/modelo_estrella.png        diagrama de la constelación (Ventas + Inventario)
    docs/modelo_estrella.drawio     el mismo diagrama, editable en diagrams.net
    docs/arquitectura_medallion.png flujo Fuentes -> Bronze -> Silver -> Gold -> Consumo
    docs/diccionario_datos.md       diccionario de datos, métricas y reglas para IA

Uso (después de correr el pipeline):  python -m src.documentacion
"""
import json
from xml.sax.saxutils import escape

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
from sqlalchemy import inspect

from . import config, gold

TABLAS_MODELO = ["fact_ventas", "fact_inventario", "dim_fecha", "dim_cliente", "dim_producto",
                 "dim_sucursal", "dim_canal"]
HECHOS = [t for t in TABLAS_MODELO if t.startswith("fact")]
COLORES = {"hecho": "#1f3a5f", "dimension": "#2a7f62", "texto": "#1d1d1f", "borde": "#8a8f98",
           "fondo_fila": "#ffffff", "scd": "#b4531c", "linaje": "#6b7280"}


def _semantica() -> dict:
    return json.loads((config.DOCS / "capa_semantica.json").read_text(encoding="utf-8"))


def _relaciones(engine) -> dict[str, list[str]]:
    """Dimensiones a las que apunta cada hecho, leídas de sus claves foráneas."""
    inspector = inspect(engine)
    return {hecho: [f["referred_table"] for f in inspector.get_foreign_keys(hecho)] for hecho in HECHOS}


def _esquema(engine) -> dict:
    """Columnas, PK y FK de cada tabla, leídas desde la base de datos."""
    inspector = inspect(engine)
    esquema = {}
    for tabla in TABLAS_MODELO:
        pk = set(inspector.get_pk_constraint(tabla)["constrained_columns"])
        fk = {c for f in inspector.get_foreign_keys(tabla) for c in f["constrained_columns"]}
        esquema[tabla] = [{"nombre": c["name"], "tipo": str(c["type"]),
                           "pk": c["name"] in pk, "fk": c["name"] in fk}
                          for c in inspector.get_columns(tabla)]
    return esquema


def _marca(columna: dict, rol: str) -> str:
    if columna["pk"]:
        return "PK"
    if columna["fk"]:
        return "FK"
    if "SCD2" in rol:
        return "S2"
    if "SCD3" in rol:
        return "S3"
    return ""


# ------------------------------------------------------- diagrama estrella
POSICIONES = {  # (x, y) de la esquina superior izquierda, en unidades del lienzo
    # Izquierda: dimensiones solo de Ventas. Centro: dimensiones conformadas compartidas.
    "dim_cliente": (2, 96), "dim_canal": (2, 30),
    "fact_ventas": (29, 69),
    "dim_fecha": (56, 98), "dim_producto": (56, 64), "dim_sucursal": (56, 34),
    "fact_inventario": (83, 63),
}
ANCHO, ALTO_FILA, ALTO_TITULO = 21, 1.75, 3.2


def _subtitulo(tabla: str, semantica: dict) -> str:
    return semantica["tablas"][tabla]["tipo"]


def _dibujar_tabla(ax, tabla, columnas, semantica, x, y):
    roles = semantica["tablas"][tabla]["columnas"]
    color = COLORES["hecho"] if tabla.startswith("fact") else COLORES["dimension"]
    alto = ALTO_TITULO + ALTO_FILA * len(columnas)
    ax.add_patch(FancyBboxPatch((x, y - alto), ANCHO, alto, boxstyle="round,pad=0,rounding_size=0.6",
                                fc=COLORES["fondo_fila"], ec=color, lw=1.4))
    ax.add_patch(FancyBboxPatch((x, y - ALTO_TITULO), ANCHO, ALTO_TITULO,
                                boxstyle="round,pad=0,rounding_size=0.6", fc=color, ec=color, lw=1.4))
    ax.text(x + 0.8, y - 1.25, tabla, color="white", fontsize=9.5, fontweight="bold", va="center")
    ax.text(x + 0.8, y - 2.45, _subtitulo(tabla, semantica), color="white", fontsize=6.3, va="center")
    for i, columna in enumerate(columnas):
        fila_y = y - ALTO_TITULO - ALTO_FILA * (i + 0.5)
        rol = roles.get(columna["nombre"], {}).get("rol", "")
        marca = _marca(columna, rol)
        color_marca = COLORES["scd"] if marca in ("S2", "S3") else color
        ax.text(x + 0.8, fila_y, marca, fontsize=6.3, fontweight="bold", color=color_marca, va="center")
        es_auditoria = rol == "Auditoría"
        ax.text(x + 3.2, fila_y, columna["nombre"], fontsize=7.2, va="center",
                color=COLORES["linaje"] if es_auditoria else COLORES["texto"],
                fontweight="bold" if columna["pk"] else "normal")
        ax.text(x + ANCHO - 0.8, fila_y, columna["tipo"].lower(), fontsize=6, va="center", ha="right",
                color=COLORES["linaje"])
    return (x, y - alto, ANCHO, alto)


def _borde_hacia(caja, destino):
    """Punto del borde de 'caja' en dirección al centro de 'destino'."""
    x, y, w, h = caja
    cx, cy = x + w / 2, y + h / 2
    dx, dy = destino[0] - cx, destino[1] - cy
    escala = min(w / 2 / abs(dx) if dx else float("inf"), h / 2 / abs(dy) if dy else float("inf"))
    return cx + dx * escala, cy + dy * escala


def generar_diagrama_estrella(esquema: dict, semantica: dict, relaciones: dict) -> None:
    fig, ax = plt.subplots(figsize=(15.5, 15))
    ax.set_xlim(0, 106)
    ax.set_ylim(-5, 103)
    ax.axis("off")
    cajas = {t: _dibujar_tabla(ax, t, esquema[t], semantica, *POSICIONES[t]) for t in TABLAS_MODELO}
    for hecho, dimensiones in relaciones.items():
        fx, fy, fw, fh = cajas[hecho]
        for tabla in dimensiones:
            x, y, w, h = cajas[tabla]
            origen = _borde_hacia(cajas[tabla], (fx + fw / 2, fy + fh / 2))
            destino = _borde_hacia(cajas[hecho], (x + w / 2, y + h / 2))
            ax.add_patch(FancyArrowPatch(origen, destino, arrowstyle="-", lw=1.3, color=COLORES["borde"]))
            for etiqueta, desplazamiento in (("1", 0.12), ("N", 0.88)):
                px = origen[0] + (destino[0] - origen[0]) * desplazamiento
                py = origen[1] + (destino[1] - origen[1]) * desplazamiento
                ax.text(px, py + 0.8, etiqueta, fontsize=8, color=COLORES["borde"], fontweight="bold", ha="center")
    ax.text(0.5, 102.5, "DataRetail 360 · Constelación de hechos Ventas + Inventario (capa Gold)",
            fontsize=13, fontweight="bold", color=COLORES["texto"], va="top")
    ax.text(0.5, 100.2, "Fecha, Producto y Sucursal son dimensiones conformadas: las comparten ambos hechos.",
            fontsize=8.5, color=COLORES["linaje"], va="top")
    ax.text(53, -2.2,
            "Grano fact_ventas: una línea de producto de cada boleta o pedido.   "
            "Grano fact_inventario: el stock de un producto, en una sucursal, al cierre de cada día.",
            fontsize=7.4, color=COLORES["linaje"], ha="center")
    ax.text(53, -4.2, "PK clave primaria · FK clave foránea · S2 atributo SCD tipo 2 · S3 atributo SCD tipo 3 · "
            "gris: columnas de linaje/auditoría", fontsize=7.2, color=COLORES["linaje"], ha="center")
    fig.savefig(config.DOCS / "modelo_estrella.png", dpi=170, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def generar_drawio(esquema: dict, semantica: dict, relaciones: dict) -> None:
    """Exporta el modelo a diagrams.net (Draw.io) para editarlo en Draw.io."""
    escala, ancho = 13, 270
    celdas, aristas = [], []
    for tabla in TABLAS_MODELO:
        x, y = POSICIONES[tabla]
        px, py = int(x * escala), int((103 - y) * escala)
        color = COLORES["hecho"] if tabla.startswith("fact") else COLORES["dimension"]
        roles = semantica["tablas"][tabla]["columnas"]
        titulo = f"{tabla}&#xa;{escape(_subtitulo(tabla, semantica))}"
        alto = 44 + 22 * len(esquema[tabla])
        celdas.append(
            f'<mxCell id="{tabla}" value="{titulo}" style="swimlane;fontStyle=1;childLayout=stackLayout;'
            f'horizontal=1;startSize=44;fillColor={color};fontColor=#ffffff;strokeColor={color};'
            f'rounded=1;arcSize=6;html=0;" vertex="1" parent="1">'
            f'<mxGeometry x="{px}" y="{py}" width="{ancho}" height="{alto}" as="geometry"/></mxCell>')
        for i, columna in enumerate(esquema[tabla]):
            marca = _marca(columna, roles.get(columna["nombre"], {}).get("rol", ""))
            texto = escape(f"{marca:<3} {columna['nombre']} : {columna['tipo'].lower()}", {'"': "&quot;"})
            estilo = "text;align=left;verticalAlign=middle;spacingLeft=6;fontFamily=Courier New;fontSize=11;"
            if columna["pk"]:
                estilo += "fontStyle=1;"
            celdas.append(f'<mxCell id="{tabla}_{i}" value="{texto}" style="{estilo}" vertex="1" '
                          f'parent="{tabla}"><mxGeometry y="{44 + 22 * i}" width="{ancho}" height="22" '
                          f'as="geometry"/></mxCell>')
    for hecho, dimensiones in relaciones.items():
        for tabla in dimensiones:
            aristas.append(f'<mxCell id="rel_{hecho}_{tabla}" style="edgeStyle=entityRelationEdgeStyle;'
                           f'endArrow=ERmany;startArrow=ERmandOne;endFill=0;startFill=0;" edge="1" parent="1" '
                           f'source="{tabla}" target="{hecho}"><mxGeometry relative="1" as="geometry"/></mxCell>')
    xml = ('<mxfile host="app.diagrams.net"><diagram id="modelo-estrella" name="Constelación Ventas + Inventario">'
           '<mxGraphModel grid="1" gridSize="10" guides="1" connect="1" arrows="1" page="1" '
           'pageWidth="1450" pageHeight="1400"><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
           + "".join(celdas + aristas) + "</root></mxGraphModel></diagram></mxfile>")
    (config.DOCS / "modelo_estrella.drawio").write_text(xml, encoding="utf-8")


# ------------------------------------------------------ diagrama Medallion
def generar_diagrama_medallion() -> None:
    fig, ax = plt.subplots(figsize=(15, 6.6))
    ax.set_xlim(0, 101.5)
    ax.set_ylim(0, 44)
    ax.axis("off")
    columnas = [
        ("FUENTES", "#6b7280", ["POS tiendas · CSV ';'", "E-commerce · JSON", "CRM · base SQLite",
                                "Maestro productos · CSV", "Equivalencias SKU · CSV", "Sucursales/comunas · CSV",
                                "Inventario diario · CSV"]),
        ("BRONZE", "#9a6b3f", ["Dato crudo, como texto", "Sin correcciones", "Contrato de columnas",
                               "Linaje y hash SHA-256", "Parquet por fuente y lote"]),
        ("SILVER", "#7b8794", ["Normaliza RUT y fechas", "Deduplica clientes", "Homologa SKU web → ERP",
                               "30 reglas de calidad", "Tabla de rechazos", "Parquet por año/mes"]),
        ("GOLD", "#b8860b", ["Ventas + Inventario (SQLite)", "SCD tipo 1, 2 y 3", "Carga idempotente",
                             "14 validaciones (todo o nada)", "Vistas semánticas", "Agregados precalculados"]),
        ("CONSUMO", "#1f3a5f", ["Dashboards en Power BI", "vw_ventas · vw_kpi_mensual",
                                "vw_inventario", "vw_kpi_inventario_mensual",
                                "Capa semántica JSON", "NLQ con validación humana"]),
    ]
    ancho, separacion, x = 16.5, 4.0, 1.5
    for i, (titulo, color, items) in enumerate(columnas):
        ax.add_patch(FancyBboxPatch((x, 4), ancho, 32, boxstyle="round,pad=0,rounding_size=1.2",
                                    fc="white", ec=color, lw=1.8))
        ax.add_patch(FancyBboxPatch((x, 31), ancho, 5, boxstyle="round,pad=0,rounding_size=1.2",
                                    fc=color, ec=color, lw=1.8))
        ax.text(x + ancho / 2, 33.5, titulo, color="white", fontsize=12, fontweight="bold",
                ha="center", va="center")
        for j, item in enumerate(items):
            ax.text(x + 1, 28.2 - j * 3.6, ("• " if item else "") + item, fontsize=7.9,
                    color=COLORES["texto"], va="center")
        if i < len(columnas) - 1:
            ax.add_patch(FancyArrowPatch((x + ancho + 0.4, 20), (x + ancho + separacion - 0.4, 20),
                                         arrowstyle="-|>", mutation_scale=18, lw=2, color="#4b5563"))
        x += ancho + separacion
    ax.text(1.5, 41.5, "DataRetail 360 · Arquitectura Medallion implementada",
            fontsize=13, fontweight="bold", color=COLORES["texto"])
    ax.text(1.5, 38.6, "Python 3.11 · Pandas · SQLAlchemy · PyArrow (Parquet) · SQLite · Git. "
            "Trazabilidad extremo a extremo: cada fila de Gold conserva id_carga, archivo y fila de origen.",
            fontsize=8.8, color=COLORES["linaje"])
    ax.text(50, 1.5, "El dato sube de Bronze a Gold ganando calidad en cada capa; "
            "las filas que no pasan las reglas quedan en etl_rechazos, nunca se pierden.",
            fontsize=8.8, color=COLORES["linaje"], ha="center")
    fig.savefig(config.DOCS / "arquitectura_medallion.png", dpi=170, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def generar_diccionario(esquema: dict, semantica: dict) -> None:
    """docs/diccionario_datos.md desde el esquema real de Gold y la capa semántica."""
    l = [f"# Diccionario de datos · {semantica['modelo']}", "",
         f"_Generado automáticamente desde el esquema de la capa Gold y `docs/capa_semantica.json` "
         f"(versión {semantica['version']})._", ""]
    for tabla in TABLAS_MODELO:
        info = semantica["tablas"][tabla]
        l += [f"## `{tabla}` — {info['tipo']}", ""]
        if "grano" in info:
            l += [f"**Grano:** {info['grano']}", ""]
        l += [info["descripcion"], "", "| Columna | Tipo | Rol | Descripción | Sinónimos |", "|---|---|---|---|---|"]
        for columna in esquema[tabla]:
            meta = info["columnas"].get(columna["nombre"], {})
            l.append(f"| `{columna['nombre']}` | {columna['tipo']} | {meta.get('rol', '')} | "
                     f"{meta.get('descripcion', '')} | {', '.join(meta.get('sinonimos', []))} |")
        l.append("")
    l += ["## Métricas oficiales (capa semántica)", "",
          "| Métrica | Definición | Fuente | SQL | Sinónimos |", "|---|---|---|---|---|"]
    for nombre, m in semantica["metricas"].items():
        l.append(f"| `{nombre}` | {m['descripcion']} | `{m['fuente']}` | `{m['sql']}` | "
                 f"{', '.join(m.get('sinonimos', []))} |")
    l += ["", "## Jerarquías", ""]
    l += [f"- **{nombre}:** {' → '.join(niveles)}" for nombre, niveles in semantica["jerarquias"].items()]
    l += ["", "## Reglas para asistentes de IA (NLQ / text-to-SQL)", ""]
    l += [f"{i}. {regla}" for i, regla in enumerate(semantica["reglas_para_ia"], start=1)]
    l += ["", "## Ejemplos de preguntas en lenguaje natural", ""]
    for ejemplo in semantica["ejemplos_nlq"]:
        l += [f"**{ejemplo['pregunta']}**", "", "```sql", ejemplo["sql"], "```", ""]
    (config.DOCS / "diccionario_datos.md").write_text("\n".join(l), encoding="utf-8")


def main() -> None:
    engine = gold.motor()
    esquema, semantica, relaciones = _esquema(engine), _semantica(), _relaciones(engine)
    generar_diagrama_estrella(esquema, semantica, relaciones)
    generar_drawio(esquema, semantica, relaciones)
    generar_diagrama_medallion()
    generar_diccionario(esquema, semantica)
    engine.dispose()
    print("Documentación generada en", config.DOCS)


if __name__ == "__main__":
    main()
