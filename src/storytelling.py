"""Storytelling con datos (Actividad 3.2): KPIs de Gold, gráficos Plotly y narrativa SCI.

Todo se calcula desde la capa semántica de Gold (vw_ventas y agg_inventario_mes),
con las mismas fórmulas de la Ficha de KPI. El notebook 3.2 y la app Streamlit
usan este módulo, así ambos muestran las mismas cifras que el dashboard BI.

    K1 Venta neta mensual        fact_ventas
    K2 Ticket promedio           fact_ventas
    K3 Tasa de quiebre de stock  fact_inventario
    K4 Días de cobertura         fact_inventario

Cada gráfico lleva un título que dice la conclusión (no solo el nombre del dato)
y se calcula desde los datos: si los datos o los filtros cambian, el mensaje también.
"""
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from sqlalchemy import create_engine, text

from . import config
from .exportar_bi import CONSULTAS_LOOKER

# Umbrales de la Ficha de KPI (docs/Ficha_KPI_DataRetail360.xlsx).
META_CRECIMIENTO_VENTA = 5.0        # K1: % sobre el mismo período del año anterior
META_QUIEBRE, ALERTA_QUIEBRE = 5.0, 8.0                   # K3: %
COBERTURA_MIN, COBERTURA_MAX = 15, 45                     # K4: días
COBERTURA_RIESGO, COBERTURA_SOBRESTOCK = 7, 60
TIENDA_NUEVA = "Iquique"            # abrió el 1 de marzo de 2026

# Paleta: un color de foco y grises de contexto; el rojo se reserva para la alerta.
COLOR = {"foco": "#2a78d6", "problema": "#eb6834", "contexto": "#898781", "atenuado": "#c3c2b7",
         "alerta": "#d03b3b", "texto": "#0b0b0b", "texto_2": "#52514e", "grilla": "#e1e0d9",
         "eje": "#c3c2b7", "fondo": "#fcfcfb"}
FUENTE = "system-ui, -apple-system, 'Segoe UI', sans-serif"
MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
MESES_LARGOS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
                "octubre", "noviembre", "diciembre"]


# ------------------------------------------------------------- formato
def num(valor: float, decimales: int = 0) -> str:
    """Formato chileno: punto para miles y coma para decimales."""
    return f"{valor:,.{decimales}f}".replace(",", "§").replace(".", ",").replace("§", ".")


def pesos(valor: float) -> str:
    return f"${num(valor)}"


def millones(valor: float) -> str:
    return f"${num(valor / 1e6)} MM"


def millones_grafico(valor: float) -> str:
    """Sin '$': Plotly interpreta el texto entre dos '$' como una fórmula LaTeX."""
    return f"{num(valor / 1e6)} MM CLP"


def pct(valor: float, decimales: int = 1, signo: bool = False) -> str:
    texto = num(valor, decimales) + "%"
    return ("+" + texto) if signo and valor > 0 else texto


# --------------------------------------------------------------- datos
def motor():
    return create_engine(config.DWH_URL)


def cargar_ventas(engine) -> pd.DataFrame:
    """Líneas de venta con sus atributos de análisis (vista semántica vw_ventas)."""
    return pd.read_sql("""
        SELECT anio, mes, anio_mes, sucursal, zona_sucursal AS zona, region_sucursal AS region,
               canal, categoria, numero_documento, es_devolucion, venta_neta, unidades
        FROM vw_ventas""", engine)


def cargar_inventario(engine) -> pd.DataFrame:
    """Componentes aditivos de K3 y K4 por mes, sucursal y categoría (agg_inventario_mes)."""
    agg = pd.read_sql("SELECT * FROM agg_inventario_mes", engine)
    agg["anio"] = agg["anio_mes"].str[:4].astype(int)
    agg["mes"] = agg["anio_mes"].str[5:].astype(int)
    return agg


def cargar_quiebre_productos(engine) -> pd.DataFrame:
    """Días en quiebre por producto, sucursal y mes.

    Es la misma consulta que alimenta la tabla de detalle del dashboard BI (src/exportar_bi.py).
    """
    detalle = pd.read_sql(text(CONSULTAS_LOOKER["quiebre_productos"]), engine)
    detalle["anio"] = detalle["anio_mes"].str[:4].astype(int)
    detalle["mes"] = detalle["anio_mes"].str[5:].astype(int)
    return detalle


