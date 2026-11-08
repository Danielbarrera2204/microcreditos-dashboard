"""Cálculo de KPIs y series del dashboard (sin Streamlit).

Lo usa dashboard.py. También se puede ejecutar directamente para validar que los
números del dashboard coinciden con los datos reales de la base (Semana 3,
Actividad 4 de la guía):

    python kpis.py
"""
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

DB_PATH = Path(__file__).resolve().parent / "db" / "microcreditos.db"
DIAS_MORA = 30           # una cuota sin pagar con más de 30 días de vencida = mora
DIAS_ENTRE_CUOTAS = 30   # igual que en db/load_csv.py y app.py

# Metas definidas en el documento de la Semana 1
METAS = {"morosos_pct": 8.0, "dias_aprobacion": 2.0, "recuperacion_pct": 85.0}

# Créditos desembolsados cuya solicitud cae en el rango de fechas elegido
BASE = """
WITH base AS (
    SELECT s.id_solicitud
    FROM solicitudes s
    JOIN estados e ON e.id_estado = s.id_estado
    WHERE e.nombre = 'Desembolsada' AND e.tipo = 'solicitud'
      AND s.fecha_solicitud BETWEEN :d1 AND :d2
)
"""


def conectar() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def parametros(d1: date, d2: date, hoy: date | None = None) -> dict:
    hoy = hoy or date.today()
    return {
        "d1": d1.isoformat(),
        "d2": d2.isoformat(),
        "hoy": hoy.isoformat(),
        "corte": (hoy - timedelta(days=DIAS_MORA)).isoformat(),
    }


def rango_fechas(conn: sqlite3.Connection) -> tuple[date, date]:
    minimo, maximo = conn.execute(
        "SELECT MIN(fecha_solicitud), MAX(fecha_solicitud) FROM solicitudes"
    ).fetchone()
    return date.fromisoformat(minimo), date.fromisoformat(maximo)


def _pct(parte, total):
    return round(100.0 * parte / total, 2) if total else None


# ------------------------------------------------------------------------- KPIs
def calcular_kpis(conn: sqlite3.Connection, p: dict) -> dict:
    """Los 3 KPIs de la Semana 1 más las métricas globales, con SQL."""
    (desembolsadas, morosos, monto_otorgado, monto_recuperado,
     monto_exigible, recuperado_exigible) = conn.execute(
        BASE + """
        SELECT
          (SELECT COUNT(*) FROM base),
          (SELECT COUNT(DISTINCT q.id_solicitud) FROM cuotas q
             JOIN base b ON b.id_solicitud = q.id_solicitud
             WHERE q.valor_pagado < q.valor_cuota AND q.fecha_vencimiento < :corte),
          (SELECT COALESCE(SUM(s.monto), 0) FROM solicitudes s
             JOIN base b ON b.id_solicitud = s.id_solicitud),
          (SELECT COALESCE(SUM(q.valor_pagado), 0) FROM cuotas q
             JOIN base b ON b.id_solicitud = q.id_solicitud),
          (SELECT COALESCE(SUM(q.valor_cuota), 0) FROM cuotas q
             JOIN base b ON b.id_solicitud = q.id_solicitud
             WHERE q.fecha_vencimiento <= :hoy),
          (SELECT COALESCE(SUM(q.valor_pagado), 0) FROM cuotas q
             JOIN base b ON b.id_solicitud = q.id_solicitud
             WHERE q.fecha_vencimiento <= :hoy)
        """,
        p,
    ).fetchone()

    dias = conn.execute(
        "SELECT AVG(julianday(fecha_decision) - julianday(fecha_solicitud)) "
        "FROM solicitudes WHERE fecha_decision IS NOT NULL "
        "AND fecha_solicitud BETWEEN :d1 AND :d2",
        p,
    ).fetchone()[0]

    solicitudes, aprobadas, rechazadas = conn.execute(
        "SELECT COUNT(*), "
        "SUM(CASE WHEN e.nombre IN ('Aprobada', 'Desembolsada') THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN e.nombre = 'Rechazada' THEN 1 ELSE 0 END) "
        "FROM solicitudes s JOIN estados e ON e.id_estado = s.id_estado "
        "WHERE e.tipo = 'solicitud' AND s.fecha_solicitud BETWEEN :d1 AND :d2",
        p,
    ).fetchone()
    aprobadas, rechazadas = aprobadas or 0, rechazadas or 0

    return {
        "solicitudes": solicitudes,
        "desembolsadas": desembolsadas,
        "tasa_aprobacion_pct": _pct(aprobadas, aprobadas + rechazadas),
        "monto_otorgado": round(monto_otorgado, 2),
        "monto_recuperado": round(monto_recuperado, 2),
        "morosos": morosos,
        "morosos_pct": _pct(morosos, desembolsadas),
        "dias_aprobacion": round(dias, 2) if dias is not None else None,
        "recuperacion_otorgado_pct": _pct(monto_recuperado, monto_otorgado),
        "recuperacion_exigible_pct": _pct(recuperado_exigible, monto_exigible),
    }


