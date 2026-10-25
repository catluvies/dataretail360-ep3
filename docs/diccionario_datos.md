# Diccionario de datos · DataRetail 360 · Ventas multicanal

_Generado automáticamente desde el esquema de la capa Gold y `docs/capa_semantica.json` (versión 1.0)._

**Grano del hecho:** Una fila de fact_ventas representa una línea de producto de una boleta (tienda física) o de un pedido (sitio web o app).

## `fact_ventas` — Hecho transaccional

Líneas vendidas en tiendas físicas y canales digitales. Las transacciones anuladas no se cargan; las devueltas se cargan con es_devolucion = 1.

| Columna | Tipo | Rol | Descripción | Sinónimos |
|---|---|---|---|---|
| `sk_venta` | INTEGER | PK | Clave sustituta de la línea de venta. |  |
| `sk_fecha` | INTEGER | FK | Fecha de la venta (FK a dim_fecha, formato AAAAMMDD). |  |
| `sk_cliente` | INTEGER | FK | Versión del cliente vigente en la fecha de la venta (FK a dim_cliente). -1 = cliente no identificado. |  |
| `sk_producto` | INTEGER | FK | Producto vendido (FK a dim_producto). |  |
| `sk_sucursal` | INTEGER | FK | Sucursal donde se registró la venta; las ventas digitales usan la sucursal virtual 'Tienda online'. |  |
| `sk_canal` | INTEGER | FK | Canal de venta (FK a dim_canal). |  |
| `fuente_origen` | TEXT | Dimensión degenerada | Sistema de origen: POS (tiendas) o ECOMMERCE (web y app). |  |
| `numero_documento` | TEXT | Dimensión degenerada | Número de boleta o de pedido. | boleta, pedido, ticket, transacción |
| `nro_linea` | INTEGER | Dimensión degenerada | Número de línea dentro del documento. |  |
| `hora` | INTEGER | Atributo | Hora del día de la venta (0-23). |  |
| `cantidad` | INTEGER | Medida aditiva | Unidades vendidas en la línea. | unidades |
| `precio_unitario` | INTEGER | Medida no aditiva | Precio unitario de venta en pesos chilenos. |  |
| `monto_bruto` | INTEGER | Medida aditiva | cantidad × precio_unitario, en pesos. |  |
| `descuento` | INTEGER | Medida aditiva | Descuento aplicado a la línea, en pesos. |  |
| `monto_neto` | INTEGER | Medida aditiva | monto_bruto − descuento, en pesos. Incluye líneas devueltas: para la venta neta oficial usar la métrica venta_neta. |  |
| `es_devolucion` | INTEGER | Indicador | 1 si la línea fue devuelta por el cliente. |  |
| `id_carga` | TEXT | Auditoría | Carga ETL que insertó la fila (linaje). |  |
| `archivo_origen` | TEXT | Auditoría | Archivo fuente del que proviene la fila (linaje). |  |
| `fila_origen` | INTEGER | Auditoría | Fila del archivo fuente (linaje hasta Bronze). |  |

## `dim_fecha` — Dimensión conformada

Calendario diario con jerarquía año > semestre > trimestre > mes > día y feriados nacionales.

| Columna | Tipo | Rol | Descripción | Sinónimos |
|---|---|---|---|---|
| `sk_fecha` | INTEGER | PK | Clave AAAAMMDD. |  |
| `fecha` | TEXT | Atributo | Fecha en formato ISO (AAAA-MM-DD). | día |
| `dia` | INTEGER | Atributo | Día del mes. |  |
| `dia_semana` | INTEGER | Atributo | Día de la semana (1 = lunes … 7 = domingo). |  |
| `nombre_dia` | TEXT | Atributo | Nombre del día en español. |  |
| `semana_iso` | INTEGER | Atributo | Número de semana ISO. |  |
| `mes` | INTEGER | Jerarquía tiempo | Mes (1-12). |  |
| `nombre_mes` | TEXT | Atributo | Nombre del mes en español. |  |
| `anio_mes` | TEXT | Jerarquía tiempo | Período mensual AAAA-MM. | período, mes |
| `trimestre` | INTEGER | Jerarquía tiempo | Trimestre (1-4). | Q |
| `semestre` | INTEGER | Jerarquía tiempo | Semestre (1-2). |  |
| `anio` | INTEGER | Jerarquía tiempo | Año calendario. | año |
| `es_fin_de_semana` | INTEGER | Indicador | 1 si es sábado o domingo. |  |
| `es_festivo` | INTEGER | Indicador | 1 si es feriado nacional. |  |
| `nombre_festivo` | TEXT | Atributo | Nombre del feriado. |  |

## `dim_cliente` — Dimensión conformada · SCD tipo 2