def venta_en_riesgo(engine, desde: str, hasta: str) -> pd.DataFrame:
    """Estimación de la venta que no ocurrió por quiebres, por zona.

    Cada día-producto-sucursal en quiebre se valoriza con la venta diaria promedio
    de ese producto en esa sucursal (unidades) por su precio de lista. Es una
    estimación: sirve para dimensionar el problema, no es un KPI oficial.
    """
    # Función de ventana: una sola pasada por fact_inventario (un JOIN contra el promedio
    # agrupado hace que SQLite recorra la tabla una vez por cada producto-sucursal).
    return pd.read_sql(text("""
        WITH base AS (
            SELECT sk_producto, sk_sucursal, sk_fecha, es_quiebre,
                   AVG(unidades_vendidas) OVER (PARTITION BY sk_producto, sk_sucursal) AS unidades_dia
            FROM fact_inventario)
        SELECT s.zona, SUM(b.unidades_dia * p.precio_lista) AS venta_en_riesgo
        FROM base b
        JOIN dim_producto p ON p.sk_producto = b.sk_producto
        JOIN dim_sucursal s ON s.sk_sucursal = b.sk_sucursal
        WHERE b.es_quiebre = 1 AND b.sk_fecha BETWEEN :desde AND :hasta
        GROUP BY s.zona ORDER BY venta_en_riesgo DESC"""), engine,
        params={"desde": int(desde.replace("-", "") + "01"), "hasta": int(hasta.replace("-", "") + "31")})


# ---------------------------------------------------------------- KPIs
def k1_venta_neta(ventas: pd.DataFrame) -> float:
    return float(ventas["venta_neta"].sum())


def k2_ticket(ventas: pd.DataFrame) -> float:
    documentos = ventas.loc[ventas["es_devolucion"] == 0, "numero_documento"].nunique()
    return float(ventas["venta_neta"].sum() / documentos) if documentos else float("nan")


def k3_quiebre(inventario: pd.DataFrame) -> float:
    registros = inventario["registros"].sum()
    return float(100 * inventario["dias_quiebre"].sum() / registros) if registros else float("nan")


def k4_cobertura(inventario: pd.DataFrame) -> float:
    """Stock del último mes del período / venta diaria de sus últimos 28 días."""
    ultimo = inventario[inventario["anio_mes"] == inventario["anio_mes"].max()]
    vendidas = ultimo["unidades_vendidas_28d"].sum()
    return float(ultimo["stock_cierre_mes"].sum() * 28 / vendidas) if vendidas else float("nan")


def periodo(df: pd.DataFrame, anio: int, mes_desde: int = 1, mes_hasta: int = 6) -> pd.DataFrame:
    return df[(df["anio"] == anio) & df["mes"].between(mes_desde, mes_hasta)]


def nombre_periodo(mes_desde: int = 1, mes_hasta: int = 6, corto: bool = False) -> str:
    """'primer semestre' ('1er sem.' en corto), un trimestre, un mes suelto o un rango de meses."""
    conocidos = {(1, 6): ("primer semestre", "1er sem."), (7, 12): ("segundo semestre", "2º sem."),
                 (1, 3): ("primer trimestre", "1er trim."), (4, 6): ("segundo trimestre", "2º trim."),
                 (7, 9): ("tercer trimestre", "3er trim."), (10, 12): ("cuarto trimestre", "4º trim.")}
    if (mes_desde, mes_hasta) in conocidos:
        return conocidos[(mes_desde, mes_hasta)][1 if corto else 0]
    if corto:
        return MESES[mes_desde - 1] if mes_desde == mes_hasta else f"{MESES[mes_desde - 1]}–{MESES[mes_hasta - 1]}"
    if mes_desde == mes_hasta:
        return f"mes de {MESES_LARGOS[mes_desde - 1]}"
    return f"período {MESES_LARGOS[mes_desde - 1]}–{MESES_LARGOS[mes_hasta - 1]}"


def meta_k2(ventas: pd.DataFrame, anio: int, mes: int) -> float:
    """Meta del ticket de un mes: promedio de los 3 meses anteriores + 3% (Ficha de KPI)."""
    orden = ventas["anio"] * 12 + ventas["mes"]
    tickets = [k2_ticket(ventas[orden == anio * 12 + mes - n]) for n in (1, 2, 3)]
    tickets = [t for t in tickets if pd.notna(t)]           # meses sin ventas
    return 1.03 * sum(tickets) / len(tickets) if tickets else float("nan")


