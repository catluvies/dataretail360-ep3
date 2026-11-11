-- =====================================================================
-- Capa semántica en SQL: vistas con nombres de negocio, la regla oficial
-- de venta neta y los KPIs de inventario. Desde aquí consultan los
-- dashboards y la IA.
-- =====================================================================

DROP VIEW IF EXISTS vw_kpi_inventario_mensual;
DROP VIEW IF EXISTS vw_inventario;
DROP VIEW IF EXISTS vw_kpi_mensual;
DROP VIEW IF EXISTS vw_ventas;

-- Vista detalle: una fila por línea vendida, ya unida a sus dimensiones.
-- Regla oficial de venta neta: monto neto de líneas no devueltas.
-- Las transacciones anuladas nunca llegan a Gold (regla VEN-03 en Silver).
CREATE VIEW vw_ventas AS
SELECT
    f.sk_venta,
    d.fecha,
    d.anio,
    d.semestre,
    d.trimestre,
    d.mes,
    d.nombre_mes,
    d.anio_mes,
    d.nombre_dia,
    d.es_fin_de_semana,
    d.es_festivo,
    f.hora,
    c.cod_canal,
    c.nombre_canal                                      AS canal,
    c.tipo_canal,
    s.cod_sucursal,
    s.nombre_sucursal                                   AS sucursal,
    s.tipo_sucursal,
    s.comuna                                            AS comuna_sucursal,
    s.region                                            AS region_sucursal,
    s.zona                                              AS zona_sucursal,
    p.cod_producto,
    p.nombre_producto                                   AS producto,
    p.marca,
    p.linea                                             AS linea_producto,
    p.subcategoria,
    p.categoria,
    p.categoria_anterior,
    cl.id_cliente,
    cl.segmento                                         AS segmento_cliente,
    cl.region                                           AS region_cliente,
    CASE WHEN f.sk_cliente = -1 THEN 1 ELSE 0 END       AS es_cliente_anonimo,
    f.fuente_origen,
    f.numero_documento,
    f.nro_linea,
    f.cantidad                                          AS unidades,
    f.precio_unitario,
    f.monto_bruto,
    f.descuento,
    f.monto_neto,
    f.es_devolucion,
    CASE WHEN f.es_devolucion = 0 THEN f.monto_neto ELSE 0 END AS venta_neta,
    CASE WHEN f.es_devolucion = 1 THEN f.monto_neto ELSE 0 END AS monto_devuelto,
    f.id_carga
FROM fact_ventas f
JOIN dim_fecha    d  ON d.sk_fecha    = f.sk_fecha
JOIN dim_canal    c  ON c.sk_canal    = f.sk_canal
JOIN dim_sucursal s  ON s.sk_sucursal = f.sk_sucursal
JOIN dim_producto p  ON p.sk_producto = f.sk_producto
JOIN dim_cliente  cl ON cl.sk_cliente = f.sk_cliente;

-- KPIs mensuales por canal.
CREATE VIEW vw_kpi_mensual AS
SELECT
    anio_mes,
    canal,
    SUM(venta_neta)                                                        AS venta_neta,
    SUM(monto_devuelto)                                                    AS monto_devuelto,
    SUM(CASE WHEN es_devolucion = 0 THEN unidades ELSE 0 END)              AS unidades_vendidas,
    COUNT(DISTINCT CASE WHEN es_devolucion = 0 THEN numero_documento END)  AS documentos,
    ROUND(SUM(venta_neta) * 1.0
          / NULLIF(COUNT(DISTINCT CASE WHEN es_devolucion = 0 THEN numero_documento END), 0)) AS ticket_promedio,
    COUNT(DISTINCT CASE WHEN es_cliente_anonimo = 0 AND es_devolucion = 0 THEN id_cliente END) AS clientes_activos
FROM vw_ventas
GROUP BY anio_mes, canal;

-- Vista detalle del inventario: una fila por producto, sucursal y día.
CREATE VIEW vw_inventario AS
SELECT
    f.sk_inventario,
    d.fecha,
    d.anio,
    d.semestre,
    d.trimestre,
    d.mes,
    d.nombre_mes,
    d.anio_mes,
    s.cod_sucursal,
    s.nombre_sucursal                                   AS sucursal,
    s.tipo_sucursal,
    s.comuna                                            AS comuna_sucursal,
    s.region                                            AS region_sucursal,
    s.zona                                              AS zona_sucursal,
    p.cod_producto,
    p.nombre_producto                                   AS producto,
    p.marca,
    p.linea                                             AS linea_producto,
    p.subcategoria,
    p.categoria,
    f.stock_cierre,
    f.unidades_recibidas,
    f.unidades_vendidas,
    f.stock_minimo,
    f.es_quiebre,
    f.id_carga
FROM fact_inventario f
JOIN dim_fecha    d ON d.sk_fecha    = f.sk_fecha
JOIN dim_sucursal s ON s.sk_sucursal = f.sk_sucursal
JOIN dim_producto p ON p.sk_producto = f.sk_producto;

-- KPIs mensuales de inventario (Ficha de KPI: K3 tasa de quiebre, K4 días de cobertura).
CREATE VIEW vw_kpi_inventario_mensual AS
SELECT
    anio_mes,
    SUM(registros)                                                         AS registros,
    SUM(dias_quiebre)                                                      AS dias_quiebre,
    ROUND(100.0 * SUM(dias_quiebre) / NULLIF(SUM(registros), 0), 2)        AS tasa_quiebre,
    SUM(stock_cierre_mes)                                                  AS stock_cierre_mes,
    SUM(unidades_vendidas_28d)                                             AS unidades_vendidas_28d,
    ROUND(SUM(stock_cierre_mes) * 28.0 / NULLIF(SUM(unidades_vendidas_28d), 0), 1) AS dias_cobertura
FROM agg_inventario_mes
GROUP BY anio_mes;
