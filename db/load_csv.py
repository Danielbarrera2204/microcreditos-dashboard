"""Carga el CSV de Kaggle en SQLite y simula las fechas y cuotas que el CSV no trae.

Qué hace:
  1. Lee data/raw/loan_approval_dataset.csv y lo limpia (espacios sobrantes en
     encabezados y valores, activos negativos).
  2. Toma una muestra estratificada de N_REGISTROS filas (la guía pide 200 a 1.000),
     conservando la proporción de aprobados y rechazados.
  3. Carga clientes y solicitudes con los datos reales del CSV.
  4. Simula lo que el CSV no trae: fechas de solicitud y de decisión, y las cuotas
     de los créditos aprobados con sus pagos. La probabilidad de que un cliente deje
     de pagar depende de su puntaje crediticio.

Uso:
    python db/load_csv.py            # carga los datos si la base está vacía
    python db/load_csv.py --reset    # borra la base y la vuelve a cargar
"""
import argparse
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from init_db import DB_PATH, init_db

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "raw" / "loan_approval_dataset.csv"

# --- Parámetros de la simulación (se pueden ajustar) ---------------------------
N_REGISTROS = 1000          # la guía pide entre 200 y 1.000 registros históricos
SEMILLA = 42                # misma semilla = mismos datos en cada ejecución
MESES_HISTORIAL = 18        # las solicitudes se reparten en los últimos 18 meses
LOAN_TERM_EN_MESES = True   # True: loan_term (2 a 20) se lee como meses; False: como años
DIAS_ENTRE_CUOTAS = 30      # las cuotas vencen cada 30 días desde el desembolso

ACTIVOS = [
    "residential_assets_value",
    "commercial_assets_value",
    "luxury_assets_value",
    "bank_asset_value",
]


def leer_csv(ruta: Path, n: int, semilla: int) -> pd.DataFrame:
    """Lee el CSV, lo limpia y devuelve una muestra estratificada por loan_status."""
    df = pd.read_csv(ruta)
    df.columns = df.columns.str.strip()
    for col in ("education", "self_employed", "loan_status"):
        df[col] = df[col].str.strip()

    # El CSV trae un valor negativo en activos residenciales: se lleva a 0
    df[ACTIVOS] = df[ACTIVOS].clip(lower=0)

    if n < len(df):
        df = df.groupby("loan_status").sample(frac=n / len(df), random_state=semilla)
    return df.sort_values("loan_id").reset_index(drop=True)


def simular_cuotas(rng, id_solicitud, monto, plazo, f_desembolso, puntaje, hoy, estados):
    """Genera las cuotas de un crédito desembolsado y simula sus pagos.

    - Cuota fija sin interés: monto / plazo (el último valor ajusta los centavos).
    - Con probabilidad p_incumple (mayor mientras menor el puntaje) el cliente deja
      de pagar desde una cuota al azar; sus cuotas siguientes quedan sin pagar.
    - Los demás pagan casi siempre a tiempo, con atrasos de 0 a 20 días.
    - Una cuota sin pago cuyo vencimiento ya pasó queda 'Vencida'; si aún no
      vence queda 'Pendiente'.
    """
    p_incumple = float(np.clip((750 - puntaje) / 1000, 0.02, 0.25))
    incumple = rng.random() < p_incumple
    cuota_corte = int(rng.integers(1, plazo + 1)) if incumple else None

    base = round(monto / plazo, 2)
    filas = []
    for k in range(1, plazo + 1):
        valor = base if k < plazo else round(monto - base * (plazo - 1), 2)
        vence = f_desembolso + timedelta(days=DIAS_ENTRE_CUOTAS * k)

        f_pago = None
        if not (incumple and k >= cuota_corte):
            retraso = int(rng.choice([0, 2, 5, 10, 20], p=[0.70, 0.12, 0.09, 0.06, 0.03]))
            if vence + timedelta(days=retraso) <= hoy:
                f_pago = vence + timedelta(days=retraso)

        if f_pago:
            estado, pagado = "Pagada", valor
        elif vence <= hoy:
            estado, pagado = "Vencida", 0.0
        else:
            estado, pagado = "Pendiente", 0.0

        filas.append((
            id_solicitud, k, vence.isoformat(), valor, pagado,
            f_pago.isoformat() if f_pago else None,
            estados[(estado, "cuota")],
        ))
    return filas