def estado_logro(logro: float) -> str:
    """K1 y K2 (logro = valor / meta): alerta bajo el 90% de la meta (Ficha de KPI)."""
    if pd.isna(logro):
        return "Sin comparación"
    return "En meta" if logro >= 1 else "Observación" if logro >= 0.9 else "Alerta"


def estado_quiebre(valor: float) -> str:
    if pd.isna(valor):
        return "Sin datos"
    return "En meta" if valor <= META_QUIEBRE else "Alerta" if valor > ALERTA_QUIEBRE else "Observación"


def estado_cobertura(valor: float) -> str:
    if pd.isna(valor):
        return "Sin datos"
    if COBERTURA_MIN <= valor <= COBERTURA_MAX:
        return "En meta"
    return "Alerta" if valor < COBERTURA_RIESGO or valor > COBERTURA_SOBRESTOCK else "Observación"


def kpis_periodo(ventas: pd.DataFrame, inventario: pd.DataFrame, anio: int = 2026,
                 mes_desde: int = 1, mes_hasta: int = 6) -> dict:
    """Los cuatro KPIs de un período contra el mismo período del año anterior, con meta y estado.

    Los datos pueden venir filtrados (zona, categoría, canal), pero con todos sus meses:
    la meta de K2 usa los 3 meses anteriores al último mes del período.
    `variacion` es % en K1 y K2, puntos porcentuales en K3 y días en K4.
    """
    actual_v, previo_v = (periodo(ventas, a, mes_desde, mes_hasta) for a in (anio, anio - 1))
    actual_i, previo_i = (periodo(inventario, a, mes_desde, mes_hasta) for a in (anio, anio - 1))
    nan = float("nan")

    def texto(valor, formato):
        return formato(valor) if pd.notna(valor) else "s/d"

    def crecimiento(valor, previo):
        return 100 * (valor / previo - 1) if previo and pd.notna(previo) else nan

    venta, venta_previa = k1_venta_neta(actual_v), k1_venta_neta(previo_v)
    # K1: meta = año anterior + 5%.
    logro_k1 = venta / (venta_previa * (1 + META_CRECIMIENTO_VENTA / 100)) if venta_previa else nan
    ticket, ticket_previo = k2_ticket(actual_v), k2_ticket(previo_v)
    # K2: el último mes del período contra el promedio de sus 3 meses anteriores + 3%.
    ultimo = int(actual_v["mes"].max()) if not actual_v.empty else mes_hasta
    meta_ticket = meta_k2(ventas, anio, ultimo)
    logro_k2 = k2_ticket(actual_v[actual_v["mes"] == ultimo]) / meta_ticket
    quiebre, quiebre_previo = k3_quiebre(actual_i), k3_quiebre(previo_i)
    cobertura, cobertura_previa = k4_cobertura(actual_i), k4_cobertura(previo_i)

    def dias(valor):
        return f"{num(valor, 1)} días"

    return {
        "K1": dict(nombre="Venta neta", hecho="fact_ventas", valor=venta, texto=millones(venta),
                   texto_previo=millones(venta_previa), variacion=crecimiento(venta, venta_previa),
                   meta=f"≥ +{num(META_CRECIMIENTO_VENTA)}% vs año anterior", logro=logro_k1,
                   estado=estado_logro(logro_k1)),
        "K2": dict(nombre="Ticket promedio", hecho="fact_ventas", valor=ticket, texto=texto(ticket, pesos),
                   texto_previo=texto(ticket_previo, pesos), variacion=crecimiento(ticket, ticket_previo),
                   meta=f"{MESES[ultimo - 1]}: ≥ {texto(meta_ticket, pesos)} (3 meses previos + 3%)",
                   logro=logro_k2, estado=estado_logro(logro_k2)),
        "K3": dict(nombre="Tasa de quiebre de stock", hecho="fact_inventario", valor=quiebre,
                   texto=texto(quiebre, lambda q: pct(q, 2)), texto_previo=texto(quiebre_previo, lambda q: pct(q, 2)),
                   variacion=quiebre - quiebre_previo, meta=f"≤ {num(META_QUIEBRE)}%",
                   estado=estado_quiebre(quiebre)),
        "K4": dict(nombre="Días de cobertura", hecho="fact_inventario", valor=cobertura,
                   texto=texto(cobertura, dias), texto_previo=texto(cobertura_previa, dias),
                   variacion=cobertura - cobertura_previa, meta=f"{COBERTURA_MIN} a {COBERTURA_MAX} días",
                   estado=estado_cobertura(cobertura)),
    }


