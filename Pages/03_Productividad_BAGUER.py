import streamlit as st
import pandas as pd
import hashlib
from pathlib import Path
from st_aggrid import AgGrid, GridOptionsBuilder, JsCode
from scripts.crear_db_baguer import inicializar_base_datos, guardar_df_en_bd, cargar_datos_productividad
from scripts.procesar_reporte_baguer import procesar_reporte_baguer
from st_aggrid import AgGrid, GridOptionsBuilder, JsCode
from scripts.procesar_reporte_baguer import procesar_reporte_baguer
from scripts.generar_imagen_baguer import generar_imagen_productividad
import io

_ICON = Path(__file__).parent / "scripts" / "image" / "icono.ico"
st.set_page_config(page_title="Productividad - BAGUER", layout="wide", page_icon=str(_ICON))

# Inicializar base de datos
inicializar_base_datos()

@st.cache_data
def obtener_productividad():
    return cargar_datos_productividad()

def generar_hash_id(df):
    llave_compuesta = (
        df["cuenta"].astype(str).fillna("") + "|" +
        df["horagestion"].astype(str).fillna("") + "|" +
        df["asesor"].astype(str).fillna("") + "|" +
        df["ultimo_perfil"].astype(str).fillna("")
    )
    df["id_registro"] = llave_compuesta.apply(
        lambda x: hashlib.md5(x.encode('utf-8')).hexdigest()
    )
    cols = ["id_registro"] + [c for c in df.columns if c != "id_registro"]
    return df[cols]

def calcular_resumen_productividad(df: pd.DataFrame, col_asesor: str) -> pd.DataFrame:
    base = df.copy()
    base["cuenta"] = base["cuenta"].astype("string").str.strip()
    base.loc[base["cuenta"].isin(["", "<NA>", "nan", "None"]), "cuenta"] = pd.NA

    resumen_cuentas = (
        base.groupby(col_asesor, dropna=False)["cuenta"]
        .nunique(dropna=True)
        .reset_index(name="Cuentas_Gestionadas")
    )

    perfiles_promesas = {"acuerdo de pago total", "acuerdo de pago abono"}
    perfil_norm = base["ultimo_perfil"].astype("string").str.strip().str.lower()
    mask_promesas = perfil_norm.isin(perfiles_promesas)

    resumen_promesas = (
        base.loc[mask_promesas]
        .groupby(col_asesor, dropna=False)["cuenta"]
        .nunique(dropna=True)
        .reset_index(name="Cantidad_Promesas")
    )

    tmp_valor = base[[col_asesor, "cuenta", "fechagestion", "valorpromesa"]].copy()
    tmp_valor["valorpromesa"] = pd.to_numeric(tmp_valor["valorpromesa"], errors="coerce")

    min_por_cuenta_dia = (
        tmp_valor.dropna(subset=["cuenta"])
        .groupby([col_asesor, "cuenta", "fechagestion"], dropna=False)["valorpromesa"]
        .min()
        .reset_index(name="min_valor")
    )

    resumen_valor = (
        min_por_cuenta_dia.groupby(col_asesor, dropna=False)["min_valor"]
        .sum(min_count=1)
        .reset_index(name="Valor_Promesas")
    )

    resumen = (
        resumen_cuentas
        .merge(resumen_promesas, on=col_asesor, how="left")
        .merge(resumen_valor, on=col_asesor, how="left")
        .fillna(0)
    )

    resumen["Cuentas_Gestionadas"] = resumen["Cuentas_Gestionadas"].astype(int)
    resumen["Cantidad_Promesas"] = resumen["Cantidad_Promesas"].astype(int)
    resumen["Valor_Promesas"] = (
        pd.to_numeric(resumen["Valor_Promesas"], errors="coerce")
        .fillna(0)
        .round(0)
        .astype("int64")
    )

    return resumen.sort_values("Valor_Promesas", ascending=False).reset_index(drop=True)

# ------------------------------------------------------------------
# SIDEBAR: Solo carga de archivo
# ------------------------------------------------------------------
st.sidebar.header("Cargar reporte")
archivo_subido = st.sidebar.file_uploader("Sube el reporte consolidado", type=["csv", "xlsx"])

if archivo_subido:
    if archivo_subido.name.endswith(".csv"):
        df_crudo = pd.read_csv(archivo_subido, sep=';', encoding='utf-8-sig', dtype=str)
    else:
        df_crudo = pd.read_excel(archivo_subido)

    if st.sidebar.button("Guardar en Base de Datos"):
        try:
            df_listo = procesar_reporte_baguer(df_crudo)
            nuevos = guardar_df_en_bd(df_listo)
            obtener_productividad.clear()
            total_leidos = len(df_listo)
            duplicados = total_leidos - nuevos
            st.sidebar.success(
                f"Procesados {total_leidos} registros — {nuevos} nuevos, {duplicados} omitidos."
            )
        except Exception as e:
            st.sidebar.error(f"Error al procesar el archivo: {e}")

