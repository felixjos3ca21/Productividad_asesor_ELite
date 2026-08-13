import sqlite3
from pathlib import Path
import pandas as pd
import streamlit as st
import plotly.express as px
from scripts.actualizar_archivo import render_actualizar_pagos_sidebar


_REPO_ROOT = Path(__file__).resolve().parent.parent
_DB_PATH = str(_REPO_ROOT / "gestiones.db")

render_actualizar_pagos_sidebar(_DB_PATH)

_ICON = Path(__file__).parent / "scripts" / "image" / "icono.ico"
st.set_page_config(page_title="Elite Abogados BPO - Pagos x Asesor", layout="wide", page_icon=str(_ICON))

st.title("Pagos x Asesor")


def _firma_db(db_path: str) -> tuple:
    path = Path(db_path)
    if not path.exists():
        return tuple()
    stat = path.stat()
    return (str(path.resolve()), stat.st_mtime_ns, stat.st_size)


@st.cache_data(show_spinner="Cargando pagos desde base de datos...", ttl=None)
def cargar_pagos_desde_sqlite(db_path: str, firma_db: tuple) -> pd.DataFrame:
    if not Path(db_path).exists():
        return pd.DataFrame()
    try:
        con = sqlite3.connect(db_path)
        df = pd.read_sql_query(
            "SELECT * FROM pagos_x_asesor",
            con,
            parse_dates=["fecha_pago", "fecha_asignacion", "fechagestion"],
        )
        con.close()
        return df
    except Exception as e:
        st.error(f"Error leyendo pagos_x_asesor: {e}")
        return pd.DataFrame()


df_pagos = cargar_pagos_desde_sqlite(_DB_PATH, _firma_db(_DB_PATH))

if df_pagos.empty:
    st.info("Aun no hay datos en pagos_x_asesor. Usa el panel lateral para cargar archivos.")
    st.stop()

#  Prewiew de los datos  --- 
#st.dataframe(df_pagos, use_container_width=True)

# ── Verificación y conversión de tipos ────────────────────────────────
df_pagos["valor_pago"] = pd.to_numeric(df_pagos["valor_pago"], errors="coerce")
filas_sin_valor = df_pagos["valor_pago"].isna().sum()
if filas_sin_valor:
    st.warning(f"{filas_sin_valor} filas tienen valor_pago no numerico y se excluyen de los totales.")

# ── Filtros (pantalla principal) ────────────────────────────────────────
st.markdown("### Filtros")
col_f1, col_f2, col_f3, col_f4, col_f5 = st.columns(5)

fecha_min = df_pagos["fecha_pago"].min()
fecha_max = df_pagos["fecha_pago"].max()
with col_f1:
    rango_fecha = st.date_input(
        "Fecha de pago",
        value=(fecha_min, fecha_max) if pd.notna(fecha_min) else None,
        key="filtro_fecha_pago",
    )

campos_disponibles = sorted(df_pagos["Campo"].dropna().unique().tolist())
with col_f2:
    campos_sel = st.multiselect("Campo", campos_disponibles, default=campos_disponibles, key="filtro_campo")

marcas_disponibles = sorted(df_pagos["marca"].dropna().unique().tolist())
with col_f3:
    marcas_sel = st.multiselect("Marca", marcas_disponibles, default=marcas_disponibles, key="filtro_marca")

asesores_disponibles = sorted(df_pagos["Nombre_Asesor"].dropna().unique().tolist())
with col_f4:
    asesores_sel = st.multiselect("Asesor", asesores_disponibles, default=asesores_disponibles, key="filtro_asesor")

tipificaciones_disponibles = sorted(df_pagos["mejorperfil"].dropna().unique().tolist())
with col_f5:
    tipificaciones_sel = st.multiselect(
        "Tipificación", tipificaciones_disponibles, default=tipificaciones_disponibles, key="filtro_tipificacion"
    )

base = df_pagos.copy()
if isinstance(rango_fecha, tuple) and len(rango_fecha) == 2:
    f_desde, f_hasta = pd.to_datetime(rango_fecha[0]), pd.to_datetime(rango_fecha[1])
    base = base[(base["fecha_pago"] >= f_desde) & (base["fecha_pago"] <= f_hasta)]
if campos_sel:
    base = base[base["Campo"].isin(campos_sel)]

if marcas_sel:
    base = base[base["marca"].isin(marcas_sel)]

if asesores_sel:
    base = base[base["Nombre_Asesor"].isin(asesores_sel)]

if tipificaciones_sel:
    base = base[base["mejorperfil"].isin(tipificaciones_sel)]

if base.empty:
    st.info("No hay datos para los filtros seleccionados.")
    st.stop()

st.divider()

# ── KPIs ───────────────────────────────────────────────────────────────
total_pagado = base["valor_pago"].sum()
cantidad_pagos = len(base)
asesores_activos = base["Nombre_Asesor"].nunique(dropna=True)
promedio_x_asesor = total_pagado / asesores_activos if asesores_activos else 0

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total pagado", f"${total_pagado:,.0f}".replace(",", "."))
col2.metric("Cantidad de pagos", f"{cantidad_pagos:,}".replace(",", "."))
col3.metric("Asesores con pago", asesores_activos)
col4.metric("Promedio x asesor", f"${promedio_x_asesor:,.0f}".replace(",", "."))

st.divider()

