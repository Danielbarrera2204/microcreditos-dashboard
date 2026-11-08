"""Módulo operativo de microcréditos (Streamlit + SQLite).

Registra clientes, solicitudes, decisiones, desembolsos y pagos de cuotas sobre la
base db/microcreditos.db. El dashboard se agrega en la Semana 3.

Ejecutar:
    streamlit run app.py
"""
import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

DB_PATH = Path(__file__).resolve().parent / "db" / "microcreditos.db"
DIAS_ENTRE_CUOTAS = 30  # igual que en db/load_csv.py

st.set_page_config(page_title="Microcréditos · Módulo operativo", page_icon="💳", layout="wide")


# ---------------------------------------------------------------- acceso a datos
@contextmanager
def conexion():
    """Abre una conexión, confirma los cambios al salir y la cierra siempre."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def consulta(sql: str, params: tuple = ()) -> pd.DataFrame:
    with conexion() as conn:
        return pd.read_sql_query(sql, conn, params=params)


def id_estado(conn: sqlite3.Connection, nombre: str, tipo: str) -> int:
    return conn.execute(
        "SELECT id_estado FROM estados WHERE nombre = ? AND tipo = ?", (nombre, tipo)
    ).fetchone()[0]


def marcar_cuotas_vencidas() -> None:
    """Pasa a 'Vencida' las cuotas pendientes cuya fecha de vencimiento ya pasó."""
    with conexion() as conn:
        conn.execute(
            "UPDATE cuotas SET id_estado = ? "
            "WHERE id_estado = ? AND valor_pagado < valor_cuota AND fecha_vencimiento < ?",
            (
                id_estado(conn, "Vencida", "cuota"),
                id_estado(conn, "Pendiente", "cuota"),
                date.today().isoformat(),
            ),
        )


def generar_cuotas(conn, id_solicitud, monto, plazo, f_desembolso) -> int:
    """Crea las cuotas de un crédito: valor fijo sin interés, una cada 30 días."""
    base = round(monto / plazo, 2)
    pendiente = id_estado(conn, "Pendiente", "cuota")
    vencida = id_estado(conn, "Vencida", "cuota")
    hoy = date.today()
    filas = []
    for k in range(1, plazo + 1):
        valor = base if k < plazo else round(monto - base * (plazo - 1), 2)
        vence = f_desembolso + timedelta(days=DIAS_ENTRE_CUOTAS * k)
        filas.append((
            id_solicitud, k, vence.isoformat(), valor, 0.0, None,
            vencida if vence < hoy else pendiente,
        ))
    conn.executemany(
        "INSERT INTO cuotas (id_solicitud, numero_cuota, fecha_vencimiento, valor_cuota, "
        "valor_pagado, fecha_pago, id_estado) VALUES (?, ?, ?, ?, ?, ?, ?)",
        filas,
    )
    return len(filas)


# ---------------------------------------------------------------------- avisos
def avisar(texto: str, tipo: str = "success") -> None:
    """Guarda un mensaje y recarga la página para que las listas se actualicen."""
    st.session_state["aviso"] = (tipo, texto)
    st.rerun()


def mostrar_aviso() -> None:
    aviso = st.session_state.pop("aviso", None)
    if aviso:
        getattr(st, aviso[0])(aviso[1])


# --------------------------------------------------------------------- pestañas
def pestana_cliente() -> None:
    st.subheader("Registrar cliente")
    with st.form("form_cliente", clear_on_submit=True):
        documento = st.text_input("Documento de identidad", key="cli_documento")
        col1, col2 = st.columns(2)
        ingresos = col1.number_input(
            "Ingresos anuales", min_value=0.0, step=100000.0, key="cli_ingresos"
        )
        puntaje = col2.number_input(
            "Puntaje crediticio (300 a 900)", min_value=300, max_value=900,
            value=600, step=1, key="cli_puntaje",
        )
        dependientes = col1.number_input(
            "Número de dependientes", min_value=0, max_value=20, value=0, step=1,
            key="cli_dependientes",
        )
        activos = col2.number_input(
            "Valor total de activos", min_value=0.0, step=100000.0, key="cli_activos"
        )
        enviar = st.form_submit_button("Guardar cliente")

    if enviar:
        documento = documento.strip()
        if not documento:
            st.error("El documento es obligatorio.")
            return
        try:
            with conexion() as conn:
                conn.execute(
                    "INSERT INTO clientes (documento, ingresos_anuales, puntaje_crediticio, "
                    "num_dependientes, valor_activos) VALUES (?, ?, ?, ?, ?)",
                    (documento, ingresos, int(puntaje), int(dependientes), activos),
                )
        except sqlite3.IntegrityError:
            st.error("Ya existe un cliente con ese documento.")
            return
        avisar(f"Cliente {documento} registrado.")


def pestana_solicitud() -> None:
    st.subheader("Nueva solicitud de crédito")
    clientes = consulta(
        "SELECT id_cliente, documento, puntaje_crediticio FROM clientes ORDER BY id_cliente DESC"
    )
    if clientes.empty:
        st.info("Primero registra un cliente.")
        return
    datos = clientes.set_index("id_cliente")

    with st.form("form_solicitud", clear_on_submit=True):
        id_cliente = st.selectbox(
            "Cliente (escribe para buscar)",
            clientes["id_cliente"].tolist(),
            format_func=lambda i: f"{datos.loc[i, 'documento']} · puntaje {datos.loc[i, 'puntaje_crediticio']}",
            key="sol_cliente",
        )
        col1, col2, col3 = st.columns(3)
        monto = col1.number_input("Monto solicitado", min_value=1.0, step=100000.0, key="sol_monto")
        plazo = col2.number_input("Plazo (meses)", min_value=1, max_value=60, value=12, step=1, key="sol_plazo")
        fecha = col3.date_input("Fecha de solicitud", value=date.today(), max_value=date.today(), key="sol_fecha")
        enviar = st.form_submit_button("Registrar solicitud")

    if enviar:
        if monto < plazo:
            st.error("El monto debe ser al menos de 1 por cada mes de plazo.")
            return
        with conexion() as conn:
            cur = conn.execute(
                "INSERT INTO solicitudes (id_cliente, monto, plazo_meses, fecha_solicitud, "
                "fecha_decision, id_estado) VALUES (?, ?, ?, ?, NULL, ?)",
                (int(id_cliente), monto, int(plazo), fecha.isoformat(),
                 id_estado(conn, "Pendiente", "solicitud")),
            )
            nueva = cur.lastrowid
        avisar(f"Solicitud #{nueva} registrada en estado Pendiente.")


def pestana_decision() -> None:
    st.subheader("1. Decidir solicitudes pendientes")
    pendientes = consulta(
        "SELECT s.id_solicitud, c.documento, c.puntaje_crediticio, s.monto, s.plazo_meses, "
        "s.fecha_solicitud FROM solicitudes s "
        "JOIN clientes c ON c.id_cliente = s.id_cliente "
        "JOIN estados e ON e.id_estado = s.id_estado "
        "WHERE e.nombre = 'Pendiente' AND e.tipo = 'solicitud' ORDER BY s.id_solicitud DESC"
    )
    if pendientes.empty:
        st.info("No hay solicitudes pendientes.")
    else:
        st.dataframe(pendientes, hide_index=True)
        datos = pendientes.set_index("id_solicitud")
        with st.form("form_decision"):
            id_sol = st.selectbox(
                "Solicitud", pendientes["id_solicitud"].tolist(),
                format_func=lambda i: f"#{i} · {datos.loc[i, 'documento']} · {datos.loc[i, 'monto']:,.0f}",
                key="dec_solicitud",
            )
            decision = st.radio("Decisión", ["Aprobar", "Rechazar"], horizontal=True, key="dec_decision")
            fecha = st.date_input("Fecha de decisión", value=date.today(), max_value=date.today(), key="dec_fecha")
            enviar = st.form_submit_button("Guardar decisión")
        if enviar:
            if fecha < date.fromisoformat(datos.loc[id_sol, "fecha_solicitud"]):
                st.error("La decisión no puede ser anterior a la fecha de solicitud.")
            else:
                nombre = "Aprobada" if decision == "Aprobar" else "Rechazada"
                with conexion() as conn:
                    conn.execute(
                        "UPDATE solicitudes SET id_estado = ?, fecha_decision = ? WHERE id_solicitud = ?",
                        (id_estado(conn, nombre, "solicitud"), fecha.isoformat(), int(id_sol)),
                    )
                avisar(f"Solicitud #{id_sol}: {nombre.lower()}.")

    st.divider()
    st.subheader("2. Desembolsar solicitudes aprobadas")
    aprobadas = consulta(
        "SELECT s.id_solicitud, c.documento, s.monto, s.plazo_meses, s.fecha_decision "
        "FROM solicitudes s JOIN clientes c ON c.id_cliente = s.id_cliente "
        "JOIN estados e ON e.id_estado = s.id_estado "
        "WHERE e.nombre = 'Aprobada' AND e.tipo = 'solicitud' ORDER BY s.id_solicitud DESC"
    )
    if aprobadas.empty:
        st.info("No hay solicitudes aprobadas por desembolsar.")
        return
    st.dataframe(aprobadas, hide_index=True)
    datos = aprobadas.set_index("id_solicitud")
    with st.form("form_desembolso"):
        id_sol = st.selectbox(
            "Solicitud aprobada", aprobadas["id_solicitud"].tolist(),
            format_func=lambda i: f"#{i} · {datos.loc[i, 'documento']} · {datos.loc[i, 'monto']:,.0f}",
            key="des_solicitud",
        )
        fecha = st.date_input("Fecha de desembolso", value=date.today(), max_value=date.today(), key="des_fecha")
        enviar = st.form_submit_button("Desembolsar y generar cuotas")
    if enviar:
        if fecha < date.fromisoformat(datos.loc[id_sol, "fecha_decision"]):
            st.error("El desembolso no puede ser anterior a la fecha de decisión.")
            return
        with conexion() as conn:
            conn.execute(
                "UPDATE solicitudes SET id_estado = ? WHERE id_solicitud = ?",
                (id_estado(conn, "Desembolsada", "solicitud"), int(id_sol)),
            )
            n = generar_cuotas(
                conn, int(id_sol), float(datos.loc[id_sol, "monto"]),
                int(datos.loc[id_sol, "plazo_meses"]), fecha,
            )
        avisar(f"Solicitud #{id_sol} desembolsada: se generaron {n} cuotas.")


def pestana_pago() -> None:
    st.subheader("Registrar pago de cuota")
    creditos = consulta(
        "SELECT s.id_solicitud, c.documento, s.monto, COUNT(*) AS cuotas_sin_pagar "
        "FROM cuotas q JOIN solicitudes s ON s.id_solicitud = q.id_solicitud "
        "JOIN clientes c ON c.id_cliente = s.id_cliente "
        "WHERE q.valor_pagado < q.valor_cuota "
        "GROUP BY s.id_solicitud ORDER BY s.id_solicitud DESC"
    )
    if creditos.empty:
        st.info("No hay créditos con cuotas por pagar.")
        return
    datos = creditos.set_index("id_solicitud")
    id_sol = st.selectbox(
        "Crédito (escribe para buscar)", creditos["id_solicitud"].tolist(),
        format_func=lambda i: (
            f"#{i} · {datos.loc[i, 'documento']} · {datos.loc[i, 'monto']:,.0f} "
            f"· {datos.loc[i, 'cuotas_sin_pagar']} cuotas sin pagar"
        ),
        key="pag_credito",
    )
    cuotas = consulta(
        "SELECT q.id_cuota, q.numero_cuota, q.fecha_vencimiento, q.valor_cuota, e.nombre AS estado "
        "FROM cuotas q JOIN estados e ON e.id_estado = q.id_estado "
        "WHERE q.id_solicitud = ? AND q.valor_pagado < q.valor_cuota ORDER BY q.numero_cuota",
        (int(id_sol),),
    )
    st.dataframe(cuotas, hide_index=True)
    datos_cuota = cuotas.set_index("id_cuota")

    with st.form("form_pago", clear_on_submit=True):
        id_cuota = st.selectbox(
            "Cuota a pagar", cuotas["id_cuota"].tolist(),
            format_func=lambda i: (
                f"Cuota {datos_cuota.loc[i, 'numero_cuota']} · vence "
                f"{datos_cuota.loc[i, 'fecha_vencimiento']} · {datos_cuota.loc[i, 'valor_cuota']:,.2f}"
            ),
            key="pag_cuota",
        )
        fecha = st.date_input("Fecha de pago", value=date.today(), max_value=date.today(), key="pag_fecha")
        enviar = st.form_submit_button("Registrar pago")

    if enviar:
        with conexion() as conn:
            conn.execute(
                "UPDATE cuotas SET valor_pagado = valor_cuota, fecha_pago = ?, id_estado = ? "
                "WHERE id_cuota = ?",
                (fecha.isoformat(), id_estado(conn, "Pagada", "cuota"), int(id_cuota)),
            )
        avisar(f"Pago registrado: cuota {datos_cuota.loc[id_cuota, 'numero_cuota']} del crédito #{id_sol}.")


def pestana_registros() -> None:
    st.subheader("Verificación de registros")
    totales = consulta(
        "SELECT (SELECT COUNT(*) FROM clientes) AS clientes, "
        "(SELECT COUNT(*) FROM solicitudes) AS solicitudes, "
        "(SELECT COUNT(*) FROM cuotas) AS cuotas, "
        "(SELECT COUNT(*) FROM cuotas WHERE valor_pagado >= valor_cuota) AS cuotas_pagadas"
    ).iloc[0]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Clientes", f"{totales['clientes']:,}")
    c2.metric("Solicitudes", f"{totales['solicitudes']:,}")
    c3.metric("Cuotas", f"{totales['cuotas']:,}")
    c4.metric("Cuotas pagadas", f"{totales['cuotas_pagadas']:,}")

    st.caption("Los registros nuevos aparecen primero: se guardan en la misma base que los datos del CSV.")
    st.markdown("**Últimas solicitudes**")
    st.dataframe(
        consulta(
            "SELECT s.id_solicitud, c.documento, s.monto, s.plazo_meses, s.fecha_solicitud, "
            "s.fecha_decision, e.nombre AS estado FROM solicitudes s "
            "JOIN clientes c ON c.id_cliente = s.id_cliente "
            "JOIN estados e ON e.id_estado = s.id_estado ORDER BY s.id_solicitud DESC LIMIT 10"
        ),
        hide_index=True,
    )
    st.markdown("**Últimos pagos registrados**")
    st.dataframe(
        consulta(
            "SELECT q.id_cuota, q.id_solicitud, q.numero_cuota, q.valor_pagado, q.fecha_pago "
            "FROM cuotas q WHERE q.fecha_pago IS NOT NULL "
            "ORDER BY q.fecha_pago DESC, q.id_cuota DESC LIMIT 10"
        ),
        hide_index=True,
    )


# ------------------------------------------------------------------- aplicación
def main() -> None:
    st.title("💳 Microcréditos · Módulo operativo")
    if not DB_PATH.exists():
        st.error(
            "No encuentro la base de datos. Ejecuta primero `python db/init_db.py` "
            "y luego `python db/load_csv.py`."
        )
        st.stop()

    marcar_cuotas_vencidas()
    mostrar_aviso()

    tabs = st.tabs([
        "Clientes", "Solicitudes", "Decisión y desembolso", "Pagos de cuotas", "Verificación",
    ])
    with tabs[0]:
        pestana_cliente()
    with tabs[1]:
        pestana_solicitud()
    with tabs[2]:
        pestana_decision()
    with tabs[3]:
        pestana_pago()
    with tabs[4]:
        pestana_registros()


main()