import streamlit as st
import pandas as pd
from pathlib import Path
from st_aggrid import AgGrid, GridOptionsBuilder
from st_aggrid.shared import JsCode
from scripts.crear_db_dupree import crear_db, cargar_gestiones, DB_PATH
from scripts.funciones_apoyo import cargar_asesores, cruzar_con_asesores

import sqlite3

_ICON = Path(__file__).parent / "scripts" / "image" / "icono.ico"
st.set_page_config(page_title="Productividad - DUPREE", layout="wide", page_icon=str(_ICON))

crear_db()

st.title("Productividad DUPREE")

# --- Carga de archivo ---
archivo = st.file_uploader("Cargar reporte de gestión (CSV)", type="csv")
if archivo is not None:
    df_nuevo = pd.read_csv(archivo, sep=None, engine="python")
    n_nuevos = cargar_gestiones(df_nuevo)
    st.success(f"{n_nuevos} gestiones nuevas cargadas. Duplicados ignorados.")

# --- Leer todo lo que hay en la DB ---
conn = sqlite3.connect(DB_PATH)
df = pd.read_sql("SELECT * FROM gestiones", conn)
conn.close()

if df.empty:
    st.info("Aún no hay gestiones cargadas.")
    st.stop()

df["fechagestion"] = pd.to_datetime(df["fechagestion"])
df = cruzar_con_asesores(df, "asesores_dupree.json")

# --- Filtros ---
col1, col2, col3 = st.columns(3)

with col1:
    rango_fechas = st.date_input(
        "Fecha",
        value=(pd.Timestamp.today().date(), pd.Timestamp.today().date()),
    )
    if isinstance(rango_fechas, tuple):
        if len(rango_fechas) == 2:
            fecha_ini, fecha_fin = rango_fechas
        else:
            fecha_ini = fecha_fin = rango_fechas[0]
    else:
        fecha_ini = fecha_fin = rango_fechas
with col2:
    campos = ["Todos"] + sorted(df["Campo"].dropna().unique().tolist())
    campo_sel = st.selectbox("Campo", campos)

with col3:
    asesores_lista = ["Todos"] + sorted(df["Nombre_Asesor"].dropna().unique().tolist())
    asesor_sel = st.selectbox("Asesor", asesores_lista)

df_filtrado = df[
    (df["fechagestion"].dt.date >= fecha_ini) & (df["fechagestion"].dt.date <= fecha_fin)
]
if campo_sel != "Todos":
    df_filtrado = df_filtrado[df_filtrado["Campo"] == campo_sel]
if asesor_sel != "Todos":
    df_filtrado = df_filtrado[df_filtrado["Nombre_Asesor"] == asesor_sel]


sin_match = df_filtrado[df_filtrado["Nombre_Asesor"].isna()]["asesor_gestion"].unique()
if len(sin_match) > 0:
    st.warning(f"{len(sin_match)} asesores sin coincidencia en el JSON: {sorted(sin_match)}")


def mostrar_productividad(df_filtrado: pd.DataFrame):
    resumen = (
        df_filtrado
        .assign(es_promesa=df_filtrado["valorpromesa"].fillna(0) > 0)
        .groupby("Nombre_Asesor")
        .agg(
            Gestiones_Realizadas=("codllamada", "count"),
            Promesas=("es_promesa", "sum"),
            Monto_Promesas=("valorpromesa", "sum"),
        )
        .reset_index()
        .sort_values("Monto_Promesas", ascending=False)
    )

    promedio = resumen["Monto_Promesas"].mean()
    resumen.columns = [c.replace("_", " ") for c in resumen.columns]

    semaforo_style = JsCode(f"""
    function(params) {{
        var promedio = {promedio};
        var valor = params.value;
        var color = 'transparent';
        if (valor >= promedio) {{
            color = '#57bb8a';
        }} else if (valor >= promedio * 0.5) {{
            color = '#f7d060';
        }} else {{
            color = '#e8695f';
        }}
        return {{'backgroundColor': color}};
    }}
    """)
    
    grid_options_adh = {
        "defaultColDef": {"sortable": True, "filter": True, "resizable": True},
        "columnDefs": [
            {"field": "Nombre Asesor", "headerName": "Asesor", "pinned": "left", "minWidth": 200, "flex": 1},
            {"field": "Gestiones Realizadas", "headerName": "Gestiones Realizadas", "minWidth": 170, "flex": 1},
            {"field": "Promesas", "headerName": "Promesas", "minWidth": 130, "flex": 1},
            {
                "field": "Monto Promesas",
                "headerName": "Monto Promesas",
                "minWidth": 170,
                "flex": 1,
                "cellStyle": semaforo_style,
                "valueFormatter": "x.toLocaleString('es-CO')",
            },
        ],
    }

    altura = 40 + 35 * len(resumen) + 10  # cabecera + filas + margen

    AgGrid(
        resumen,
        gridOptions=grid_options_adh,
        theme="alpine",
        allow_unsafe_jscode=True,
        height=altura,
    )

mostrar_productividad(df_filtrado)