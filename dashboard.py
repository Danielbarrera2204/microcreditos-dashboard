"""Dashboard gerencial de microcréditos (Semana 3).

Tres zonas, como pide la guía:
  - Superior: tarjetas con los KPIs y métricas globales.
  - Media: gráficos de tendencias.
  - Inferior: tabla detallada de solicitudes.

Se abre desde app.py (menú lateral). Los cálculos viven en kpis.py.
"""
from datetime import date

import plotly.express as px
import streamlit as st

import kpis as K

# "exigible": pagos recibidos ÷ cuotas ya vencidas (mide la salud de la cartera).
# "otorgado": pagos recibidos ÷ monto total desembolsado (fórmula original de la Semana 1;
#             queda baja mientras la cartera es joven porque incluye cuotas que aún no vencen).
FORMULA_RECUPERACION = "exigible"

COLORES_RESULTADO = {"Aprobada": "#2a9d8f", "Rechazada": "#e76f51", "Pendiente": "#e9c46a"}

st.title("📊 Dashboard gerencial · Microcréditos")

if not K.DB_PATH.exists():
    st.error("No encuentro la base de datos. Ejecuta `python db/init_db.py` y `python db/load_csv.py`.")
    st.stop()

conn = K.conectar()
d_min, d_max = K.rango_fechas(conn)

# ------------------------------------------------------------------- filtros
col_fechas, col_nota = st.columns([2, 3])
rango = col_fechas.date_input(
    "Periodo (por fecha de solicitud)", value=(d_min, d_max),
    min_value=d_min, max_value=max(d_max, date.today()), key="dash_rango",
)
col_nota.caption(
    "El periodo filtra las tarjetas, los gráficos y la tabla. "
    "Montos en las unidades monetarias del dataset de Kaggle."
)
if len(rango) != 2:
    st.info("Elige la fecha final del periodo.")
    st.stop()

p = K.parametros(rango[0], rango[1])
k = K.calcular_kpis(conn, p)
if k["solicitudes"] == 0:
    st.warning("No hay solicitudes en ese periodo.")
    st.stop()


def num(valor, decimales=1, sufijo=""):
    return "—" if valor is None else f"{valor:,.{decimales}f}{sufijo}"


def diferencia(valor, meta, unidad):
    return None if valor is None else f"{valor - meta:+.2f} {unidad} vs meta"


# ------------------------------------------------------------- zona superior
st.subheader("Indicadores clave")
t1, t2, t3 = st.columns(3)

t1.metric(
    "% de créditos morosos",
    num(k["morosos_pct"], 2, " %"),
    delta=diferencia(k["morosos_pct"], K.METAS["morosos_pct"], "pp"),
    delta_color="inverse",
    help="Créditos desembolsados con al menos una cuota sin pagar y más de 30 días vencida, "
         "sobre el total de créditos desembolsados.",
)
t1.caption(f"Meta: ≤ {K.METAS['morosos_pct']:.0f} % · {k['morosos']} de {k['desembolsadas']} créditos")

t2.metric(
    "Tiempo promedio de aprobación",
    num(k["dias_aprobacion"], 2, " días"),
    delta=diferencia(k["dias_aprobacion"], K.METAS["dias_aprobacion"], "días"),
    delta_color="inverse",
    help="Días promedio entre la fecha de solicitud y la fecha de decisión (aprobada o rechazada).",
)
t2.caption(f"Meta: ≤ {K.METAS['dias_aprobacion']:.0f} días")

if FORMULA_RECUPERACION == "exigible":
    valor_rec, titulo_rec = k["recuperacion_exigible_pct"], "Recuperación de cartera exigible"
    ayuda_rec = "Pagos recibidos sobre el valor de las cuotas que ya vencieron."
    nota_rec = f"Meta: ≥ {K.METAS['recuperacion_pct']:.0f} % · vs. total otorgado: {num(k['recuperacion_otorgado_pct'], 1, ' %')}"
else:
    valor_rec, titulo_rec = k["recuperacion_otorgado_pct"], "Monto recuperado vs. otorgado"
    ayuda_rec = "Pagos recibidos sobre el monto total desembolsado."
    nota_rec = f"Meta: ≥ {K.METAS['recuperacion_pct']:.0f} %"
t3.metric(
    titulo_rec, num(valor_rec, 1, " %"),
    delta=diferencia(valor_rec, K.METAS["recuperacion_pct"], "pp"), help=ayuda_rec,
)
t3.caption(nota_rec)