# ── Resumen por asesor ───────────────────────────────────────────────
resumen_asesor = (
    base.groupby("Nombre_Asesor", as_index=False)
    .agg(
        total_pagado=("valor_pago", "sum"),
        cantidad_pagos=("cuenta", "count"),
        Campo=("Campo", "first"),
    )
    .sort_values("total_pagado", ascending=False)
)

st.subheader("Resumen por asesor")
st.dataframe(
    resumen_asesor,
    use_container_width=True,
    hide_index=True,
    column_config={
        "total_pagado": st.column_config.NumberColumn("Total pagado", format="$ %d"),
        "cantidad_pagos": st.column_config.NumberColumn("Cantidad de pagos", format="%d"),
    },
)
st.divider()

## GRAFICO DE PAGOS POR DIA

st.subheader("Pagos por día")

base["dia_pago"] = base["fecha_pago"].dt.day
pagos_diarios = (
    base.groupby(["dia_pago", "Campo"], as_index=False)
    .agg(total_dia=("valor_pago", "sum"))
)

fig = px.line(
    pagos_diarios,   # ← cambia resumen_asesor por pagos_diarios aquí
    x="dia_pago",
    y="total_dia",
    color="Campo",
    markers=True,
    labels={"dia_pago": "Día", "total_dia": "Total pagado", "Campo": "Campo"},
)
fig.update_layout(hovermode="x unified")
st.plotly_chart(fig, use_container_width=True)

st.markdown("### Meta por asesor")
meta = st.number_input(
    "Meta de recaudo por asesor",
    min_value=0.0,
    value=0.0,
    step=10000.0,
    format="%.0f",
    key="input_meta_asesor",
)

resumen_asesor["meta"] = meta
resumen_asesor["valor_faltante"] = resumen_asesor["total_pagado"] - resumen_asesor["meta"]
resumen_asesor["%_meta"] = resumen_asesor.apply(
    lambda r: (r["total_pagado"] / r["meta"] * 100) if r["meta"] > 0 else 0.0,
    axis=1,
)

from st_aggrid import AgGrid, JsCode

resumen_asesor["estado"] = resumen_asesor["valor_faltante"].apply(lambda v: "✅ Cumplida" if v >= 0 else "⏳ En curso")

marcas_texto = ", ".join(marcas_sel) if marcas_sel else "Todas"
campos_texto = ", ".join(campos_sel) if campos_sel else "Todos"
st.subheader(f"Resumen por asesor — Marca: {marcas_texto} | Campo: {campos_texto}")

df_grid = resumen_asesor[
    ["Nombre_Asesor", "total_pagado", "meta", "valor_faltante", "%_meta", "estado"]
].copy()

money_formatter = JsCode("""
function(params) {
    if (params.value == null) return '';
    return '$ ' + Math.round(params.value).toLocaleString('es-CO');
}
""")

progress_renderer = JsCode("""
class ProgressBarRenderer {
    init(params) {
        this.eGui = document.createElement('div');
        const real = params.value == null ? 0 : params.value;
        const ancho = Math.min(Math.max(real, 0), 100);
        const color = real >= 100 ? '#2ecc71' : '#3498db';
        this.eGui.innerHTML = `
            <div style="background:#e2e8f0;border-radius:4px;height:18px;width:100%;position:relative;">
                <div style="background:${color};width:${ancho}%;height:100%;border-radius:4px;"></div>
                <span style="position:absolute;inset:0;text-align:center;font-size:11px;line-height:18px;">${real.toFixed(0)}%</span>
            </div>`;
    }
    getGui() { return this.eGui; }
}
""")

grid_options = {
    "defaultColDef": {
        "sortable": True,
        "filter": True,
        "resizable": True,
    },
    "columnDefs": [
        {"field": "Nombre_Asesor", "headerName": "Asesor", "pinned": "left"},
        {"field": "total_pagado", "headerName": "Total pagado", "valueFormatter": money_formatter, "type": ["numericColumn"]},
        {"field": "meta", "headerName": "Meta", "valueFormatter": money_formatter, "type": ["numericColumn"]},
        {"field": "valor_faltante", "headerName": "Falta / Excedente", "valueFormatter": money_formatter, "type": ["numericColumn"]},
        {"field": "%_meta", "headerName": "Avance", "cellRenderer": progress_renderer, "type": ["numericColumn"]},
        {"field": "estado", "headerName": "Estado"},
    ],
}
custom_css = {
    ".ag-header": {"background-color": "#1f3b57 !important"},
    ".ag-header-cell-label": {"color": "white !important", "font-weight": "600"},
    ".ag-row-even": {"background-color": "#ffffff !important"},
    ".ag-row-odd": {"background-color": "#f2f5f8 !important"},
}

altura_fila = 42
altura_header = 46
altura_calculada = altura_header + altura_fila * len(df_grid) + 10
altura_calculada = min(altura_calculada, 900)  # tope para que no se salga de pantalla con muchas filas

AgGrid(
    df_grid,
    gridOptions=grid_options,
    custom_css=custom_css,
    allow_unsafe_jscode=True,
    fit_columns_on_grid_load=True,
    theme="alpine",
    height=altura_calculada,   # ← número fijo, calculado según tus filas reales
    update_mode="NO_UPDATE",
)
st.caption(f"Filas en df_grid: {len(df_grid)}")