# ----------------------------------------------------------------------- series
def solicitudes_por_mes(conn: sqlite3.Connection, p: dict) -> pd.DataFrame:
    return pd.read_sql_query(
        """
        SELECT strftime('%Y-%m', s.fecha_solicitud) AS mes,
               CASE e.nombre WHEN 'Rechazada' THEN 'Rechazada'
                             WHEN 'Pendiente' THEN 'Pendiente'
                             ELSE 'Aprobada' END AS resultado,
               COUNT(*) AS solicitudes
        FROM solicitudes s JOIN estados e ON e.id_estado = s.id_estado
        WHERE e.tipo = 'solicitud' AND s.fecha_solicitud BETWEEN :d1 AND :d2
        GROUP BY mes, resultado ORDER BY mes
        """,
        conn, params=p,
    )


def flujo_mensual(conn: sqlite3.Connection, p: dict) -> pd.DataFrame:
    """Monto desembolsado y monto recaudado por mes.

    La fecha de desembolso se deduce de la primera cuota: vence 30 días después.
    """
    desembolsado = pd.read_sql_query(
        BASE + f"""
        , desemb AS (
            SELECT s.id_solicitud, s.monto,
                   date(MIN(q.fecha_vencimiento), '-{DIAS_ENTRE_CUOTAS} days') AS f
            FROM base b
            JOIN solicitudes s ON s.id_solicitud = b.id_solicitud
            JOIN cuotas q ON q.id_solicitud = b.id_solicitud
            GROUP BY s.id_solicitud
        )
        SELECT strftime('%Y-%m', f) AS mes, SUM(monto) AS desembolsado
        FROM desemb GROUP BY mes
        """,
        conn, params=p,
    )
    recaudado = pd.read_sql_query(
        BASE + """
        SELECT strftime('%Y-%m', q.fecha_pago) AS mes, SUM(q.valor_pagado) AS recaudado
        FROM cuotas q JOIN base b ON b.id_solicitud = q.id_solicitud
        WHERE q.fecha_pago IS NOT NULL GROUP BY mes
        """,
        conn, params=p,
    )
    flujo = desembolsado.merge(recaudado, on="mes", how="outer").fillna(0)
    return flujo.sort_values("mes").reset_index(drop=True)


def morosidad_por_puntaje(conn: sqlite3.Connection, p: dict) -> pd.DataFrame:
    df = pd.read_sql_query(
        BASE + """
        SELECT CASE WHEN c.puntaje_crediticio < 600 THEN '300-599'
                    WHEN c.puntaje_crediticio < 700 THEN '600-699'
                    WHEN c.puntaje_crediticio < 800 THEN '700-799'
                    ELSE '800-900' END AS rango,
               COUNT(*) AS creditos,
               SUM(CASE WHEN m.id_solicitud IS NOT NULL THEN 1 ELSE 0 END) AS morosos
        FROM base b
        JOIN solicitudes s ON s.id_solicitud = b.id_solicitud
        JOIN clientes c ON c.id_cliente = s.id_cliente
        LEFT JOIN (
            SELECT DISTINCT id_solicitud FROM cuotas
            WHERE valor_pagado < valor_cuota AND fecha_vencimiento < :corte
        ) m ON m.id_solicitud = b.id_solicitud
        GROUP BY rango ORDER BY rango
        """,
        conn, params=p,
    )
    df["pct_morosos"] = (100.0 * df["morosos"] / df["creditos"]).round(2)
    return df


def detalle_solicitudes(conn: sqlite3.Connection, p: dict) -> pd.DataFrame:
    df = pd.read_sql_query(
        """
        SELECT s.id_solicitud AS "Solicitud",
               c.documento AS "Documento",
               c.puntaje_crediticio AS "Puntaje",
               s.monto AS "Monto",
               s.plazo_meses AS "Plazo (meses)",
               s.fecha_solicitud AS "Fecha solicitud",
               s.fecha_decision AS "Fecha decisión",
               e.nombre AS "Estado",
               COALESCE(q.pagadas, 0) AS "Cuotas pagadas",
               COALESCE(q.total, 0) AS "Cuotas totales",
               COALESCE(q.moroso, 0) AS moroso
        FROM solicitudes s
        JOIN clientes c ON c.id_cliente = s.id_cliente
        JOIN estados e ON e.id_estado = s.id_estado
        LEFT JOIN (
            SELECT id_solicitud, COUNT(*) AS total,
                   SUM(valor_pagado >= valor_cuota) AS pagadas,
                   MAX(valor_pagado < valor_cuota AND fecha_vencimiento < :corte) AS moroso
            FROM cuotas GROUP BY id_solicitud
        ) q ON q.id_solicitud = s.id_solicitud
        WHERE s.fecha_solicitud BETWEEN :d1 AND :d2
        ORDER BY s.id_solicitud DESC
        """,
        conn, params=p,
    )
    df["Moroso"] = df.pop("moroso").map({1: "Sí", 0: "No"})
    return df