df_productividad = obtener_productividad()

if df_productividad.empty:
    st.info("Aún no hay registros guardados en la base de datos. Sube y guarda un reporte.")
    st.stop()

# ------------------------------------------------------------------
# PÁGINA PRINCIPAL: Filtros, Resumen y Detalle
# ------------------------------------------------------------------
st.title("📈 Carga de gestiiones y Análisis de Productividad Campaña BAGUER")

# --- LÓGICA DE PREPARACIÓN PARA FILTROS ---
col_asesor = "Nombre_Asesor" if "Nombre_Asesor" in df_productividad.columns else "asesor_gestion"
col_campo = "asesor"

df_productividad["Fecha"] = pd.to_datetime(df_productividad["Fecha"], errors='coerce')
if df_productividad["Fecha"].dt.tz is not None:
    df_productividad["Fecha"] = df_productividad["Fecha"].dt.tz_convert(None)

# 2. Configurar el filtro de fechas
fecha_min = df_productividad["Fecha"].min().date()
fecha_max = df_productividad["Fecha"].max().date()

asesores_disponibles = sorted(df_productividad[col_asesor].dropna().unique().tolist())
campo_disponible = sorted(df_productividad[col_campo].dropna().unique().tolist()) if col_campo in df_productividad.columns else []

# --- UI PRINCIPAL: FILTROS HORIZONTALES ---
st.markdown("### Filtros de Búsqueda")
col_f1, col_f2, col_f3 = st.columns(3)

with col_f1:
    fechas_seleccionadas = st.date_input(
        "Rango de Fechas",
        value=(fecha_max, fecha_max), # La tupla lo mantiene como selector de rango
        min_value=fecha_min,
        max_value=fecha_max
    )

# Validación robusta de los resultados del calendario
if isinstance(fechas_seleccionadas, tuple):
    if len(fechas_seleccionadas) == 2:
        f_inicio, f_fin = fechas_seleccionadas
    elif len(fechas_seleccionadas) == 1:
        f_inicio, f_fin = fechas_seleccionadas[0], fechas_seleccionadas[0]
    else:
        f_inicio, f_fin = fecha_max, fecha_max
else:
    # Si por algún motivo devuelve una sola fecha (no tupla)
    f_inicio, f_fin = fechas_seleccionadas, fechas_seleccionadas

with col_f2:
    asesores_seleccionados = st.multiselect(
        "Asesor",
        options=asesores_disponibles,
        default=asesores_disponibles,
    )

with col_f3:
    if campo_disponible:
        campos_seleccionados = st.multiselect(
            "Campo",
            options=campo_disponible,
            default=campo_disponible,
        )
    else:
        campos_seleccionados = []
        st.info("La columna de Campo no está disponible.")

# --- APLICAR FILTROS AL DATAFRAME ---
if len(fechas_seleccionadas) == 2:
    f_inicio, f_fin = fechas_seleccionadas
else:
    f_inicio, f_fin = fechas_seleccionadas[0], fechas_seleccionadas[0]

f_inicio_dt = pd.to_datetime(f_inicio)
f_fin_dt = pd.to_datetime(f_fin) + pd.Timedelta(days=1, seconds=-1)

condicion_fecha = (df_productividad["Fecha"] >= f_inicio_dt) & (df_productividad["Fecha"] <= f_fin_dt)
condicion_asesor = df_productividad[col_asesor].isin(asesores_seleccionados)

if campos_seleccionados:
    condicion_campo = df_productividad[col_campo].isin(campos_seleccionados)
    df_filtrado = df_productividad[condicion_fecha & condicion_asesor & condicion_campo].copy()
else:
    df_filtrado = df_productividad[condicion_fecha & condicion_asesor].copy()

# --- MÉTRICAS DE RESUMEN ---
st.markdown("---")
resumen_diario = calcular_resumen_productividad(df_filtrado, col_asesor)

st.subheader("Resumen del periodo")
col_m1, col_m2, col_m3 = st.columns(3)

total_cuentas = int(resumen_diario["Cuentas_Gestionadas"].sum())
total_promesas = int(resumen_diario["Cantidad_Promesas"].sum())
total_valor = int(resumen_diario["Valor_Promesas"].sum())

col_m1.metric("Cuentas Gestionadas", f"{total_cuentas:,}".replace(",", "."))
col_m2.metric("Cantidad de Promesas", f"{total_promesas:,}".replace(",", "."))
col_m3.metric("Valor de Promesas", f"$ {total_valor:,}".replace(",", "."))

### ----------------------------  ####### ----------------------------------------------


