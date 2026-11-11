"""DataRetail 360 · App de storytelling (Actividad 3.2).

Es la versión en Python del dashboard BI (docs/excalidraw/dashboard_bi_wireframe.png):
cuatro filtros, los cuatro KPIs oficiales (dos de fact_ventas y dos de fact_inventario),
los tres gráficos de la narrativa, la tabla de productos en quiebre y la narrativa SCI.
Los cálculos vienen de src/storytelling.py, igual que en el notebook.

Uso:  streamlit run app.py
"""
import pandas as pd
import streamlit as st

from src import storytelling as sty

ANIO = 2026
PERIODOS = {f"1er semestre {ANIO}": (1, 6), f"1er trimestre {ANIO}": (1, 3), f"2º trimestre {ANIO}": (4, 6)}
ICONO = {"En meta": "✅", "Observación": "🟠", "Alerta": "⚠️"}

st.set_page_config(page_title="DataRetail 360 · Storytelling", page_icon="📊", layout="wide")


@st.cache_data
def datos():
    engine = sty.motor()
    return (sty.cargar_ventas(engine), sty.cargar_inventario(engine),
            sty.venta_en_riesgo(engine, f"{ANIO}-01", f"{ANIO}-06"), sty.cargar_quiebre_productos(engine))


ventas, inventario, riesgo, detalle = datos()

st.title("DataRetail 360 · Ventas e inventario")
st.caption(f"Cada período se compara con el mismo período de {ANIO - 1} · Capa Gold (vw_ventas, "
           "agg_inventario_mes) · KPIs de la Ficha de KPI: dos por tabla de hechos")

# Filtros en una fila, arriba de todo (los mismos cuatro del dashboard BI).
c1, c2, c3, c4 = st.columns(4)
desde, hasta = PERIODOS[c1.selectbox("Período", list(PERIODOS))]
zonas = c2.multiselect("Zona", sorted(inventario["zona"].unique()), placeholder="Todas las zonas")
categorias = c3.multiselect("Categoría", sorted(inventario["categoria"].unique()), placeholder="Todas las categorías")
canales = c4.multiselect("Canal", sorted(ventas["canal"].unique()), placeholder="Todos los canales")
if canales:
    st.caption("ℹ️ El filtro de canal solo afecta a ventas (K1, K2 y el gráfico de venta): "
               "el inventario no tiene canal.")


def filtrar(df, con_canal=False):
    if zonas:
        df = df[df["zona"].isin(zonas)]
    if categorias:
        df = df[df["categoria"].isin(categorias)]
    if con_canal and canales:
        df = df[df["canal"].isin(canales)]
    return df


v, inv, det = filtrar(ventas, con_canal=True), filtrar(inventario), filtrar(detalle)
actual_i = sty.periodo(inv, ANIO, desde, hasta)
if sty.periodo(v, ANIO, desde, hasta).empty or actual_i.empty:
    st.warning("No hay datos para esa combinación de filtros.")
    st.stop()


# Tarjetas de KPI: valor del período, variación contra el año anterior y estado contra la meta.
def diferencia(valor, decimales, unidad):
    return f"{'+' if valor > 0 else ''}{sty.num(valor, decimales)} {unidad} vs {ANIO - 1}"


