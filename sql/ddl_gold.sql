-- =====================================================================
-- Capa Gold · DataRetail 360 · Esquema estrella del proceso Ventas
-- Grano de fact_ventas: una línea de producto de cada boleta o pedido.
-- Motor: SQLite.
-- =====================================================================

-- ---------------------------------------------------------------- Fecha
-- Dimensión conformada. Jerarquía: día -> mes -> trimestre -> semestre -> año.
CREATE TABLE IF NOT EXISTS dim_fecha (
    sk_fecha          INTEGER PRIMARY KEY,          -- clave inteligente AAAAMMDD
    fecha             TEXT    NOT NULL UNIQUE,      -- ISO 8601
    dia               INTEGER NOT NULL,
    dia_semana        INTEGER NOT NULL,             -- 1 = lunes ... 7 = domingo
    nombre_dia        TEXT    NOT NULL,
    semana_iso        INTEGER NOT NULL,
    mes               INTEGER NOT NULL,
    nombre_mes        TEXT    NOT NULL,
    anio_mes          TEXT    NOT NULL,             -- '2025-03'
    trimestre         INTEGER NOT NULL,
    semestre          INTEGER NOT NULL,
    anio              INTEGER NOT NULL,
    es_fin_de_semana  INTEGER NOT NULL CHECK (es_fin_de_semana IN (0, 1)),
    es_festivo        INTEGER NOT NULL CHECK (es_festivo IN (0, 1)),
    nombre_festivo    TEXT
);

-- ---------------------------------------------------------------- Canal
CREATE TABLE IF NOT EXISTS dim_canal (
    sk_canal      INTEGER PRIMARY KEY,
    cod_canal     TEXT NOT NULL UNIQUE,                -- TIENDA, WEB, APP
    nombre_canal  TEXT NOT NULL,
    tipo_canal    TEXT NOT NULL                        -- Presencial / Digital
);

-- -------------------------------------------------------------- Sucursal
-- Dimensión espacial. Jerarquía: sucursal -> comuna -> región -> zona -> país.
-- SCD tipo 1: las correcciones (p. ej. dirección) sobrescriben el valor.
CREATE TABLE IF NOT EXISTS dim_sucursal (
    sk_sucursal          INTEGER PRIMARY KEY AUTOINCREMENT,
    cod_sucursal         TEXT NOT NULL UNIQUE,         -- clave de negocio
    nombre_sucursal      TEXT NOT NULL,
    tipo_sucursal        TEXT NOT NULL,                -- Tienda calle / Mall / Virtual
    direccion            TEXT,
    comuna               TEXT NOT NULL,
    region               TEXT NOT NULL,
    zona                 TEXT NOT NULL,
    pais                 TEXT NOT NULL,
    latitud              REAL,
    longitud             REAL,
    fecha_apertura       TEXT,
    fecha_actualizacion  TEXT NOT NULL,
    id_carga             TEXT NOT NULL
);

-- -------------------------------------------------------------- Producto
-- Jerarquía: producto -> subcategoría -> categoría.
-- SCD tipo 1: nombre, marca, línea, subcategoría, precio de lista, SKU web.
-- SCD tipo 3: categoría (se guarda la categoría anterior para comparar antes/después).
CREATE TABLE IF NOT EXISTS dim_producto (
    sk_producto             INTEGER PRIMARY KEY AUTOINCREMENT,
    cod_producto            TEXT NOT NULL UNIQUE,      -- clave de negocio (ERP)
    sku_web                 TEXT,                      -- código homologado del e-commerce
    nombre_producto         TEXT NOT NULL,
    marca                   TEXT,
    linea                   TEXT,
    subcategoria            TEXT NOT NULL,
    categoria               TEXT NOT NULL,             -- valor vigente
    categoria_anterior      TEXT,                      -- SCD 3: valor previo
    fecha_cambio_categoria  TEXT,
    precio_lista            INTEGER,
    fecha_actualizacion     TEXT NOT NULL,
    id_carga                TEXT NOT NULL
);