# ------------------------------------------------------------------- validación
def calculo_independiente(conn: sqlite3.Connection, d1: date, d2: date, hoy: date) -> dict:
    """Recalcula los KPIs con pandas, sin reutilizar las consultas SQL de arriba."""
    sol = pd.read_sql_query(
        "SELECT s.id_solicitud, s.monto, s.fecha_solicitud, s.fecha_decision, "
        "e.nombre AS estado FROM solicitudes s JOIN estados e ON e.id_estado = s.id_estado",
        conn,
    )
    cuo = pd.read_sql_query("SELECT * FROM cuotas", conn)
    sol["fecha_solicitud"] = pd.to_datetime(sol["fecha_solicitud"])
    sol["fecha_decision"] = pd.to_datetime(sol["fecha_decision"])
    cuo["fecha_vencimiento"] = pd.to_datetime(cuo["fecha_vencimiento"])

    en_rango = sol[(sol["fecha_solicitud"] >= pd.Timestamp(d1)) & (sol["fecha_solicitud"] <= pd.Timestamp(d2))]
    desemb = en_rango[en_rango["estado"] == "Desembolsada"]
    c = cuo[cuo["id_solicitud"].isin(desemb["id_solicitud"])]

    corte = pd.Timestamp(hoy) - pd.Timedelta(days=DIAS_MORA)
    morosos = c[(c["valor_pagado"] < c["valor_cuota"]) & (c["fecha_vencimiento"] < corte)]["id_solicitud"].nunique()
    exigibles = c[c["fecha_vencimiento"] <= pd.Timestamp(hoy)]
    decididas = en_rango.dropna(subset=["fecha_decision"])
    dias = (decididas["fecha_decision"] - decididas["fecha_solicitud"]).dt.days.mean()
    otorgado = desemb["monto"].sum()

    return {
        "solicitudes": len(en_rango),
        "desembolsadas": len(desemb),
        "monto_otorgado": round(float(otorgado), 2),
        "morosos_pct": _pct(morosos, len(desemb)),
        "dias_aprobacion": round(float(dias), 2) if pd.notna(dias) else None,
        "recuperacion_otorgado_pct": _pct(c["valor_pagado"].sum(), otorgado),
        "recuperacion_exigible_pct": _pct(exigibles["valor_pagado"].sum(), exigibles["valor_cuota"].sum()),
    }


ETIQUETAS = [
    ("solicitudes", "Solicitudes del periodo"),
    ("desembolsadas", "Créditos desembolsados"),
    ("monto_otorgado", "Monto otorgado"),
    ("morosos_pct", "% créditos morosos"),
    ("dias_aprobacion", "Días promedio de aprobación"),
    ("recuperacion_otorgado_pct", "Recuperado vs. otorgado (%)"),
    ("recuperacion_exigible_pct", "Recuperado vs. exigible (%)"),
]


def _iguales(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) < 0.01


def validar() -> bool:
    """Compara los KPIs del dashboard con un cálculo independiente en pandas."""
    if not DB_PATH.exists():
        print(f"No encuentro la base de datos en {DB_PATH}")
        return False
    conn = conectar()
    hoy = date.today()
    d_min, d_max = rango_fechas(conn)
    periodos = {
        "Todo el historial": (d_min, d_max),
        "Últimos 6 meses": (max(d_min, hoy - timedelta(days=182)), d_max),
    }
    todo_ok = True
    for nombre, (d1, d2) in periodos.items():
        dashboard = calcular_kpis(conn, parametros(d1, d2, hoy))
        referencia = calculo_independiente(conn, d1, d2, hoy)
        print(f"\n{nombre} ({d1} a {d2})")
        print(f"  {'KPI':<32}{'Dashboard':>16}{'Pandas':>16}  Resultado")
        for clave, etiqueta in ETIQUETAS:
            ok = _iguales(dashboard[clave], referencia[clave])
            todo_ok &= ok
            print(f"  {etiqueta:<32}{str(dashboard[clave]):>16}{str(referencia[clave]):>16}  {'OK' if ok else 'DIFERENTE'}")
    conn.close()
    print("\nTodas las métricas coinciden." if todo_ok else "\nHay diferencias: revisar.")
    return todo_ok


if __name__ == "__main__":
    sys.exit(0 if validar() else 1)