kpis = sty.kpis_periodo(v, inv, ANIO, desde, hasta)
tarjetas = {
    "K1": dict(titulo="K1 · Venta neta", variacion=lambda x: f"{sty.pct(x, signo=True)} vs {ANIO - 1}",
               color="normal", ayuda=f"Meta: ≥ +{sty.num(sty.META_CRECIMIENTO_VENTA)}% sobre el mismo "
                                     "período del año anterior · alerta bajo el 90% de la meta"),
    "K2": dict(titulo="K2 · Ticket promedio", variacion=lambda x: f"{sty.pct(x, signo=True)} vs {ANIO - 1}",
               color="normal", ayuda="Venta neta / documentos de venta. Meta del último mes del período: "
                                     "≥ promedio de los 3 meses anteriores + 3%"),
    "K3": dict(titulo="K3 · Tasa de quiebre", variacion=lambda x: diferencia(x, 2, "pts"), color="inverse",
               ayuda=f"% de días-producto-sucursal que cerraron con stock 0. Meta: ≤ {sty.num(sty.META_QUIEBRE)}% "
                     f"· alerta sobre {sty.num(sty.ALERTA_QUIEBRE)}%"),
    "K4": dict(titulo="K4 · Días de cobertura", variacion=lambda x: diferencia(x, 1, "días"), color="off",
               ayuda="Stock del último día del período / venta diaria de los últimos 28 días. Meta: entre "
                     f"{sty.COBERTURA_MIN} y {sty.COBERTURA_MAX} días"),
}
for columna, (clave, tarjeta) in zip(st.columns(4), tarjetas.items()):
    kpi = kpis[clave]
    hay_variacion = pd.notna(kpi["variacion"])          # no la hay si el año anterior no tiene datos
    columna.metric(tarjeta["titulo"], kpi["texto"], tarjeta["variacion"](kpi["variacion"]) if hay_variacion else None,
                   delta_color=tarjeta["color"], help=tarjeta["ayuda"])
    columna.caption(f"{ICONO.get(kpi['estado'], '')} {kpi['estado']} · meta {kpi['meta']}")



def grafico(contenedor, fig):
    """Muestra el título-mensaje como texto de la página, que sí se ajusta al ancho de la columna."""
    margen_titulo = fig.layout.margin.t
    contenedor.markdown(f"**{fig.layout.meta['titulo'].replace('<br>', ' ')}**")
    contenedor.caption(fig.layout.meta["subtitulo"])
    fig.update_layout(title_text="", margin_t=30, height=fig.layout.height - margen_titulo + 30)
    contenedor.plotly_chart(fig, width="stretch", theme=None)


# Los tres gráficos de la historia.
grafico(st, sty.fig_venta_semestre(v, ANIO, desde, hasta))
izquierda, derecha = st.columns(2)
grafico(izquierda, sty.fig_quiebre_mensual(inv, resaltar=(f"{ANIO}-{desde:02d}", f"{ANIO}-{hasta:02d}")))
grafico(derecha, sty.fig_quiebre_sucursal(actual_i))

# Detalle: qué producto reponer y dónde.
st.subheader("Productos con más días en quiebre")
top = sty.productos_en_quiebre(sty.periodo(det, ANIO, desde, hasta))
if top.empty:
    st.info("Ningún producto cerró un día sin stock con estos filtros.")
else:
    por_sucursal = top["sucursal"].value_counts()
    concentra = (f"{por_sucursal.index[0]} concentra {por_sucursal.iloc[0]} de los {len(top)} · "
                 if len(por_sucursal) > 1 else "")
    st.caption(f"{concentra}Días que cada producto cerró con stock 0 en el período y su stock al cierre de "
               f"{sty.MESES_LARGOS[hasta - 1]}: cada fila dice qué reponer y dónde.")
    columnas = {"producto": "Producto", "categoria": "Categoría", "sucursal": "Sucursal", "zona": "Zona",
                "dias_quiebre": "Días en quiebre", "pct_dias": "% del período",
                "stock_cierre_mes": f"Stock a {sty.MESES_LARGOS[hasta - 1]}", "stock_minimo": "Stock mínimo"}
    st.dataframe(
        top[list(columnas)].rename(columns=columnas), hide_index=True, width="stretch",
        column_config={
            "Días en quiebre": st.column_config.ProgressColumn(
                format="%d", min_value=0, max_value=int(top["dias_informados"].max())),
            "% del período": st.column_config.NumberColumn(format="%.0f%%"),
        })

# Narrativa SCI: describe a toda la empresa en el semestre, por eso solo se muestra sin filtros.
st.subheader("Narrativa SCI")
if zonas or categorias or canales or (desde, hasta) != (1, 6):
    st.info("La narrativa SCI describe a toda la empresa en el primer semestre: quita los filtros para verla.")
else:
    for parte, texto in sty.narrativa_sci(ventas, inventario, riesgo, ANIO).items():
        st.markdown(f"**{parte}.** {texto}")

with st.expander("Ver la tabla de KPIs"):
    st.dataframe(sty.tabla_kpis(v, inv, ANIO, desde, hasta), hide_index=True, width="stretch")