def tabla_kpis(ventas: pd.DataFrame, inventario: pd.DataFrame, anio: int = 2026,
               mes_desde: int = 1, mes_hasta: int = 6) -> pd.DataFrame:
    """Los cuatro KPIs del período contra el mismo período del año anterior, con su estado."""
    def diferencia(valor, decimales, unidad):
        if pd.isna(valor):
            return "s/d"
        return f"{'+' if valor > 0 else ''}{num(valor, decimales)} {unidad}".replace("-", "−")

    def porcentaje(valor):
        return pct(valor, signo=True).replace("-", "−") if pd.notna(valor) else "s/d"

    variacion = {"K1": porcentaje, "K2": porcentaje,
                 "K3": lambda v: diferencia(v, 2, "pts"), "K4": lambda v: diferencia(v, 1, "días")}
    filas = [(clave, k["nombre"], k["hecho"], k["texto"], k["texto_previo"], k["meta"], k["estado"],
              variacion[clave](k["variacion"]))
             for clave, k in kpis_periodo(ventas, inventario, anio, mes_desde, mes_hasta).items()]
    corto = nombre_periodo(mes_desde, mes_hasta, corto=True)
    return pd.DataFrame(filas, columns=["ID", "KPI", "Hecho", f"{corto} {anio}", f"{corto} {anio - 1}",
                                        "Meta", "Estado", "Variación"])


# ------------------------------------------------------------- gráficos
def _estilo(fig: go.Figure, subtitulo: str, alto: int = 430) -> go.Figure:
    """Ejes y grilla recesivos, tipografía del sistema, subtítulo con la evidencia.

    El título y el subtítulo quedan también en layout.meta: la app los muestra como texto de la
    página, porque Plotly no corta las líneas de un título y en una columna angosta se pierde.
    """
    titulo = fig.layout.title.text
    fig.update_layout(
        height=alto, font=dict(family=FUENTE, size=13, color=COLOR["texto_2"]),
        title=dict(text=f"{titulo}<br><sup style='color:{COLOR['texto_2']}'>{subtitulo}</sup>",
                   font=dict(size=17, color=COLOR["texto"]), x=0, xanchor="left"),
        meta=dict(titulo=titulo, subtitulo=subtitulo),
        paper_bgcolor=COLOR["fondo"], plot_bgcolor=COLOR["fondo"], separators=",.",
        margin=dict(l=10, r=30, t=110 if "<br>" in titulo else 90, b=40),
        hoverlabel=dict(font_family=FUENTE), legend=dict(orientation="h", y=-0.15, x=0, title_text=""))
    # automargin explícito: sin él, las etiquetas de los ejes se cortan cuando no se usa la plantilla de Plotly.
    fig.update_xaxes(showgrid=False, linecolor=COLOR["eje"], tickfont_color=COLOR["contexto"], automargin=True)
    fig.update_yaxes(gridcolor=COLOR["grilla"], zeroline=False, tickfont_color=COLOR["contexto"], automargin=True)
    return fig