Clientes identificados, seudonimizados. Cada cambio de comuna/región o de segmento crea una nueva versión con su vigencia, para que las ventas pasadas conserven la región y el segmento que el cliente tenía al comprar.

| Columna | Tipo | Rol | Descripción | Sinónimos |
|---|---|---|---|---|
| `sk_cliente` | INTEGER | PK | Clave sustituta de la versión. -1 = cliente no identificado. |  |
| `id_cliente` | TEXT | Clave de negocio | Seudónimo estable del RUT (SHA-256 con sal secreta). No permite recuperar el RUT. |  |
| `comuna` | TEXT | Atributo SCD2 | Comuna de residencia en la versión. |  |
| `region` | TEXT | Atributo SCD2 | Región de residencia en la versión. | región del cliente |
| `zona` | TEXT | Atributo SCD2 | Macrozona de residencia en la versión. |  |
| `segmento` | TEXT | Atributo SCD2 | Segmento comercial: Nuevo, Ocasional, Frecuente o VIP. |  |
| `fecha_registro` | TEXT | Atributo SCD1 | Fecha de registro en el CRM. |  |
| `fecha_inicio_vigencia` | TEXT | SCD2 | Desde cuándo rige la versión. |  |
| `fecha_fin_vigencia` | TEXT | SCD2 | Hasta cuándo rige la versión; 9999-12-31 = vigente. |  |
| `es_actual` | INTEGER | SCD2 | 1 si es la versión vigente. |  |
| `version` | INTEGER | SCD2 | Número correlativo de versión del cliente. |  |
| `id_carga` | TEXT | Auditoría | Carga que insertó la versión. |  |

## `dim_producto` — Dimensión conformada · SCD tipo 1 y tipo 3

Maestro de productos homologado entre ERP y e-commerce. Jerarquía categoría > subcategoría > producto. La categoría es SCD tipo 3: se guarda la categoría anterior para comparar antes y después de una reclasificación.

| Columna | Tipo | Rol | Descripción | Sinónimos |
|---|---|---|---|---|
| `sk_producto` | INTEGER | PK | Clave sustituta. |  |
| `cod_producto` | TEXT | Clave de negocio | Código del producto en el ERP. | SKU |
| `sku_web` | TEXT | Atributo SCD1 | Código del producto en el e-commerce (tabla de equivalencias). |  |
| `nombre_producto` | TEXT | Atributo SCD1 | Nombre comercial. | producto, artículo |
| `marca` | TEXT | Atributo SCD1 | Marca del producto. |  |
| `linea` | TEXT | Atributo SCD1 | Línea de precio: Básica, Estándar o Premium. |  |
| `subcategoria` | TEXT | Jerarquía producto | Subcategoría. |  |
| `categoria` | TEXT | Jerarquía producto · SCD3 | Categoría vigente: Tecnología, Hogar o Accesorios. | rubro, familia |
| `categoria_anterior` | TEXT | SCD3 | Categoría previa a la última reclasificación (SCD tipo 3). |  |
| `fecha_cambio_categoria` | TEXT | SCD3 | Fecha en que se registró la reclasificación. |  |
| `precio_lista` | INTEGER | Atributo SCD1 | Precio de lista vigente, en pesos. |  |
| `fecha_actualizacion` | TEXT | Auditoría | Última vez que la fila cambió. |  |
| `id_carga` | TEXT | Auditoría | Carga que insertó o actualizó la fila. |  |

## `dim_sucursal` — Dimensión conformada y espacial · SCD tipo 1

Sucursales con su ubicación geográfica. Jerarquía zona > región > comuna > sucursal. Las correcciones sobrescriben el valor (sin historia).

| Columna | Tipo | Rol | Descripción | Sinónimos |
|---|---|---|---|---|
| `sk_sucursal` | INTEGER | PK | Clave sustituta. |  |
| `cod_sucursal` | TEXT | Clave de negocio | Código de la sucursal (SUC-01 …). SUC-99 = Tienda online. |  |
| `nombre_sucursal` | TEXT | Atributo | Nombre comercial de la sucursal. | tienda, local |
| `tipo_sucursal` | TEXT | Atributo | Tienda calle, Mall o Virtual. |  |
| `direccion` | TEXT | Atributo SCD1 | Dirección postal. |  |
| `comuna` | TEXT | Jerarquía geográfica | Comuna de la sucursal. |  |
| `region` | TEXT | Jerarquía geográfica | Región de la sucursal. 'Canal online' para la tienda virtual. | región |
| `zona` | TEXT | Jerarquía geográfica | Macrozona: Norte, Centro, Sur, Austral u Online. |  |
| `pais` | TEXT | Jerarquía geográfica | País. |  |
| `latitud` | REAL | Atributo espacial | Latitud (WGS84) para mapas. |  |
| `longitud` | REAL | Atributo espacial | Longitud (WGS84) para mapas. |  |
| `fecha_apertura` | TEXT | Atributo | Fecha de apertura. |  |
| `fecha_actualizacion` | TEXT | Auditoría | Última vez que la fila cambió. |  |
| `id_carga` | TEXT | Auditoría | Carga que insertó o actualizó la fila. |  |