-- --------------------------------------------------------------- Cliente
-- SCD tipo 2: comuna/región/zona y segmento conservan su historia completa.
-- id_cliente es un seudónimo del RUT (SHA-256 con sal secreta): Gold no guarda
-- RUT, nombre, correo ni teléfono (minimización, Ley 21.719).
CREATE TABLE IF NOT EXISTS dim_cliente (
    sk_cliente             INTEGER PRIMARY KEY AUTOINCREMENT,
    id_cliente             TEXT    NOT NULL,           -- clave de negocio seudonimizada
    comuna                 TEXT    NOT NULL,
    region                 TEXT    NOT NULL,
    zona                   TEXT    NOT NULL,
    segmento               TEXT    NOT NULL,
    fecha_registro         TEXT,
    fecha_inicio_vigencia  TEXT    NOT NULL,
    fecha_fin_vigencia     TEXT    NOT NULL,           -- '9999-12-31' = versión vigente
    es_actual              INTEGER NOT NULL CHECK (es_actual IN (0, 1)),
    version                INTEGER NOT NULL,
    id_carga               TEXT    NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_cliente_version  ON dim_cliente (id_cliente, version);
CREATE INDEX        IF NOT EXISTS ix_dim_cliente_vigencia ON dim_cliente (id_cliente, fecha_inicio_vigencia, fecha_fin_vigencia);

-- Miembro desconocido: ventas sin cliente identificado (boletas anónimas, invitados web).
INSERT OR IGNORE INTO dim_cliente
    (sk_cliente, id_cliente, comuna, region, zona, segmento, fecha_registro,
     fecha_inicio_vigencia, fecha_fin_vigencia, es_actual, version, id_carga)
VALUES (-1, 'NO_IDENTIFICADO', 'No identificado', 'No identificado', 'No identificado',
        'No identificado', NULL, '1900-01-01', '9999-12-31', 1, 1, 'INICIAL');

-- ------------------------------------------------------- Hecho: Ventas
-- Tabla de hechos transaccional. Medidas aditivas: cantidad, montos.
CREATE TABLE IF NOT EXISTS fact_ventas (
    sk_venta          INTEGER PRIMARY KEY AUTOINCREMENT,
    sk_fecha          INTEGER NOT NULL REFERENCES dim_fecha (sk_fecha),
    sk_cliente        INTEGER NOT NULL REFERENCES dim_cliente (sk_cliente),
    sk_producto       INTEGER NOT NULL REFERENCES dim_producto (sk_producto),
    sk_sucursal       INTEGER NOT NULL REFERENCES dim_sucursal (sk_sucursal),
    sk_canal          INTEGER NOT NULL REFERENCES dim_canal (sk_canal),
    fuente_origen     TEXT    NOT NULL,                -- dimensión degenerada: POS / ECOMMERCE
    numero_documento  TEXT    NOT NULL,                -- dimensión degenerada: boleta o pedido
    nro_linea         INTEGER NOT NULL,
    hora              INTEGER NOT NULL CHECK (hora BETWEEN 0 AND 23),
    cantidad          INTEGER NOT NULL CHECK (cantidad > 0),
    precio_unitario   INTEGER NOT NULL CHECK (precio_unitario > 0),
    monto_bruto       INTEGER NOT NULL,
    descuento         INTEGER NOT NULL CHECK (descuento >= 0),
    monto_neto        INTEGER NOT NULL,
    es_devolucion     INTEGER NOT NULL CHECK (es_devolucion IN (0, 1)),
    id_carga          TEXT    NOT NULL,                -- linaje hacia Bronze
    archivo_origen    TEXT    NOT NULL,
    fila_origen       INTEGER NOT NULL,
    UNIQUE (fuente_origen, numero_documento, nro_linea) -- garantiza idempotencia
);
-- Índices en las claves foráneas usadas en filtros y joins.
CREATE INDEX IF NOT EXISTS ix_fact_ventas_fecha    ON fact_ventas (sk_fecha);
CREATE INDEX IF NOT EXISTS ix_fact_ventas_producto ON fact_ventas (sk_producto);
CREATE INDEX IF NOT EXISTS ix_fact_ventas_sucursal ON fact_ventas (sk_sucursal);
CREATE INDEX IF NOT EXISTS ix_fact_ventas_cliente  ON fact_ventas (sk_cliente);
CREATE INDEX IF NOT EXISTS ix_fact_ventas_canal    ON fact_ventas (sk_canal);

-- ------------------------------------------------- Tablas de control ETL
CREATE TABLE IF NOT EXISTS etl_control_cargas (
    id_carga                     TEXT PRIMARY KEY,
    lote                         INTEGER NOT NULL,
    inicio                       TEXT NOT NULL,
    fin                          TEXT,
    estado                       TEXT NOT NULL,        -- EN_PROCESO / EXITOSA / FALLIDA
    lineas_leidas                INTEGER,
    lineas_validas               INTEGER,
    lineas_rechazadas            INTEGER,
    lineas_excluidas             INTEGER,
    filas_insertadas_fact        INTEGER,
    filas_omitidas_ya_cargadas   INTEGER,
    version_codigo               TEXT,                 -- commit de Git que ejecutó la carga
    mensaje                      TEXT
);

CREATE TABLE IF NOT EXISTS etl_rechazos (
    id_rechazo      INTEGER PRIMARY KEY AUTOINCREMENT,
    id_carga        TEXT NOT NULL,
    tipo            TEXT NOT NULL,                     -- RECHAZO / EXCLUSION
    entidad         TEXT NOT NULL,
    regla           TEXT NOT NULL,
    motivo          TEXT NOT NULL,
    archivo_origen  TEXT NOT NULL,
    fila_origen     INTEGER NOT NULL,
    clave_registro  TEXT,
    registro        TEXT                               -- registro original, datos personales enmascarados
);
CREATE INDEX IF NOT EXISTS ix_etl_rechazos_carga ON etl_rechazos (id_carga, regla);

CREATE TABLE IF NOT EXISTS etl_validaciones (
    id_carga     TEXT NOT NULL,
    validacion   TEXT NOT NULL,
    resultado    TEXT NOT NULL,                        -- OK / FALLA
    detalle      TEXT,
    PRIMARY KEY (id_carga, validacion)
);

-- ------------------------------ Agregado precalculado (vista materializada)
-- SQLite no tiene vistas materializadas: se emulan con una tabla que el
-- pipeline refresca al final de cada carga.
CREATE TABLE IF NOT EXISTS agg_ventas_mes_region (
    anio_mes         TEXT    NOT NULL,
    region           TEXT    NOT NULL,
    canal            TEXT    NOT NULL,
    venta_neta       INTEGER NOT NULL,
    monto_devuelto   INTEGER NOT NULL,
    unidades         INTEGER NOT NULL,
    documentos       INTEGER NOT NULL,
    ticket_promedio  INTEGER,
    fecha_refresco   TEXT    NOT NULL,
    PRIMARY KEY (anio_mes, region, canal)
);
