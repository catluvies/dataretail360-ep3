# DataRetail 360 · EP3

IDY1102 Estructuras y Visualización de Datos · Sección 003D
Anyara Rosso · Robert Groom

Pipeline ETL en Python que integra las fuentes del caso DataRetail 360 en un modelo dimensional,
siguiendo la arquitectura Medallion: Bronze (dato crudo) → Silver (dato limpio) → Gold (modelo dimensional).

El modelo es una **constelación de dos hechos** que comparten las dimensiones conformadas
fecha, producto y sucursal (Bus Matrix de la EP1):

| Hecho | Tipo | Grano | Dimensiones |
|---|---|---|---|
| `fact_ventas` | Transaccional | Una línea de producto de cada boleta o pedido | fecha, producto, sucursal, canal, cliente |
| `fact_inventario` | Snapshot periódico diario | El stock de un producto, en una sucursal, por día | fecha, producto, sucursal |

KPIs oficiales (`docs/Ficha_KPI_DataRetail360.xlsx`), dos por hecho:

| ID | KPI | Hecho | Vista |
|---|---|---|---|
| K1 | Venta neta mensual | `fact_ventas` | `vw_kpi_mensual` |
| K2 | Ticket promedio | `fact_ventas` | `vw_kpi_mensual` |
| K3 | Tasa de quiebre de stock | `fact_inventario` | `vw_kpi_inventario_mensual` |
| K4 | Días de cobertura | `fact_inventario` | `vw_kpi_inventario_mensual` |

## Qué hay

| Carpeta | Contenido |
|---|---|
| `src/` | Código del pipeline: generador de datos, capas Bronze, Silver y Gold, validaciones |
| `sql/` | Esquema de Gold y vistas para consultar ventas e inventario |
| `notebooks/` | `EP3_evidencias.ipynb`: el pipeline ejecutado paso a paso, con sus resultados · `3.2_storytelling_ventas_inventario.ipynb`: gráficos y narrativa |
| `docs/` | Modelo (imagen y archivo de Draw.io), arquitectura, capa semántica, diccionario y Ficha de KPI |

## Cómo ejecutarlo

Requiere Python 3.11.

```bash
pip install pandas sqlalchemy pyarrow matplotlib jupyter
python -m src.generar_fuentes
python -m src.pipeline --todo --reiniciar
python -m src.documentacion
```

El primer comando crea los datos de prueba del caso (ocho archivos por lote, incluido el inventario
diario) y el segundo los carga en las tres capas. Cada lote termina con `EXITOSA` en el log y
14 validaciones `OK` (9 de ventas y 5 de inventario, entre ellas la cuadratura de unidades vendidas
entre los dos hechos). El tercero regenera los diagramas y el diccionario de `docs/` desde el
esquema real de Gold.
Después se puede abrir `notebooks/EP3_evidencias.ipynb` para ver la evidencia.

Ojo: `generar_fuentes` sobrescribe `data/fuentes/`. Si editaste alguna fuente a mano (por ejemplo,
el CRM para una demo), respáldala antes.

### Altas, cambios y bajas de clientes (SCD tipo 2)

El CRM de cada lote (`data/fuentes/lote_N/crm_clientes.db`, tabla `clientes`) es una foto completa.
Al volver a cargar el lote más reciente, `dim_cliente` queda así:

| En el CRM | En `dim_cliente` |
|---|---|
| Cliente nuevo | Versión 1, vigente. Si el RUT no es válido se rechaza y queda en `etl_rechazos` |
| Cambia la comuna o el segmento | Se cierra la versión vigente y se abre otra, que rige desde la fecha de actualización del CRM o, si el CRM no fechó el cambio, desde el día de la carga |
| El cliente ya no viene | No se borra: se cierra su versión vigente y queda sin versión actual. Sus ventas siguen enlazadas |

Reprocesar un lote anterior al último cargado no modifica las dimensiones.

## Actividad 3.2 · Storytelling con datos

```bash
pip install plotly kaleido streamlit
python -m src.storytelling        # gráficos (HTML + PNG) y narrativa SCI en docs/storytelling/
streamlit run app.py              # app con los 4 KPIs, los 3 gráficos, la tabla de productos en quiebre y 4 filtros
```

`notebooks/3.2_storytelling_ventas_inventario.ipynb` tiene los tres gráficos con título-mensaje y la
narrativa SCI. Todos los cálculos están en `src/storytelling.py`, así el notebook, la app y el
dashboard usan una sola definición de cada KPI.

## Dashboard BI (guía 3.2.3)

```bash
python -m src.exportar_bi         # CSV de Gold en data/bi/: modelo estrella (Power BI) y tablas planas (Looker Studio)
```

`docs/dashboard_bi.md` explica cómo armarlo: relaciones, medidas DAX de los 4 KPIs, visuales, filtros
y las cifras de control que el dashboard debe mostrar. El wireframe está en
`docs/excalidraw/dashboard_bi_wireframe.png`, y los diagramas y fichas visuales de KPIs, en `docs/excalidraw/`.