## `dim_canal` — Dimensión conformada

Canal por el que se realizó la venta.

| Columna | Tipo | Rol | Descripción | Sinónimos |
|---|---|---|---|---|
| `sk_canal` | INTEGER | PK | Clave sustituta. |  |
| `cod_canal` | TEXT | Clave de negocio | Código del canal: TIENDA, WEB, APP. |  |
| `nombre_canal` | TEXT | Atributo | Tienda física, Sitio web o App móvil. | canal, canal de venta |
| `tipo_canal` | TEXT | Jerarquía canal | Presencial o Digital. | online, físico |

## Métricas oficiales (capa semántica)

| Métrica | Definición | SQL sobre `vw_ventas` | Sinónimos |
|---|---|---|---|
| `venta_neta` | Venta neta oficial: monto neto de las líneas no devueltas. Las anuladas no llegan a Gold. | `SUM(venta_neta)` | ventas, venta neta, ingresos, facturación |
| `monto_devuelto` | Monto neto de las líneas devueltas. | `SUM(monto_devuelto)` | devoluciones |
| `tasa_devolucion` | Proporción del monto vendido que fue devuelto. | `SUM(monto_devuelto) * 1.0 / NULLIF(SUM(venta_neta) + SUM(monto_devuelto), 0)` |  |
| `unidades_vendidas` | Unidades de líneas no devueltas. | `SUM(CASE WHEN es_devolucion = 0 THEN unidades ELSE 0 END)` | unidades, cantidad vendida |
| `documentos` | Número de boletas o pedidos con venta efectiva. | `COUNT(DISTINCT CASE WHEN es_devolucion = 0 THEN numero_documento END)` | transacciones, boletas, pedidos |
| `ticket_promedio` | Venta neta dividida por el número de documentos con venta efectiva. | `SUM(venta_neta) * 1.0 / NULLIF(COUNT(DISTINCT CASE WHEN es_devolucion = 0 THEN numero_documento END), 0)` | ticket medio, valor promedio por compra |
| `clientes_activos` | Clientes identificados con al menos una compra no devuelta en el período. | `COUNT(DISTINCT CASE WHEN es_cliente_anonimo = 0 AND es_devolucion = 0 THEN id_cliente END)` | clientes que compraron |

## Jerarquías

- **tiempo:** anio → semestre → trimestre → anio_mes → fecha
- **geografia_sucursal:** zona_sucursal → region_sucursal → comuna_sucursal → sucursal
- **producto:** categoria → subcategoria → producto
- **canal:** tipo_canal → canal

## Reglas para asistentes de IA (NLQ / text-to-SQL)

1. Consultar solo vw_ventas, vw_kpi_mensual o agg_ventas_mes_region; nunca las capas Bronze o Silver.
2. La venta neta se calcula con la métrica venta_neta, no con monto_bruto ni monto_neto.
3. Para analizar dónde se vende usar region_sucursal; region_cliente indica dónde vivía el cliente al comprar (SCD tipo 2).
4. Las ventas digitales tienen region_sucursal = 'Canal online'.
5. Excluir es_cliente_anonimo = 1 al contar clientes.
6. Los nombres de canal válidos son 'Tienda física', 'Sitio web' y 'App móvil'.
7. Toda respuesta generada debe pasar por el checklist de validación humana antes de comunicarse.

## Ejemplos de preguntas en lenguaje natural

**¿Cuál fue la venta neta de la app en marzo de 2026?**

```sql
SELECT SUM(venta_neta) AS venta_neta FROM vw_ventas WHERE canal = 'App móvil' AND anio_mes = '2026-03'
```

**¿Qué región tuvo el mayor ticket promedio en tiendas físicas durante 2025?**

```sql
SELECT region_sucursal, SUM(venta_neta) * 1.0 / NULLIF(COUNT(DISTINCT CASE WHEN es_devolucion = 0 THEN numero_documento END), 0) AS ticket_promedio FROM vw_ventas WHERE canal = 'Tienda física' AND anio = 2025 GROUP BY region_sucursal ORDER BY ticket_promedio DESC LIMIT 1
```

**¿Cuántos clientes VIP compraron en el primer semestre de 2026?**

```sql
SELECT COUNT(DISTINCT id_cliente) FROM vw_ventas WHERE segmento_cliente = 'VIP' AND anio = 2026 AND semestre = 1 AND es_cliente_anonimo = 0 AND es_devolucion = 0
```
