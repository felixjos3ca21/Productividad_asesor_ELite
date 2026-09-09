import sys
from pathlib import Path
import math
import pandas as pd
import streamlit as st
from scripts.actualizar_archivo import render_actualizar_archivo_sidebar
from scripts.importar_gestiones import DEFAULT_CARPETAS, ejecutar_etl
from scripts.funciones_apoyo import (
    obtener_firma_archivo,
    firma_db,
    cargar_desde_sqlite,
    cargar_catalogo,
    aplicar_homologacion,
    deduplicar_por_llave_negocio,
    construir_resumen_por_asesor,
    calcular_deberia_llevar,
    buscar_columna_case_insensitive,
    formato_moneda,
    icono_pct_relativo,
    barra_azul_monto,
    render_kpi_row,
    render_matriz_html,
    construir_matriz_horaria_acuerdos,
    graficar_heatmap_acuerdos,
    construir_matriz_horaria_contactabilidad,
    graficar_heatmap_contactabilidad,
    construir_resumen_mensual_promesa,
    graficar_combo_mensual,
    render_modulo_adherencia,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DB_PATH = str(_REPO_ROOT / "gestiones.db")



if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_ICON = Path(__file__).parent / "scripts" / "image" / "icono.ico"
st.set_page_config(page_title="Productividad CLARO", layout="wide", page_icon=str(_ICON))

# --- Estado de seleccion ---
if "productividad_seccion" not in st.session_state or st.session_state["productividad_seccion"] is None:
    st.session_state["productividad_seccion"] = "Productividad"

seccion = st.session_state["productividad_seccion"]

# Estilos CSS para los botones de sección (Estilo CLARO Rojo)
st.markdown(
    """
    <style>
    .stButton > button {
        height: 3.6rem !important;
        border-radius: 12px !important;
        transition: all 0.25s ease-in-out !important;
    }
    /* Para forzar tamaño y negrita en el texto interno del botón */
    .stButton > button p,
    .stButton > button div,
    .stButton > button span {
        font-size: 1.4rem !important;
        font-weight: 800 !important;
        line-height: 1.2 !important;
    }
    .stButton > button[kind="secondary"], 
    .stButton > button[data-testid="baseButton-secondary"] {
        background: #fde8e9 !important;
        color: #990011 !important;
        border: 2px solid #f8b4b8 !important;
    }
    .stButton > button[kind="secondary"] p,
    .stButton > button[kind="secondary"] div,
    .stButton > button[kind="secondary"] span,
    .stButton > button[data-testid="baseButton-secondary"] p,
    .stButton > button[data-testid="baseButton-secondary"] div,
    .stButton > button[data-testid="baseButton-secondary"] span {
        color: #990011 !important;
    }
    .stButton > button[kind="secondary"]:hover, 
    .stButton > button[data-testid="baseButton-secondary"]:hover {
        background: #fbd5d8 !important;
        border-color: #e8031b !important;
        transform: translateY(-2px);
        box-shadow: 0 4px 14px rgba(232, 3, 27, 0.2);
    }
    .stButton > button[kind="primary"], 
    .stButton > button[data-testid="baseButton-primary"] {
        background: linear-gradient(135deg, #b80215 0%, #E8031B 100%) !important;
        color: #ffffff !important;
        border: 1px solid #ff4d61 !important;
        box-shadow: 0 4px 18px rgba(232, 3, 27, 0.45) !important;
    }
    .stButton > button[kind="primary"] p,
    .stButton > button[kind="primary"] div,
    .stButton > button[kind="primary"] span,
    .stButton > button[data-testid="baseButton-primary"] p,
    .stButton > button[data-testid="baseButton-primary"] div,
    .stButton > button[data-testid="baseButton-primary"] span {
        color: #ffffff !important;
    }
    .stButton > button[kind="primary"]:hover, 
    .stButton > button[data-testid="baseButton-primary"]:hover {
        background: linear-gradient(135deg, #d00218 0%, #ff1f37 100%) !important;
        transform: translateY(-2px);
        box-shadow: 0 6px 22px rgba(232, 3, 27, 0.65) !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

col1, col2 = st.columns(2)
with col1:
    if st.button(
        "📊 Productividad",
        use_container_width=True,
        type="primary" if seccion == "Productividad" else "secondary",
        key="btn_sec_prod",
    ):
        st.session_state["productividad_seccion"] = "Productividad"
        st.rerun()

with col2:
    if st.button(
        "⏱️ Adherencia",
        use_container_width=True,
        type="primary" if seccion == "Adherencia" else "secondary",
        key="btn_sec_adh",
    ):
        st.session_state["productividad_seccion"] = "Adherencia"
        st.rerun()

st.divider()

# ── Catálogo (lo necesitan ambas secciones) ────────────────────────────────
json_catalogo = "asesores_catalogo.json"
firma_catalogo = obtener_firma_archivo(json_catalogo)
catalogo = cargar_catalogo(json_catalogo, firma_catalogo)

if seccion == "Productividad":
    render_actualizar_archivo_sidebar(_DB_PATH)

    with st.sidebar.expander("🔄 Actualizar desde Carpeta Local", expanded=False):
        carpetas_texto = st.text_area(
            "Carpetas Gestiones (una por línea)",
            value="\n".join(DEFAULT_CARPETAS),
            key="carpetas_gestiones_input",
            height=80,
        )
        carpetas_lista = [c.strip() for c in carpetas_texto.splitlines() if c.strip()]
        forzar_reimport = st.checkbox("Reimportar todo", value=False, key="chk_forzar_etl")
        if st.button("Recargar Gestiones", key="btn_recargar_db", width="stretch"):
            with st.spinner("Procesando e importando gestiones..."):
                res_etl = ejecutar_etl(carpeta_path=carpetas_lista, db_path=_DB_PATH, forzar=forzar_reimport)
                st.cache_data.clear()
                if "error" in res_etl:
                    st.error(res_etl["error"])
                else:
                    st.success(
                        f"¡Base de datos actualizada!\n\n"
                        f"• Registros nuevos: {res_etl['nuevas']}\n"
                        f"• Archivos procesados: {res_etl['procesados']}\n"
                        f"• Sin cambios: {res_etl['sin_cambios']}"
                    )
                    if "advertencia" in res_etl:
                        st.warning(res_etl["advertencia"])
                    st.rerun()

    if not Path(_DB_PATH).exists():
        st.error(
            "No se encontro la base de datos **gestiones.db**.\n\n"
            "Utiliza la sección **'🔄 Actualizar Base de Datos'** en la barra lateral para procesar los archivos de gestiones."
        )
        st.stop()

    df_raw = cargar_desde_sqlite(_DB_PATH, firma_db(_DB_PATH))
	
    if df_raw.empty:
        st.warning("La base de datos esta vacia. Utiliza el botón en la barra lateral para recargar las gestiones.")
        st.stop()

    df_raw["Fecha"] = pd.to_datetime(df_raw["Fecha"], errors="coerce").dt.normalize()
    df_proc = aplicar_homologacion(df_raw, catalogo)

    if "Fecha" not in df_proc.columns:
        st.error("No existe la columna Fecha despues de las transformaciones.")
        st.stop()

    fechas_validas = sorted(df_proc["Fecha"].dropna().unique())
    if not fechas_validas:
        st.error("No hay fechas validas para filtrar.")
        st.stop()

    min_fecha_db = pd.to_datetime(fechas_validas[0]).date()
    max_fecha_db = pd.to_datetime(fechas_validas[-1]).date()

elif seccion == "Adherencia":
    render_modulo_adherencia(_DB_PATH, catalogo)


st.markdown(
	"""
	<style>
	/* ─── KPI Cards ─────────────────────────────────────────── */
	.kpi-row {
		display: flex;
		gap: 10px;
		margin-bottom: 10px;
		flex-wrap: wrap;
	}
	.kpi-card {
		flex: 1;
		min-width: 150px;
		background: #1c2333;
		border-radius: 10px;
		padding: 14px 16px;
		border-top: 3px solid var(--accent, #4e9af1);
		display: flex;
		flex-direction: column;
		gap: 3px;
		box-shadow: 0 2px 10px rgba(0,0,0,0.35);
	}
	.kpi-icon  { font-size: 1.15rem; margin-bottom: 2px; }
	.kpi-label {
		font-size: 1rem;
		color: #7a8199;
		line-height: 2;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.kpi-value {
		font-size: 1.5rem;
		font-weight: 700;
		color: #e6eaf5;
		line-height: 1.0;
		margin-top: 3px;
	}

	/* ─── Matriz de Productividad ────────────────────────────── */
	.mat-wrap {
		overflow-x: auto;
		border-radius: 10px;
		border: 1px solid #2a3050;
		margin-top: 8px;
	}
	.mat-tbl {
		width: 100%;
		border-collapse: collapse;
		font-size: 1rem !important;
		font-family: 'Segoe UI', 'Inter', sans-serif;
		white-space: nowrap;
	}
	.mat-tbl thead tr {
		background: #121827;
		color: #f8fafc;
		font-size: 1.05rem !important;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}
	.mat-tbl thead th {
		padding: 14px 18px;
		text-align: center;
		border-bottom: 2px solid #334155;
		white-space: pre-line;
		font-weight: 800;
		line-height: 1.3;
	}
	.mat-tbl thead th:first-child { text-align: left; padding-left: 20px; }
	.mat-tbl tbody tr:nth-child(odd)  { background: #19203a; }
	.mat-tbl tbody tr:nth-child(even) { background: #1e2640; }
	.mat-tbl tbody tr:hover           { background: #273155; transition: background 0.12s; }
	.mat-tbl tbody td {
		padding: 8px 12px;
		color: #e2e8f0;
		font-weight: 600;
		font-size: 1.6rem;
		text-align: center;
		border-bottom: 1px solid #242d47;
	}
	.mat-tbl tbody td:first-child {
		text-align: left;
		padding: 11px 16px 11px 20px;
		font-weight: 600;
		color: #f8fafc;
		font-size: 1.7rem;
		max-width: 220px;
		white-space: normal;
	}
	</style>
	""",
	unsafe_allow_html=True,
)


if st.session_state["productividad_seccion"] == "Productividad":

	st.title("Productividad Asesores")


	# ── Sección 1: Productividad (Pantalla Principal) ──────────────────────────
	st.markdown("### 🔍 Filtros - Productividad")
	f_col1, f_col2, f_col3, f_col4, f_col5 = st.columns(5)

	with f_col1:
		rango_sel = st.date_input(
			"Rango de Fechas",
			value=(max_fecha_db, max_fecha_db),
			min_value=min_fecha_db,
			max_value=max_fecha_db,
		)

	campos_disponibles = sorted(df_proc.get("Campo", pd.Series(dtype="string")).dropna().astype(str).unique().tolist())
	with f_col2:
		campos_sel = st.multiselect("Campo", options=campos_disponibles)

	col_asesor = "Nombre_Asesor" if "Nombre_Asesor" in df_proc.columns else "asesor_gestion"
	asesores_disponibles = sorted(df_proc[col_asesor].dropna().astype(str).unique().tolist())
	with f_col3:
		asesores_sel = st.multiselect("Asesor", options=asesores_disponibles)

	col_marca = buscar_columna_case_insensitive(df_proc, ["Marca"])
	marcas_disponibles = sorted(df_proc[col_marca].dropna().astype(str).unique().tolist()) if col_marca else []
	with f_col4:
		marcas_sel = st.multiselect("Marca", options=marcas_disponibles)

	col_crm = buscar_columna_case_insensitive(df_proc, ["CRM", "crm"])
	crms_disponibles = sorted(df_proc[col_crm].dropna().astype(str).unique().tolist()) if col_crm else []
	with f_col5:
		crms_sel = st.multiselect("CRM", options=crms_disponibles)

	st.divider()
	# ──────────────────────────────────────────────────────────────────────────

	if isinstance(rango_sel, (tuple, list)):
		if len(rango_sel) == 2:
			fecha_desde, fecha_hasta = rango_sel
		elif len(rango_sel) == 1:
			fecha_desde = fecha_hasta = rango_sel[0]
		else:
			fecha_desde = fecha_hasta = max_fecha_db
	else:
		fecha_desde = fecha_hasta = rango_sel

	f_desde_norm = pd.to_datetime(fecha_desde).normalize()
	f_hasta_norm = pd.to_datetime(fecha_hasta).normalize()

	base = df_proc[(df_proc["Fecha"] >= f_desde_norm) & (df_proc["Fecha"] <= f_hasta_norm)].copy()
	if campos_sel and "Campo" in base.columns:
		base = base[base["Campo"].isin(campos_sel)]
	if asesores_sel:
		base = base[base[col_asesor].isin(asesores_sel)]
	if marcas_sel and col_marca in base.columns:
		base = base[base[col_marca].isin(marcas_sel)]
	if crms_sel and col_crm in base.columns:
		base = base[base[col_crm].isin(crms_sel)]

	base, filas_duplicadas_removidas = deduplicar_por_llave_negocio(base, col_asesor)

	if base.empty:
		st.info("No hay datos para los filtros seleccionados.")
		st.stop()

	resumen_diario = construir_resumen_por_asesor(base, col_asesor)
	resumen_diario = calcular_deberia_llevar(base, resumen_diario, col_asesor)


	total_cuentas_gestionadas = int(resumen_diario["cuentas_gestionadas"].sum())

	if "Identificacion" in base.columns:
		ids_limpios = base["Identificacion"].astype("string").str.strip()
		ids_limpios = ids_limpios.mask(ids_limpios.isin(["", "<NA>", "nan", "None"]), pd.NA)
		total_clientes_gestionados = int(ids_limpios.nunique(dropna=True))
	else:
		total_clientes_gestionados = int(resumen_diario["clientes_Gestionados"].sum())

	asesores_en_vista = max(int(resumen_diario[col_asesor].nunique(dropna=True)), 1)
	promedio_cuentas_gestionadas_x_asesor = total_cuentas_gestionadas / asesores_en_vista
	promedio_cuentas_gestionadas_x_asesor_kpi = int(math.ceil(promedio_cuentas_gestionadas_x_asesor))
	promedio_cuentas_unicas_x_asesor = float(resumen_diario["Gest_cuentas"].mean()) if not resumen_diario.empty else 0.0
	promedio_cuentas_unicas_x_asesor_kpi = int(math.ceil(promedio_cuentas_unicas_x_asesor))
	promedio_clientes_gestionados_x_asesor = float(resumen_diario["clientes_Gestionados"].mean()) if not resumen_diario.empty else 0.0

	cantidad_promesas = int(resumen_diario["Promesas"].sum()) if "Promesas" in resumen_diario.columns else 0
	total_valor_promesas = float(resumen_diario["valor_promesa"].sum()) if "valor_promesa" in resumen_diario.columns else 0.0
	promedio_promesas = float(resumen_diario["Promesas"].mean()) if "Promesas" in resumen_diario.columns and not resumen_diario.empty else 0.0
	promedio_promesas_kpi = int(math.ceil(promedio_promesas))

	st.markdown(render_kpi_row([
		{"label": "Total cuentas gestionadas",       "value": f"{total_cuentas_gestionadas:,}".replace(",", "."),             "icon": "📋", "color": "#4e9af1"},
		{"label": "Total clientes gestionados",       "value": f"{total_clientes_gestionados:,}".replace(",", "."),           "icon": "👥", "color": "#4ecdc4"},
		{"label": "Promedio cuentas x asesor",        "value": f"{promedio_cuentas_gestionadas_x_asesor_kpi:,}".replace(",", "."), "icon": "📊", "color": "#a78bfa"},
		{"label": "Promedio cuentas unicas x asesor", "value": f"{promedio_cuentas_unicas_x_asesor_kpi:,}".replace(",", "."),  "icon": "🔢", "color": "#818cf8"},
	]), unsafe_allow_html=True)

	st.markdown(render_kpi_row([
		{"label": "Cantidad promesas",       "value": f"{cantidad_promesas:,}".replace(",", "."), "icon": "🤝", "color": "#34d399"},
		{"label": "Total valor promesas",    "value": formato_moneda(total_valor_promesas),       "icon": "💰", "color": "#fbbf24"},
		{"label": "Promedio promesas x asesor", "value": f"{promedio_promesas_kpi:,}".replace(",", "."), "icon": "📈", "color": "#fb923c"},
	]), unsafe_allow_html=True)

	_hora_actualiz = None
	if "Hora" in base.columns and not base.empty:
		_fechas_dt = pd.to_datetime(base["Fecha"], errors="coerce")
		_horas_td = pd.to_timedelta(base["Hora"].astype("string"), errors="coerce")
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
	import base64

	@st.cache_data(show_spinner=False)
	def _imagen_a_base64(ruta: str) -> str:
		with open(ruta, "rb") as f:
			return base64.b64encode(f.read()).decode("utf-8")

		
	_logo_elite_b64 = _imagen_a_base64("scripts/image/Elite_H_color.png")
	_logo_claro_b64 = _imagen_a_base64("scripts/image/logo_claro.png")

	st.markdown(
		f"""
		<div style='display:flex; align-items:center; justify-content:space-between; margin-top:15px; margin-bottom:15px;'>
			<img src='data:image/png;base64,{_logo_elite_b64}' style='width:220px; object-fit:contain;'>
			<h3 style='text-align:center; font-size:3.4rem; margin:0; flex:1;'>📊 Productividad x Asesor - Campaña CLARO &nbsp;&nbsp;·&nbsp;&nbsp; Actualizado: {_hora_actualiz}</h3>
			<img src='data:image/png;base64,{_logo_claro_b64}' style='width:140px; object-fit:contain;'>
		</div>
		""",
		unsafe_allow_html=True,
	)

	matriz_ui = resumen_diario.copy()


	def icono_semaforo_deberia(gestionados: int, deberia: float) -> str:
		if gestionados >= deberia:
			return "🟢"
		return "🔴"


	def preparar_matriz_ui(df_resumen: pd.DataFrame, col_asesor: str, incluir_fecha: bool = False) -> pd.DataFrame:
		if df_resumen.empty:
			return pd.DataFrame()

		resumen_ui = df_resumen.copy()
		resumen_ui["cuentas_gestionadas"] = resumen_ui["cuentas_gestionadas"].map(
			lambda v: f"{int(v):,}".replace(",", ".")
		)
		resumen_ui["clientes_Gestionados"] = resumen_ui.apply(
			lambda r: f"{icono_semaforo_deberia(int(r['clientes_Gestionados']), float(r['deberia_llevar']))} {int(r['clientes_Gestionados']):,}".replace(",", "."),
			axis=1,
		)

		min_valor, max_valor = df_resumen["valor_promesa"].min(), df_resumen["valor_promesa"].max()
		resumen_ui["valor_promesa"] = resumen_ui["valor_promesa"].map(
			lambda v: f"{barra_azul_monto(v, min_valor, max_valor)} {formato_moneda(v)}"
		)

		min_contact, max_contact = df_resumen["%_contactabilidad"].min(), df_resumen["%_contactabilidad"].max()
		min_conv, max_conv = df_resumen["%_Conversion"].min(), df_resumen["%_Conversion"].max()

		resumen_ui["%_contactabilidad"] = resumen_ui["%_contactabilidad"].map(
			lambda v: f"{icono_pct_relativo(v, min_contact, max_contact)} {v:.2f}%"
		)
		resumen_ui["%_Conversion"] = resumen_ui["%_Conversion"].map(
			lambda v: f"{icono_pct_relativo(v, min_conv, max_conv)} {v:.2f}%"
		)
		resumen_ui["deberia_llevar"] = resumen_ui["deberia_llevar"].map(
			lambda v: f"{int(round(v)):,.0f}".replace(",", ".")
		)

		columnas_vista = [
			col_asesor,
		]
		if incluir_fecha and "Fecha" in resumen_ui.columns:
			columnas_vista.append("Fecha")

		columnas_vista.extend([
			"cuentas_gestionadas",
			"deberia_llevar",
			"clientes_Gestionados",
			"contacto_directo",
			"contacto_indirecto",
			"no_contacto",
			"Promesas",
			"valor_promesa",
			"%_contactabilidad",
			"%_Conversion",
		])

		renombrar_mapa = {
			col_asesor: "Asesor",
			"Fecha": "Fecha",
			"cuentas_gestionadas": "Cuentas\ngestionadas",
			"clientes_Gestionados": "Clientes\ngestionados",
			"contacto_directo": "Contacto\ndirecto",
			"contacto_indirecto": "Contacto\nindirecto",
			"no_contacto": "No\ncontacto",
			"Promesas": "Promesas",
			"deberia_llevar": "Deberia\nllevar",
			"valor_promesa": "Valor\npromesa",
			"%_contactabilidad": "%\nContactabilidad",
			"%_Conversion": "%\nConversion",
		}

		return resumen_ui[columnas_vista].rename(columns=renombrar_mapa)


	# ── Renderizado Reporte 1: Consolidado del Rango ─────────────────────────
	matriz_mostrar_consolidado = preparar_matriz_ui(resumen_diario, col_asesor, incluir_fecha=False)
	st.markdown(render_matriz_html(matriz_mostrar_consolidado), unsafe_allow_html=True)

	csv_export_consolidado = resumen_diario.to_csv(index=False).encode("utf-8")
	nombre_archivo_consolidado = (
		f"resumen_productividad_{fecha_desde}.csv"
		if fecha_desde == fecha_hasta
		else f"resumen_productividad_{fecha_desde}_a_{fecha_hasta}.csv"
	)
	st.download_button(
		label="Descargar resumen consolidado (CSV)",
		data=csv_export_consolidado,
		file_name=nombre_archivo_consolidado,
		mime="text/csv",
		key="btn_descargar_consolidado",
	)

	st.divider()


	col1, col2, col3, col4, col5, col6=st.columns(6)
	with col1:
		st.image("scripts/image/Elite_H_color.png", width=300)
	with col6:
		st.image("scripts/image/logo_claro.png", width=200)

	# ── Renderizado Reporte 2: Detalle Diario por Asesor ──────────────────────
	st.markdown("<h3 style='text-align: center; margin-top: 20px; margin-bottom: 15px;'>📅 Detalle de Gestiones por Día y Asesor</h3>", unsafe_allow_html=True)

	lista_resumenes_diarios = []
	for fecha_val, df_dia in base.groupby("Fecha"):
		res_dia = construir_resumen_por_asesor(df_dia, col_asesor)
		res_dia = calcular_deberia_llevar(df_dia, res_dia, col_asesor)
		res_dia["Fecha"] = pd.to_datetime(fecha_val).strftime("%d/%m/%Y")
		res_dia["_fecha_dt"] = pd.to_datetime(fecha_val)
		lista_resumenes_diarios.append(res_dia)

	if lista_resumenes_diarios:
		resumen_diario_por_fecha = pd.concat(lista_resumenes_diarios, ignore_index=True)
		resumen_diario_por_fecha = resumen_diario_por_fecha.sort_values(
			by=[col_asesor, "_fecha_dt"], ascending=[True, True]
		).drop(columns=["_fecha_dt"])

		matriz_mostrar_diario = preparar_matriz_ui(resumen_diario_por_fecha, col_asesor, incluir_fecha=True)
		st.markdown(render_matriz_html(matriz_mostrar_diario), unsafe_allow_html=True)

		csv_export_diario = resumen_diario_por_fecha.to_csv(index=False).encode("utf-8")
		nombre_archivo_diario = f"detalle_diario_productividad_{fecha_desde}_a_{fecha_hasta}.csv"
		st.download_button(
			label="Descargar detalle diario por asesor (CSV)",
			data=csv_export_diario,
			file_name=nombre_archivo_diario,
			mime="text/csv",
			key="btn_descargar_diario",
		)

	st.divider()
	st.markdown("<h3 style='text-align: center; margin-top: 20px; margin-bottom: 15px;'>🕒 Concentración Horaria de Acuerdos y Contactabilidad</h3>", unsafe_allow_html=True)

	matriz_horaria_acuerdos = construir_matriz_horaria_acuerdos(base)
	matriz_horaria_contacto = construir_matriz_horaria_contactabilidad(base)

	col_hm1, col_hm2 = st.columns(2)
	with col_hm1:
		st.markdown("**Acuerdos por hora del día**")
		fig_acuerdos = graficar_heatmap_acuerdos(matriz_horaria_acuerdos)
		if fig_acuerdos is not None:
			st.plotly_chart(fig_acuerdos, width="stretch")
		else:
			st.info("No hay acuerdos para los filtros seleccionados.")

	with col_hm2:
		st.markdown("**Contactabilidad por hora del día**")
		fig_contacto = graficar_heatmap_contactabilidad(matriz_horaria_contacto)
		if fig_contacto is not None:
			st.plotly_chart(fig_contacto, width="stretch")
		else:
			st.info("No hay gestiones para los filtros seleccionados.")

	st.divider()
	st.markdown("<h3 style='text-align: center; margin-top: 20px; margin-bottom: 15px;'>📈 Comportamiento Mensual de Acuerdos</h3>", unsafe_allow_html=True)

	resumen_diario_mes = construir_resumen_mensual_promesa(base)
	fig_mensual = graficar_combo_mensual(resumen_diario_mes)
	if fig_mensual is not None:
		st.plotly_chart(fig_mensual, width="stretch")
	else:
		st.info("No hay acuerdos para los filtros seleccionados.")