def fig_venta_semestre(ventas: pd.DataFrame, anio: int = 2026, mes_desde: int = 1, mes_hasta: int = 6) -> go.Figure:
    """Situación (K1): venta neta mensual del período contra el año anterior, con y sin la tienda nueva."""
    def mensual(df):
        return df.groupby("mes")["venta_neta"].sum().reindex(range(mes_desde, mes_hasta + 1), fill_value=0) / 1e6

    actual, previo = (periodo(ventas, a, mes_desde, mes_hasta) for a in (anio, anio - 1))
    series = {f"{anio - 1}": mensual(previo), f"{anio}": mensual(actual)}
    con_tienda_nueva = (actual["sucursal"] == TIENDA_NUEVA).any()
    if con_tienda_nueva:
        series[f"{anio} sin {TIENDA_NUEVA}"] = mensual(actual[actual["sucursal"] != TIENDA_NUEVA])
    datos = pd.DataFrame(series).rename(index=dict(enumerate(MESES, start=1))).reset_index(names="mes")
    largo = datos.melt(id_vars="mes", var_name="serie", value_name="venta_mm")

    total_actual, total_previo = k1_venta_neta(actual), k1_venta_neta(previo)
    del_periodo = f"del {nombre_periodo(mes_desde, mes_hasta)}"
    subtitulo = f"K1 · {millones_grafico(total_actual)} en {anio} vs {millones_grafico(total_previo)} en {anio - 1}"
    if total_previo:
        crecimiento = 100 * (total_actual / total_previo - 1)
        verbo = "creció" if crecimiento >= 0 else "cayó"
        titulo = f"La venta neta {del_periodo} {verbo} {pct(abs(crecimiento))} frente a {anio - 1}"
    else:
        titulo = f"La venta neta {del_periodo} fue de {millones_grafico(total_actual)} (sin ventas en {anio - 1})"
    if con_tienda_nueva and total_previo:
        sin_nueva = 100 * (k1_venta_neta(actual[actual["sucursal"] != TIENDA_NUEVA]) / total_previo - 1)
        aporte = k1_venta_neta(actual[actual["sucursal"] == TIENDA_NUEVA])
        titulo += (f",<br>pero sin la tienda nueva de {TIENDA_NUEVA} habría "
                   f"{'crecido' if sin_nueva >= 0 else 'caído'} {pct(abs(sin_nueva))}")
        subtitulo += f" · {TIENDA_NUEVA} abrió en marzo y aportó {millones_grafico(aporte)}"

    colores = {f"{anio - 1}": COLOR["contexto"], f"{anio}": COLOR["foco"],
               f"{anio} sin {TIENDA_NUEVA}": COLOR["problema"]}
    fig = px.line(largo, x="mes", y="venta_mm", color="serie", markers=True, title=titulo,
                  color_discrete_map=colores, line_dash="serie",
                  line_dash_map={k: ("dash" if "sin" in k else "solid") for k in colores})
    fig.update_traces(line_width=2, marker_size=8,
                      hovertemplate="%{x}: %{y:,.1f} MM CLP<extra>%{fullData.name}</extra>")
    # Etiqueta directa al final de cada línea, separadas para que no choquen.
    finales = sorted((float(t.y[-1]), t.name) for t in fig.data)
    separacion = 0.07 * (largo["venta_mm"].max() - largo["venta_mm"].min())
    posiciones = []
    for valor, _ in finales:
        posiciones.append(max(valor, posiciones[-1] + separacion) if posiciones else valor)
    for (_, nombre), y in zip(finales, posiciones):
        fig.add_annotation(x=MESES[mes_hasta - 1], y=y, text=nombre, showarrow=False, xanchor="left", xshift=12,
                           font=dict(color=COLOR["texto_2"], size=12))
    fig.update_yaxes(title_text="Venta neta (MM CLP)")
    fig.update_xaxes(title_text="")
    fig.update_layout(margin_r=130)
    return _estilo(fig, subtitulo)


