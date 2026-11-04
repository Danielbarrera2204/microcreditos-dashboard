-- Esquema de la base de datos: Microcréditos (SQLite)
-- Tablas maestras: estados, clientes
-- Tablas transaccionales: solicitudes, cuotas

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS estados (
    id_estado INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre    TEXT NOT NULL,
    tipo      TEXT NOT NULL CHECK (tipo IN ('solicitud', 'cuota')),
    UNIQUE (nombre, tipo)
);

CREATE TABLE IF NOT EXISTS clientes (
    id_cliente        INTEGER PRIMARY KEY AUTOINCREMENT,
    documento         TEXT NOT NULL UNIQUE,
    ingresos_anuales  REAL NOT NULL CHECK (ingresos_anuales >= 0),
    puntaje_crediticio INTEGER,
    num_dependientes  INTEGER DEFAULT 0,
    valor_activos     REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS solicitudes (
    id_solicitud    INTEGER PRIMARY KEY AUTOINCREMENT,
    id_cliente      INTEGER NOT NULL,
    monto           REAL NOT NULL CHECK (monto > 0),
    plazo_meses     INTEGER NOT NULL CHECK (plazo_meses > 0),
    fecha_solicitud TEXT NOT NULL,          -- formato YYYY-MM-DD
    fecha_decision  TEXT,                   -- NULL mientras esté pendiente
    id_estado       INTEGER NOT NULL,
    FOREIGN KEY (id_cliente) REFERENCES clientes (id_cliente),
    FOREIGN KEY (id_estado)  REFERENCES estados (id_estado)
);

CREATE TABLE IF NOT EXISTS cuotas (
    id_cuota          INTEGER PRIMARY KEY AUTOINCREMENT,
    id_solicitud      INTEGER NOT NULL,
    numero_cuota      INTEGER NOT NULL CHECK (numero_cuota > 0),
    fecha_vencimiento TEXT NOT NULL,        -- formato YYYY-MM-DD
    valor_cuota       REAL NOT NULL CHECK (valor_cuota > 0),
    valor_pagado      REAL NOT NULL DEFAULT 0,
    fecha_pago        TEXT,                 -- NULL mientras no se pague
    id_estado         INTEGER NOT NULL,
    FOREIGN KEY (id_solicitud) REFERENCES solicitudes (id_solicitud),
    FOREIGN KEY (id_estado)    REFERENCES estados (id_estado),
    UNIQUE (id_solicitud, numero_cuota)
);

CREATE INDEX IF NOT EXISTS idx_solicitudes_cliente ON solicitudes (id_cliente);
CREATE INDEX IF NOT EXISTS idx_solicitudes_estado  ON solicitudes (id_estado);
CREATE INDEX IF NOT EXISTS idx_cuotas_solicitud    ON cuotas (id_solicitud);

-- Datos maestros de estados
INSERT OR IGNORE INTO estados (nombre, tipo) VALUES
    ('Pendiente',   'solicitud'),
    ('Aprobada',    'solicitud'),
    ('Rechazada',   'solicitud'),
    ('Desembolsada','solicitud'),
    ('Pendiente',   'cuota'),
    ('Pagada',      'cuota'),
    ('Vencida',     'cuota');