_hora_actualiz = None
if "Hora" in df_productividad.columns and not df_productividad.empty:
	_fechas_dt = pd.to_datetime(df_productividad["Fecha"], errors="coerce")
	_horas_td = pd.to_timedelta(df_productividad["Hora"].astype("string"), errors="coerce")
	_fechas_horas = _fechas_dt + _horas_td
	_max_gestion = _fechas_horas.dropna().max()
	if pd.notna(_max_gestion):
		_min_redondeado = (_max_gestion.minute // 10) * 10
		_hora_actualiz = _max_gestion.replace(minute=_min_redondeado, second=0, microsecond=0).strftime("%H:%M")

if not _hora_actualiz:
	_ahora = pd.Timestamp.now()
	_min_redondeado = ((_ahora.minute) // 10) * 10
	_hora_actualiz = _ahora.replace(minute=_min_redondeado, second=0, microsecond=0).strftime("%H:%M")

st.divider()

col1, col2, col3, col4, col5, col6=st.columns(6)
with col2:
	st.image("scripts/image/Elite_H_color.png", width=600)
with col5:
	st.image("scripts/image/baguer_logo.png", width=200)


# --- TABLA DE RESULTADOS CON AGGRID ---
st.markdown(
	f"<h3 style='text-align: center; margin-top: 15px; margin-bottom: 15px;'>📊 Productividad x Asesor - Campaña BAGUER &nbsp;&nbsp;·&nbsp;&nbsp; Actualizado: {_hora_actualiz}</h3>",
	unsafe_allow_html=True,
)
# 1. Usamos el DataFrame directamente sin transformar los números a texto
resumen_mostrar = resumen_diario.copy()

# 2. Creamos el código JavaScript para el SEMÁFORO
# Importante: Cambia el 2000000 y el 1000000 por tus metas reales de recaudo
estilo_semaforo = JsCode("""
function(params) {
    let val = params.value;
    let color_fondo = '';
    let color_texto = 'white'; // Texto blanco por defecto
    
    if (val >= 2000000) {
        color_fondo = '#2e7d32'; // Verde (Meta superada)
    } else if (val >= 1000000) {
        color_fondo = '#f9a825'; // Amarillo (Cerca a la meta)
        color_texto = 'black';   // Texto negro para contraste en el amarillo
    } else {
        color_fondo = '#c62828'; // Rojo (Bajo rendimiento)
    }
    
    return {
        'backgroundColor': color_fondo,
        'color': color_texto,
        'fontWeight': 'bold' // Pone el número en Negrita
    };
}
""")

# 3. Creamos el código JavaScript para formatear el número como Moneda
formato_moneda = JsCode("""
function(params) {
    // Convierte el número a formato moneda con puntos locales
    return '$ ' + params.value.toLocaleString('es-CO'); 
}
""")

# 4. Construir y configurar opciones de la grilla
gb = GridOptionsBuilder.from_dataframe(resumen_mostrar)

# Ajuste automático de comportamiento horizontal
gb.configure_default_column(
    resizable=True, 
    filter=True, 
    sortable=True,
    suppressSizeToFit=True 
)
gb.configure_column(col_asesor, header_name="Nombre Asesor",width=300)
gb.configure_column("Cuentas_Gestionadas", header_name="Cuentas Gestionadas", width=180,cellStyle={'textAlign': 'center'})
gb.configure_column("Cantidad_Promesas", header_name="Cantidad de Promesas", width=200, cellStyle={'textAlign': 'center'})
gb.configure_column(
    "Valor_Promesas", 
    header_name="Valor de Promesas",
    width=200,
    cellStyle=estilo_semaforo,
    valueFormatter=formato_moneda
)

gridOptions = gb.build()

# Expande la tabla verticalmente sin paginación (muestra todos los resultados hacia abajo)
gridOptions['domLayout'] = 'autoHeight'

custom_css = {
    ".ag-header": {"background-color": "#1f3b57 !important"},
    ".ag-header-cell-label": {"color": "white !important", "font-weight": "600"},
    ".ag-row-even": {"background-color": "rgba(255,255,255,0.85) !important"},
    ".ag-row-odd": {"background-color": "rgba(242,245,248,0.85) !important"},
}
espacio_izq, col_centro, espacio_der = st.columns([1, 3, 1])
with col_centro:
     
    AgGrid(
        resumen_mostrar,
        custom_css=custom_css,
        gridOptions=gridOptions,
        fit_columns_on_grid_load=True, # Ajustar las columnas al ancho del contenedor
        theme='alpine',                # El tema 'alpine' tiene excelente contraste (filas grises/blancas)
        allow_unsafe_jscode=True,      # OBLIGATORIO: Permite ejecutar el JavaScript del semáforo
    )

st.markdown("---")

imagen_resumen = generar_imagen_productividad(
    resumen_mostrar,
    col_asesor,
    _hora_actualiz,
)

buffer = io.BytesIO()
imagen_resumen.save(buffer, format="JPEG", quality=95)

st.image(imagen_resumen, caption="Vista previa de la imagen")
st.download_button(
    "📥 Descargar imagen del resumen",
    data=buffer.getvalue(),
    file_name=f"productividad_baguer_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.jpg",
    mime="image/jpeg",
)