g1, g2, g3, g4 = st.columns(4)
g1.metric("Solicitudes del periodo", f"{k['solicitudes']:,}")
g2.metric("Tasa de aprobación", num(k["tasa_aprobacion_pct"], 1, " %"))
g3.metric("Monto otorgado", num(k["monto_otorgado"], 0))
g4.metric("Monto recuperado", num(k["monto_recuperado"], 0))

# --------------------------------------------------------------- zona media
st.divider()
st.subheader("Tendencias")
c1, c2 = st.columns(2)

por_mes = K.solicitudes_por_mes(conn, p)
fig1 = px.bar(
    por_mes, x="mes", y="solicitudes", color="resultado", barmode="stack",
    color_discrete_map=COLORES_RESULTADO,
    title="Solicitudes por mes y resultado",
    labels={"mes": "Mes", "solicitudes": "Solicitudes", "resultado": "Resultado"},
)
c1.plotly_chart(fig1)

flujo = K.flujo_mensual(conn, p)
flujo_largo = flujo.melt(id_vars="mes", var_name="concepto", value_name="monto")
flujo_largo["concepto"] = flujo_largo["concepto"].map({"desembolsado": "Desembolsado", "recaudado": "Recaudado"})
fig2 = px.line(
    flujo_largo, x="mes", y="monto", color="concepto", markers=True,
    title="Monto desembolsado vs. recaudado por mes",
    labels={"mes": "Mes", "monto": "Monto", "concepto": ""},
)
c2.plotly_chart(fig2)

c3, c4 = st.columns(2)
por_puntaje = K.morosidad_por_puntaje(conn, p)
fig3 = px.bar(
    por_puntaje, x="rango", y="pct_morosos", text_auto=".1f",
    title="Morosidad por rango de puntaje crediticio",
    labels={"rango": "Puntaje crediticio", "pct_morosos": "% de créditos morosos"},
)
fig3.add_hline(y=K.METAS["morosos_pct"], line_dash="dash", annotation_text=f"Meta {K.METAS['morosos_pct']:.0f} %")
c3.plotly_chart(fig3)

# Lectura gerencial: texto generado a partir de los datos del periodo
with c4:
    st.markdown("**Lectura gerencial**")
    lineas = []
    if k["morosos_pct"] is not None:
        cumple = k["morosos_pct"] <= K.METAS["morosos_pct"]
        lineas.append(
            f"La morosidad es de {k['morosos_pct']:.2f} %, "
            f"{'dentro' if cumple else 'por encima'} de la meta de {K.METAS['morosos_pct']:.0f} %."
        )
    if k["dias_aprobacion"] is not None:
        cumple = k["dias_aprobacion"] <= K.METAS["dias_aprobacion"]
        lineas.append(
            f"Aprobar una solicitud toma {k['dias_aprobacion']:.2f} días en promedio: "
            f"{'se cumple' if cumple else 'no se cumple'} la meta de {K.METAS['dias_aprobacion']:.0f} días."
        )
    if not por_puntaje.empty and por_puntaje["pct_morosos"].max() > 0:
        peor = por_puntaje.loc[por_puntaje["pct_morosos"].idxmax()]
        lineas.append(
            f"El segmento de mayor riesgo es el de puntaje {peor['rango']}, con "
            f"{peor['pct_morosos']:.1f} % de morosidad: ahí conviene reforzar el análisis de crédito."
        )
    for linea in lineas:
        st.markdown(f"- {linea}")

# --------------------------------------------------------------- zona inferior
st.divider()
st.subheader("Detalle de solicitudes")
detalle = K.detalle_solicitudes(conn, p)
conn.close()

f1, f2 = st.columns([3, 2])
estados = f1.multiselect(
    "Estado", sorted(detalle["Estado"].unique()), default=sorted(detalle["Estado"].unique()),
    key="dash_estados",
)
buscar = f2.text_input("Buscar documento", key="dash_buscar")

filtrado = detalle[detalle["Estado"].isin(estados)]
if buscar.strip():
    filtrado = filtrado[filtrado["Documento"].str.contains(buscar.strip(), case=False, regex=False)]

st.caption(f"Mostrando {len(filtrado):,} de {len(detalle):,} solicitudes (el filtro de estado solo afecta a esta tabla).")
st.dataframe(filtrado, hide_index=True)
st.download_button(
    "Descargar tabla en CSV", filtrado.to_csv(index=False).encode("utf-8"),
    file_name="solicitudes.csv", mime="text/csv",
)