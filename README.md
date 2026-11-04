# Microcréditos: módulo operativo y dashboard

Proyecto final de Gerencia Estratégica de TI. Prototipo que registra solicitudes
de microcrédito y cuotas de pago, y las convierte en KPIs para la toma de decisiones.

**Caso de estudio:** Control de Solicitudes y Cobranza de Microcréditos.
**Tecnología:** Python, Streamlit, SQLite.

## KPIs

| KPI | Fórmula | Meta |
| --- | --- | --- |
| % de créditos morosos | (Créditos con alguna cuota vencida más de 30 días ÷ Créditos desembolsados) × 100 | ≤ 8 % |
| Tiempo promedio de aprobación (días) | Promedio de (fecha de decisión − fecha de solicitud) | ≤ 2 días |
| Monto recuperado vs. otorgado (%) | (Suma de pagos recibidos ÷ Suma de montos desembolsados) × 100 | ≥ 85 % |

## Modelo de datos

Cuatro tablas: `clientes` y `estados` (maestras), `solicitudes` y `cuotas` (transaccionales).
Una solicitud pertenece a un cliente y genera varias cuotas; ambas tienen un estado.
El esquema completo está en `db/schema.sql`.

## Instalación

```bash
python -m venv .venv
source .venv/bin/activate        # En Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Crear la base de datos

```bash
python db/init_db.py             # crea db/microcreditos.db
python db/init_db.py --reset     # la borra y la crea de nuevo
```

## Estructura

```text
├── README.md
├── requirements.txt
├── db/
│   ├── schema.sql      # tablas del DER
│   └── init_db.py      # genera microcreditos.db
└── data/
    └── raw/            # CSV de Kaggle (no se sube a Git)
```

## Estado del proyecto

- [x] Semana 1: KPIs, DER y esquema de base de datos
- [ ] Semana 2: módulo operativo en Streamlit y carga del CSV
- [ ] Semana 3: dashboard y consultas de resumen
- [ ] Semana 4: costos, prueba E2E, documentación y sustentación