def fig_quiebre_mensual(inventario: pd.DataFrame, resaltar: tuple[str, str] | None = None) -> go.Figure:
    """Complicación (K3): tasa de quiebre mes a mes contra la meta y la alerta.

    `resaltar` = (anio_mes desde, anio_mes hasta) marca con una franja el período en análisis.
    """
    mensual = (inventario.groupby("anio_mes")[["dias_quiebre", "registros"]].sum()
               .assign(tasa=lambda d: 100 * d["dias_quiebre"] / d["registros"]).reset_index())
    mensual["mes"] = [f"{MESES[int(m[5:]) - 1]} {m[2:4]}" for m in mensual["anio_mes"]]
    sobre_meta = int((mensual["tasa"] > META_QUIEBRE).sum())
    cuantos = f"los {len(mensual)} meses" if sobre_meta == len(mensual) else f"{sobre_meta} de {len(mensual)} meses"
    titulo = (f"El quiebre de stock superó la meta de {num(META_QUIEBRE)}% en {cuantos}"
              if sobre_meta else f"El quiebre de stock se mantuvo en la meta de {num(META_QUIEBRE)}%")
    alertas = mensual[mensual["tasa"] > ALERTA_QUIEBRE]
    subtitulo = f"K3 · % de días-producto-sucursal que cerraron con stock 0 · promedio {pct(k3_quiebre(inventario), 2)}"
    if not alertas.empty:
        subtitulo += f" · sobre la alerta en {', '.join(alertas['mes'])}"

    fig = px.line(mensual, x="mes", y="tasa", markers=True, title=titulo)
    fig.update_traces(line_color=COLOR["foco"], line_width=2, marker_size=8,
                      hovertemplate="%{x}: %{y:.2f}% de quiebre<extra></extra>")
    fig.add_hline(y=META_QUIEBRE, line_dash="dash", line_color=COLOR["contexto"], line_width=1.5,
                  annotation_text=f"Meta {num(META_QUIEBRE)}%", annotation_position="bottom left",
                  annotation_font_color=COLOR["texto_2"])
    fig.add_hline(y=ALERTA_QUIEBRE, line_dash="dot", line_color=COLOR["alerta"], line_width=1.5,
                  annotation_text=f"⚠ Alerta {num(ALERTA_QUIEBRE)}%", annotation_position="top left",
                  annotation_font_color=COLOR["texto_2"])
    for fila in alertas.itertuples():
        fig.add_annotation(x=fila.mes, y=fila.tasa, text=pct(fila.tasa), showarrow=False, yshift=14,
                           font=dict(color=COLOR["texto"], size=12))
    if resaltar:
        dentro = mensual.index[mensual["anio_mes"].between(*resaltar)]
        if 0 < len(dentro) < len(mensual):
            # En un eje de categorías, las posiciones numéricas son el índice de cada mes.
            fig.add_vrect(x0=dentro[0] - 0.5, x1=dentro[-1] + 0.5, fillcolor=COLOR["foco"], opacity=0.08,
                          line_width=0, layer="below")
            fig.add_annotation(x=(dentro[0] + dentro[-1]) / 2, y=1, yref="paper", yanchor="bottom",
                               text="período en análisis", showarrow=False,
                               font=dict(color=COLOR["texto_2"], size=11))
    fig.update_yaxes(title_text="Tasa de quiebre (%)", range=[0, max(10, mensual["tasa"].max() + 1.5)])
    fig.update_xaxes(title_text="")
    return _estilo(fig, subtitulo)


def resumen_por(inventario: pd.DataFrame, columna: str) -> pd.DataFrame:
    """K3 y K4 por zona o sucursal (K4 con el último mes del período)."""
    ultimo = inventario["anio_mes"].max()
    base = inventario.groupby(columna).agg(registros=("registros", "sum"), dias_quiebre=("dias_quiebre", "sum"))
    fin = (inventario[inventario["anio_mes"] == ultimo].groupby(columna)
           [["stock_cierre_mes", "unidades_vendidas_28d"]].sum())
    resumen = base.join(fin)
    resumen["quiebre"] = 100 * resumen["dias_quiebre"] / resumen["registros"]
    resumen["cobertura"] = resumen["stock_cierre_mes"] * 28 / resumen["unidades_vendidas_28d"]
    return resumen[["quiebre", "cobertura"]].sort_values("quiebre", ascending=False)