def cargar(conn: sqlite3.Connection, df: pd.DataFrame, hoy: date, rng) -> dict:
    """Inserta clientes, solicitudes y cuotas. Devuelve un conteo de lo cargado."""
    conn.execute("PRAGMA foreign_keys = ON")
    estados = {
        (nombre, tipo): id_estado
        for id_estado, nombre, tipo in conn.execute(
            "SELECT id_estado, nombre, tipo FROM estados"
        )
    }

    # Clientes: el CSV no trae documento de identidad, se genera a partir de loan_id
    conn.executemany(
        "INSERT INTO clientes (documento, ingresos_anuales, puntaje_crediticio, "
        "num_dependientes, valor_activos) VALUES (?, ?, ?, ?, ?)",
        [
            (
                f"DOC{int(r.loan_id):06d}",
                float(r.income_annum),
                int(r.cibil_score),
                int(r.no_of_dependents),
                float(sum(getattr(r, c) for c in ACTIVOS)),
            )
            for r in df.itertuples(index=False)
        ],
    )
    ids_cliente = dict(conn.execute("SELECT documento, id_cliente FROM clientes"))

    total_dias = 30 * MESES_HISTORIAL
    inicio = hoy - timedelta(days=total_dias)
    n_solicitudes = n_aprobadas = n_cuotas = 0

    for r in df.itertuples(index=False):
        f_solicitud = inicio + timedelta(days=int(rng.integers(0, total_dias - 5)))
        f_decision = min(f_solicitud + timedelta(days=1 + int(rng.poisson(1.3))), hoy)
        aprobado = r.loan_status == "Approved"
        plazo = int(r.loan_term) * (1 if LOAN_TERM_EN_MESES else 12)
        estado = estados[("Desembolsada" if aprobado else "Rechazada", "solicitud")]

        cur = conn.execute(
            "INSERT INTO solicitudes (id_cliente, monto, plazo_meses, fecha_solicitud, "
            "fecha_decision, id_estado) VALUES (?, ?, ?, ?, ?, ?)",
            (
                ids_cliente[f"DOC{int(r.loan_id):06d}"],
                float(r.loan_amount),
                plazo,
                f_solicitud.isoformat(),
                f_decision.isoformat(),
                estado,
            ),
        )
        n_solicitudes += 1

        if aprobado:
            n_aprobadas += 1
            filas = simular_cuotas(
                rng, cur.lastrowid, float(r.loan_amount), plazo,
                f_decision, int(r.cibil_score), hoy, estados,
            )
            conn.executemany(
                "INSERT INTO cuotas (id_solicitud, numero_cuota, fecha_vencimiento, "
                "valor_cuota, valor_pagado, fecha_pago, id_estado) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                filas,
            )
            n_cuotas += len(filas)

    return {
        "clientes": len(df),
        "solicitudes": n_solicitudes,
        "desembolsadas": n_aprobadas,
        "rechazadas": n_solicitudes - n_aprobadas,
        "cuotas": n_cuotas,
    }


def resumen_kpis(conn: sqlite3.Connection, hoy: date) -> dict:
    """Calcula los 3 KPIs de la Semana 1 con SQL directo (vista previa de la Semana 3)."""
    desembolsadas = (
        "(SELECT COUNT(*) FROM solicitudes s JOIN estados e ON e.id_estado = s.id_estado "
        "WHERE e.nombre = 'Desembolsada' AND e.tipo = 'solicitud')"
    )
    monto_desembolsado = (
        "(SELECT SUM(s.monto) FROM solicitudes s JOIN estados e ON e.id_estado = s.id_estado "
        "WHERE e.nombre = 'Desembolsada' AND e.tipo = 'solicitud')"
    )
    hoy_s = hoy.isoformat()
    q = lambda sql, *p: conn.execute(sql, p).fetchone()[0]

    return {
        "morosos_pct": q(
            f"SELECT ROUND(100.0 * COUNT(DISTINCT id_solicitud) / {desembolsadas}, 2) "
            "FROM cuotas WHERE valor_pagado < valor_cuota "
            "AND fecha_vencimiento < date(?, '-30 days')", hoy_s,
        ),
        "dias_aprobacion": q(
            "SELECT ROUND(AVG(julianday(fecha_decision) - julianday(fecha_solicitud)), 2) "
            "FROM solicitudes WHERE fecha_decision IS NOT NULL"
        ),
        "recuperado_vs_otorgado_pct": q(
            f"SELECT ROUND(100.0 * (SELECT SUM(valor_pagado) FROM cuotas) / {monto_desembolsado}, 2)"
        ),
        "recuperado_vs_exigible_pct": q(
            "SELECT ROUND(100.0 * SUM(valor_pagado) / SUM(valor_cuota), 2) "
            "FROM cuotas WHERE fecha_vencimiento <= ?", hoy_s,
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Carga el CSV y simula fechas y cuotas")
    parser.add_argument("--csv", type=Path, default=CSV_PATH, help="ruta del CSV de Kaggle")
    parser.add_argument("--n", type=int, default=N_REGISTROS, help="registros a cargar")
    parser.add_argument("--seed", type=int, default=SEMILLA, help="semilla de la simulación")
    parser.add_argument("--reset", action="store_true", help="borra la base y recarga")
    args = parser.parse_args()

    if not args.csv.exists():
        raise SystemExit(
            f"No encuentro el CSV en {args.csv}.\n"
            "Descárgalo de Kaggle y déjalo en data/raw/ (loan_approval_dataset.csv)."
        )

    init_db(reset=args.reset)
    hoy = date.today()
    rng = np.random.default_rng(args.seed)

    with sqlite3.connect(DB_PATH) as conn:
        if conn.execute("SELECT COUNT(*) FROM solicitudes").fetchone()[0]:
            raise SystemExit(
                "La base ya tiene datos. Usa --reset para borrarla y volver a cargar."
            )
        df = leer_csv(args.csv, args.n, args.seed)
        conteo = cargar(conn, df, hoy, rng)
        kpis = resumen_kpis(conn, hoy)

    print(f"Base de datos poblada en {DB_PATH}")
    for nombre, valor in conteo.items():
        print(f"  {nombre:<14} {valor:>6}")
    print("\nKPIs de control (calculados con SQL, fecha de corte "
          f"{hoy.isoformat()}):")
    print(f"  % créditos morosos (>30 días):          {kpis['morosos_pct']} %   (meta ≤ 8 %)")
    print(f"  Tiempo promedio de aprobación:          {kpis['dias_aprobacion']} días (meta ≤ 2)")
    print(f"  Recuperado vs. otorgado (todo el monto): {kpis['recuperado_vs_otorgado_pct']} %   (meta ≥ 85 %)")
    print(f"  Recuperado vs. exigible a la fecha:      {kpis['recuperado_vs_exigible_pct']} %")


if __name__ == "__main__":
    main()