def fig_quiebre_sucursal(inventario: pd.DataFrame) -> go.Figure:
    """Complicación -> Idea (K3 y K4): dónde se quiebra más, con la cobertura al lado."""
    zonas = resumen_por(inventario, "zona")
    sucursales = resumen_por(inventario, "sucursal").join(
        inventario.drop_duplicates("sucursal").set_index("sucursal")["zona"])
    peor = zonas.index[0]
    sucursales["grupo"] = [f"Zona {peor}" if z == peor else "Resto" for z in sucursales["zona"]]
    sucursales["etiqueta"] = [f"{pct(q)} · {num(c)} días" for q, c in zip(sucursales["quiebre"], sucursales["cobertura"])]
    datos = sucursales.reset_index().sort_values("quiebre")

    primera = sucursales.index[0]
    titulo = (f"En la zona {peor}, {primera} es la tienda que más quiebra "
              f"({pct(sucursales.loc[primera, 'quiebre'])})")
    subtitulo = f"K3 tasa de quiebre y K4 días de cobertura · {pct(zonas.loc[peor, 'quiebre'])} en {peor}"
    if len(zonas) > 1:
        # Referencia: la zona Centro (Santiago) si está en el filtro; si no, la que menos quiebra.
        ref = "Centro" if "Centro" in zonas.index and peor != "Centro" else zonas.index[-1]
        veces = zonas.loc[peor, "quiebre"] / zonas.loc[ref, "quiebre"]
        cob_peor, cob_ref = zonas.loc[peor, "cobertura"], zonas.loc[ref, "cobertura"]
        if veces >= 1.5:
            titulo = f"La zona {peor} quiebra {num(veces, 1)} veces más que la zona {ref}"
            if abs(cob_peor / cob_ref - 1) <= 0.25:
                titulo += " con una cobertura parecida:<br>falta reponer a tiempo, no comprar más"
        subtitulo += (f" vs {pct(zonas.loc[ref, 'quiebre'])} en {ref}"
                      f" · cobertura {num(cob_peor, 1)} vs {num(cob_ref, 1)} días")

    fig = px.bar(datos, x="quiebre", y="sucursal", orientation="h", color="grupo", text="etiqueta", title=titulo,
                 color_discrete_map={f"Zona {peor}": COLOR["problema"], "Resto": COLOR["atenuado"]},
                 custom_data=["zona", "cobertura"])
    fig.update_traces(marker_cornerradius=4, textposition="outside", cliponaxis=False,
                      textfont=dict(color=COLOR["texto_2"], size=11),
                      hovertemplate="<b>%{y}</b> (%{customdata[0]})<br>Quiebre: %{x:.2f}%"
                                    "<br>Cobertura: %{customdata[1]:.0f} días<extra></extra>")
    fig.add_vline(x=META_QUIEBRE, line_dash="dash", line_color=COLOR["contexto"], line_width=1.5, layer="below")
    fig.add_annotation(x=META_QUIEBRE, y=0, yref="paper", yanchor="top", yshift=-22, showarrow=False,
                       text=f"Meta {num(META_QUIEBRE)}%", font=dict(color=COLOR["texto_2"], size=12))
    fig.update_layout(bargap=0.25, yaxis=dict(categoryorder="array", categoryarray=list(datos["sucursal"])))
    fig.update_xaxes(title_text="", ticksuffix="%", range=[0, datos["quiebre"].max() * 1.3])
    fig.update_yaxes(title_text="", gridcolor="rgba(0,0,0,0)")
    return _estilo(fig, subtitulo, alto=max(380, 40 * len(datos) + 140))


# -------------------------------------------------------------- detalle
def productos_en_quiebre(detalle: pd.DataFrame, cuantos: int = 15) -> pd.DataFrame:
    """Detalle (K3): los producto-sucursal con más días en quiebre del período.

    El stock y el stock mínimo son los del último mes del período: dicen qué reponer y dónde.
    """
    claves = ["cod_producto", "producto", "categoria", "sucursal", "zona"]
    dias = detalle.groupby(claves, as_index=False)[["dias_quiebre", "dias_informados"]].sum()
    cierre = detalle.loc[detalle["anio_mes"] == detalle["anio_mes"].max(),
                         claves + ["stock_cierre_mes", "stock_minimo"]]
    top = (dias[dias["dias_quiebre"] > 0].merge(cierre, on=claves, how="left")
           .sort_values(["dias_quiebre", "producto", "sucursal"], ascending=[False, True, True]).head(cuantos))
    top["pct_dias"] = 100 * top["dias_quiebre"] / top["dias_informados"]
    return top.reset_index(drop=True)


# ------------------------------------------------------------ narrativa
def narrativa_sci(ventas: pd.DataFrame, inventario: pd.DataFrame, en_riesgo: pd.DataFrame | None = None,
                  anio: int = 2026) -> dict:
    """Situación, complicación e idea, con las cifras calculadas desde Gold."""
    actual_v, previo_v = periodo(ventas, anio), periodo(ventas, anio - 1)
    actual_i = periodo(inventario, anio)
    total, total_previo = k1_venta_neta(actual_v), k1_venta_neta(previo_v)
    crecimiento = 100 * (total / total_previo - 1)
    nueva = k1_venta_neta(actual_v[actual_v["sucursal"] == TIENDA_NUEVA])
    sin_nueva = 100 * ((total - nueva) / total_previo - 1)
    ticket, ticket_previo = k2_ticket(actual_v), k2_ticket(previo_v)
    meses = inventario.groupby("anio_mes")[["dias_quiebre", "registros"]].sum()
    sobre_meta = int((100 * meses["dias_quiebre"] / meses["registros"] > META_QUIEBRE).sum())
    zonas = resumen_por(actual_i, "zona")
    peor, centro = zonas.index[0], "Centro"
    sucursales = resumen_por(actual_i[actual_i["zona"] == peor], "sucursal").index[:3]

    situacion = (f"En el primer semestre de {anio} DataRetail 360 vendió {millones(total)} netos, "
                 f"{pct(crecimiento)} más que en {anio - 1}, con un ticket promedio de {pesos(ticket)} "
                 f"({pct(100 * (ticket / ticket_previo - 1), signo=True)}).")
    if centro not in zonas.index or centro == peor:
        centro = zonas.index[-1]
    cuantos = f"los {len(meses)} meses" if sobre_meta == len(meses) else f"{sobre_meta} de {len(meses)} meses"
    complicacion = (f"Pero todo ese crecimiento lo aporta la tienda nueva de {TIENDA_NUEVA} ({millones(nueva)}): "
                    f"sin ella, la venta {'sube' if sin_nueva >= 0 else 'cae'} {pct(abs(sin_nueva))}. "
                    f"Además, el quiebre de stock superó la meta de {num(META_QUIEBRE)}% en {cuantos} "
                    f"({pct(k3_quiebre(actual_i), 2)} en el semestre) y en la zona {peor} llega a "
                    f"{pct(zonas.loc[peor, 'quiebre'])}, frente a {pct(zonas.loc[centro, 'quiebre'])} en la zona "
                    f"{centro}, con una cobertura parecida ({num(zonas.loc[peor, 'cobertura'], 1)} vs "
                    f"{num(zonas.loc[centro, 'cobertura'], 1)} días): no falta stock en total, falta reponer a tiempo.")
    if en_riesgo is not None and not en_riesgo.empty:
        riesgo = en_riesgo["venta_en_riesgo"].sum()
        complicacion += (f" Estimamos que esos quiebres dejaron de vender unos {millones(riesgo)} en el semestre"
                         + (", más de lo que crecimos." if riesgo > total - total_previo else "."))
    idea = (f"Recomendamos subir el stock mínimo y la frecuencia de reposición en las tiendas de la zona {peor}, "
            f"partiendo por {', '.join(sucursales[:-1])} y {sucursales[-1]}, para bajar el quiebre a la meta de "
            f"{num(META_QUIEBRE)}% antes del cierre de {anio}, y medir el avance cada mes con K3.")
    return {"Situación": situacion, "Complicación": complicacion, "Idea / acción": idea}


# ---------------------------------------------------------- exportación
def exportar(destino=None) -> None:
    """Guarda los tres gráficos (HTML interactivo y PNG) y la narrativa SCI en docs/storytelling/.

    Se corre desde la terminal: exportar PNG con kaleido dentro de un notebook es muy lento.
    """
    destino = destino or config.DOCS / "storytelling"
    destino.mkdir(parents=True, exist_ok=True)
    engine = motor()
    ventas, inventario = cargar_ventas(engine), cargar_inventario(engine)
    figuras = {"g1_venta_semestre": fig_venta_semestre(ventas),
               "g2_quiebre_mensual": fig_quiebre_mensual(inventario),
               "g3_quiebre_sucursal": fig_quiebre_sucursal(periodo(inventario, 2026))}
    for nombre, figura in figuras.items():
        figura.write_html(destino / f"{nombre}.html", include_plotlyjs="cdn")
        figura.write_image(destino / f"{nombre}.png", width=1000, scale=2)
    sci = narrativa_sci(ventas, inventario, venta_en_riesgo(engine, "2026-01", "2026-06"))
    (destino / "narrativa_sci.md").write_text(
        "# Narrativa SCI · DataRetail 360 · 1er semestre 2026\n\n"
        + "\n\n".join(f"**{parte}.** {texto}" for parte, texto in sci.items()) + "\n", encoding="utf-8")
    print("Gráficos y narrativa guardados en", destino)


if __name__ == "__main__":
    exportar()
