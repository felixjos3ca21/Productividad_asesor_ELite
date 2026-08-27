import json
import math
import sqlite3
import sys
from pathlib import Path
import pandas as pd
import streamlit as st
from scripts.actualizar_archivo import render_actualizar_archivo_sidebar
from scripts.importar_gestiones import DEFAULT_CARPETAS, ejecutar_etl	
import plotly.graph_objects as go
import numpy as np


_REPO_ROOT = Path(__file__).resolve().parent.parent
_DB_PATH = str(_REPO_ROOT / "gestiones.db")


render_actualizar_archivo_sidebar(_DB_PATH)

if str(_REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(_REPO_ROOT))


_ICON = Path(__file__).parent / "scripts" / "image" / "icono.ico"
st.set_page_config(page_title="Elite Abogados BPO - Productividad", layout="wide", page_icon=str(_ICON))

st.title("Productividad Asesores")


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
		font-size: 0.75rem;
		font-family: 'Segoe UI', 'Inter', sans-serif;
		white-space: nowrap;
	}
	.mat-tbl thead tr {
		background: #121827;
		color: #f8fafc;
		font-size: 0.78rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}
	.mat-tbl thead th {
		padding: 11px 14px;
		text-align: center;
		border-bottom: 2px solid #334155;
		white-space: pre-line;
		font-weight: 800;
		line-height: 1.3;
	}
	.mat-tbl thead th:first-child { text-align: left; padding-left: 16px; }
	.mat-tbl tbody tr:nth-child(odd)  { background: #19203a; }
	.mat-tbl tbody tr:nth-child(even) { background: #1e2640; }
	.mat-tbl tbody tr:hover           { background: #273155; transition: background 0.12s; }
	.mat-tbl tbody td {
		padding: 6px 12px;
		color: #e2e8f0;
		font-weight: 600;
		font-size: 0.76rem;
		text-align: center;
		border-bottom: 1px solid #242d47;
	}
	.mat-tbl tbody td:first-child {
		text-align: left;
		padding: 7px 12px 7px 16px;
		font-weight: 700;
		color: #f8fafc;
		font-size: 0.78rem;
		max-width: 220px;
		white-space: normal;
	}
	</style>
	""",
	unsafe_allow_html=True,
)


def obtener_firma_archivo(path_texto: str) -> tuple:
	path = Path(path_texto)
	if not path.exists() or not path.is_file():
		return tuple()
	stat = path.stat()
	return (str(path.resolve()), stat.st_mtime_ns, stat.st_size)


def _firma_db(db_path: str) -> tuple:
	"""Firma del archivo gestiones.db para invalidar cache cuando cambia."""
	return obtener_firma_archivo(db_path)


@st.cache_data(show_spinner="Cargando gestiones desde base de datos...", ttl=None)
def cargar_desde_sqlite(db_path: str, firma_db: tuple) -> pd.DataFrame:
	if not Path(db_path).exists():
		return pd.DataFrame()
	try:
		con = sqlite3.connect(db_path)
		df = pd.read_sql_query(
			"SELECT * FROM gestiones",
			con,
			parse_dates=["Fecha", "FechaPromesa"],
		)
		con.close()
		return df
	except Exception as e:
		st.error(f"Error leyendo gestiones.db: {e}")
		return pd.DataFrame()


def primera_columna(df_base: pd.DataFrame, candidatas: list[str]):
	for c in candidatas:
		if c in df_base.columns:
			return c
	return None


def buscar_columna_case_insensitive(df_base: pd.DataFrame, candidatas: list[str]):
	mapa = {str(c).strip().lower(): c for c in df_base.columns}
	for c in candidatas:
		col = mapa.get(str(c).strip().lower())
		if col is not None:
			return col
	return None


def a_hora_hhmmss(serie: pd.Series) -> pd.Series:
	s = serie.astype("string").str.strip()
	salida = pd.Series(pd.NA, index=serie.index, dtype="string")

	dt_hms = pd.to_datetime(s, format="%H:%M:%S", errors="coerce")
	mask_hms = dt_hms.notna()
	salida.loc[mask_hms] = dt_hms.loc[mask_hms].dt.strftime("%H:%M:%S")

	mask_restante = salida.isna()
	if mask_restante.any():
		dt_hm = pd.to_datetime(s.loc[mask_restante], format="%H:%M", errors="coerce")
		mask_hm = dt_hm.notna()
		if mask_hm.any():
			idx_hm = dt_hm.index[mask_hm]
			salida.loc[idx_hm] = dt_hm.loc[idx_hm].dt.strftime("%H:%M:%S")

	mask_restante = salida.isna()
	if mask_restante.any():
		td = pd.to_timedelta(s.loc[mask_restante], errors="coerce")
		mask_td = td.notna()
		if mask_td.any():
			idx_td = td.index[mask_td]
			segs = td.loc[idx_td].dt.total_seconds().astype(int).abs()
			h = (segs // 3600).astype(str).str.zfill(2)
			m = ((segs % 3600) // 60).astype(str).str.zfill(2)
			sec = (segs % 60).astype(str).str.zfill(2)
			salida.loc[idx_td] = (h + ":" + m + ":" + sec).astype("string")

	return salida


def transformar_df(df_base: pd.DataFrame) -> pd.DataFrame:
	df = df_base.copy()
	col_fecha = primera_columna(df, ["Fecha", "fechagestion", "fecha_gestion"])
	col_hora = primera_columna(df, ["Hora", "horagestion", "hora_gestion"])
	col_tg = primera_columna(df, ["Tiempo_Gestion", "tiempogestion", "tiempo_gestion"])
	col_tl = primera_columna(df, ["Tiempo_Llamada", "tiempollamada", "tiempo_llamada"])
	col_id = primera_columna(df, ["Identificacion", "identification", "identificacion"])
	col_cuenta = primera_columna(df, ["Cuenta", "cuenta"])
	col_fp = primera_columna(df, ["FechaPromesa", "fechapromesa", "fecha_promesa"])

	if col_fecha:
		df["Fecha"] = pd.to_datetime(df[col_fecha], errors="coerce").dt.normalize()
	if col_hora:
		df["Hora"] = a_hora_hhmmss(df[col_hora])
	if col_tg:
		df["Tiempo_Gestion"] = a_hora_hhmmss(df[col_tg])
	if col_tl:
		df["Tiempo_Llamada"] = a_hora_hhmmss(df[col_tl])
	if col_id:
		df["Identificacion"] = df[col_id].astype("string").str.strip()
	if col_cuenta:
		df["Cuenta"] = df[col_cuenta].astype("string").str.replace("-", "", regex=False).str.strip()
	if col_fp:
		df["FechaPromesa"] = pd.to_datetime(df[col_fp], errors="coerce").dt.normalize()

	return df


@st.cache_data(show_spinner=False)
def cargar_catalogo(path_texto: str, firma_catalogo: tuple) -> dict:
	path = Path(path_texto)
	if path.exists():
		return json.loads(path.read_text(encoding="utf-8-sig"))
	return {}


def construir_mapa_catalogo(catalogo: dict) -> pd.DataFrame:
	filas = []
	for asesor_gestion, cfg in catalogo.items():
		if not isinstance(cfg, dict):
			continue

		vigencias = cfg.get("vigencias")
		if isinstance(vigencias, list) and vigencias:
			for v in vigencias:
				if not isinstance(v, dict):
					continue
				filas.append(
					{
						"asesor_gestion": asesor_gestion,
						"Nombre_Asesor": v.get("Nombre_Asesor", cfg.get("Nombre_Asesor", asesor_gestion)),
						"Campo": v.get("Campo", cfg.get("Campo", "Pendiente")),
						"desde": pd.to_datetime(v.get("desde"), errors="coerce").normalize() if v.get("desde") else pd.NaT,
						"hasta": pd.to_datetime(v.get("hasta"), errors="coerce").normalize() if v.get("hasta") else pd.NaT,
					}
				)
		else:
			filas.append(
				{
					"asesor_gestion": asesor_gestion,
					"Nombre_Asesor": cfg.get("Nombre_Asesor", asesor_gestion),
					"Campo": cfg.get("Campo", "Pendiente"),
					"desde": pd.NaT,
					"hasta": pd.NaT,
				}
			)

	if not filas:
		return pd.DataFrame(columns=["asesor_gestion", "Nombre_Asesor", "Campo", "desde", "hasta"])

	return pd.DataFrame(filas)


def aplicar_homologacion(df_base: pd.DataFrame, catalogo: dict) -> pd.DataFrame:
	if "asesor_gestion" not in df_base.columns:
		return df_base

	base = df_base.copy()
	cols_a_reemplazar = [c for c in ["Nombre_Asesor", "Campo"] if c in base.columns]
	if cols_a_reemplazar:
		base = base.drop(columns=cols_a_reemplazar)

	if not catalogo:
		base["Nombre_Asesor"] = base["asesor_gestion"]
		base["Campo"] = "Pendiente"
		return base

	mapa_df = construir_mapa_catalogo(catalogo)
	if mapa_df.empty:
		base["Nombre_Asesor"] = base["asesor_gestion"]
		base["Campo"] = "Pendiente"
		return base

	base = base.reset_index(drop=True).copy()
	base["__row_id"] = base.index
	salida = base.merge(mapa_df, on="asesor_gestion", how="left")

	if "Fecha" in salida.columns:
		fecha = pd.to_datetime(salida["Fecha"], errors="coerce").dt.normalize()
		desde_ok = salida["desde"].isna() | (fecha >= salida["desde"])
		hasta_ok = salida["hasta"].isna() | (fecha <= salida["hasta"])
		validas = salida[desde_ok & hasta_ok].copy()
	else:
		validas = salida.copy()

	if validas.empty:
		elegidas = base[["__row_id", "asesor_gestion"]].copy()
		elegidas["Nombre_Asesor"] = elegidas["asesor_gestion"]
		elegidas["Campo"] = "Pendiente"
	else:
		validas["__desde_sort"] = validas["desde"].fillna(pd.Timestamp("1900-01-01"))
		validas["__abierta_sort"] = validas["hasta"].isna().astype(int)
		validas = validas.sort_values(["__row_id", "__abierta_sort", "__desde_sort"], ascending=[True, False, False])
		elegidas = validas.groupby("__row_id", as_index=False).first()

	salida_final = base.merge(elegidas[["__row_id", "Nombre_Asesor", "Campo"]], on="__row_id", how="left")
	salida_final["Nombre_Asesor"] = salida_final["Nombre_Asesor"].fillna(salida_final["asesor_gestion"])
	salida_final["Campo"] = salida_final["Campo"].fillna("Pendiente")
	return salida_final.drop(columns=["__row_id"])


def deduplicar_por_llave_negocio(df_base: pd.DataFrame, col_asesor: str) -> tuple[pd.DataFrame, int]:
	base = df_base.copy()
	cols_llave = [c for c in ["Fecha", "Hora", "Cuenta", col_asesor, "Identificacion"] if c in base.columns]
	if not cols_llave:
		return base, 0

	for c in cols_llave:
		base[c] = base[c].astype("string").str.strip().fillna("")

	antes = len(base)
	base = base.drop_duplicates(subset=cols_llave, keep="first")
	removidos = antes - len(base)
	return base, removidos


def construir_resumen_por_asesor(base_dia: pd.DataFrame, col_asesor: str) -> pd.DataFrame:
	base = base_dia.copy()
	base["Cuenta"] = base["Cuenta"].astype("string").str.strip()
	base.loc[base["Cuenta"].isin(["", "<NA>", "nan", "None"]), "Cuenta"] = pd.NA

	base["Identificacion"] = base["Identificacion"].astype("string").str.strip()
	base.loc[base["Identificacion"].isin(["", "<NA>", "nan", "None"]), "Identificacion"] = pd.NA

	base["llave_gestion_unica"] = (
		base["Cuenta"].astype("string").fillna("").str.strip() + "|" + base["Hora"].astype("string").fillna("").str.strip()
	)

	resumen_gest_cuentas = base.groupby(col_asesor, dropna=False)["Cuenta"].nunique(dropna=True).reset_index(name="Gest_cuentas")
	resumen_gestiones = (
		base.groupby(col_asesor, dropna=False)["llave_gestion_unica"].nunique().reset_index(name="cuentas_gestionadas")
	)
	resumen_clientes = (
		base.groupby(col_asesor, dropna=False)["Identificacion"].nunique(dropna=True).reset_index(name="clientes_Gestionados")
	)

	perfiles_contacto_directo = {
		"pago parcial", "contesta y cuelga", "ya pago", "promesa de pago", "renuente", "llamar luego", 
		"no hubo acuerdo", "colgo", "voluntad de pago", "promesa de pago con descuento", 
		"no es el encargado del pago", "promesa con tercero", "dificultad de pago", "pago no abonado", 
		"reclamacion", "recordatorio", "encargado renuente", "promesa whatsapp", "abono", "al dia",
	}
	perfiles_contacto_indirecto = {
		"equivocado", "mensaje con tercero", "tercero no conoce al titular", 
		"tercero no toma mensaje", "fallecio",
	}
	perfiles_no_contacto = {"no contesta", "mensaje en buzon", "no contacto", "ilocalizado"}
	perfiles_promesas = {"promesa de pago", "promesa de pago con descuento", "promesa con tercero"}

	if "ultimo_perfil_cliente" in base.columns:
		perfil_norm = base["ultimo_perfil_cliente"].astype("string").str.strip().str.lower()
		mask_directo = perfil_norm.isin(perfiles_contacto_directo)
		mask_indirecto = perfil_norm.isin(perfiles_contacto_indirecto)
		mask_no_contacto = perfil_norm.isin(perfiles_no_contacto)
		mask_promesas = perfil_norm.isin(perfiles_promesas)

		resumen_contacto_directo = base.loc[mask_directo].groupby(col_asesor, dropna=False)["Cuenta"].nunique(dropna=True).reset_index(name="contacto_directo")
		resumen_contacto_indirecto = base.loc[mask_indirecto].groupby(col_asesor, dropna=False)["Cuenta"].nunique(dropna=True).reset_index(name="contacto_indirecto")
		resumen_no_contacto = base.loc[mask_no_contacto].groupby(col_asesor, dropna=False)["Cuenta"].nunique(dropna=True).reset_index(name="no_contacto")
		resumen_promesas = base.loc[mask_promesas].groupby(col_asesor, dropna=False)["Cuenta"].nunique(dropna=True).reset_index(name="Promesas")
	else:
		resumen_contacto_directo = pd.DataFrame(columns=[col_asesor, "contacto_directo"])
		resumen_contacto_indirecto = pd.DataFrame(columns=[col_asesor, "contacto_indirecto"])
		resumen_no_contacto = pd.DataFrame(columns=[col_asesor, "no_contacto"])
		resumen_promesas = pd.DataFrame(columns=[col_asesor, "Promesas"])

	col_valorpromesa = "valorpromesa" if "valorpromesa" in base.columns else "valor_promesa" if "valor_promesa" in base.columns else None
	if col_valorpromesa:
		tmp_valor = base[[col_asesor, "Cuenta", col_valorpromesa]].copy()
		tmp_valor[col_valorpromesa] = pd.to_numeric(tmp_valor[col_valorpromesa], errors="coerce")
		min_por_cuenta = (
			tmp_valor.dropna(subset=["Cuenta"])
			.groupby([col_asesor, "Cuenta"], dropna=False)[col_valorpromesa]
			.min()
			.reset_index(name="min_valor_cuenta")
		)
		resumen_valor_promesa = (
			min_por_cuenta.groupby(col_asesor, dropna=False)["min_valor_cuenta"].sum(min_count=1).reset_index(name="valor_promesa")
		)
	else:
		resumen_valor_promesa = pd.DataFrame(columns=[col_asesor, "valor_promesa"])

	resumen = (
		resumen_gestiones.merge(resumen_gest_cuentas, on=col_asesor, how="outer")
		.merge(resumen_clientes, on=col_asesor, how="outer")
		.merge(resumen_contacto_directo, on=col_asesor, how="outer")
		.merge(resumen_contacto_indirecto, on=col_asesor, how="outer")
		.merge(resumen_no_contacto, on=col_asesor, how="outer")
		.merge(resumen_promesas, on=col_asesor, how="outer")
		.merge(resumen_valor_promesa, on=col_asesor, how="outer")
		.fillna(0)
	)

	columnas_enteras = [
		"cuentas_gestionadas",
		"Gest_cuentas",
		"clientes_Gestionados",
		"contacto_directo",
		"contacto_indirecto",
		"no_contacto",
		"Promesas",
	]
	for c in columnas_enteras:
		if c in resumen.columns:
			resumen[c] = resumen[c].astype(int)

	resumen["valor_promesa"] = pd.to_numeric(resumen["valor_promesa"], errors="coerce").fillna(0)
	resumen["%_contactabilidad"] = (resumen["contacto_directo"].div(resumen["Gest_cuentas"].replace(0, pd.NA)).fillna(0) * 100).round(2)
	resumen["%_Conversion"] = (resumen["Promesas"].div(resumen["contacto_directo"].replace(0, pd.NA)).fillna(0) * 100).round(2)

	return resumen.sort_values("valor_promesa", ascending=False).reset_index(drop=True)


def calcular_deberia_llevar(base_rango: pd.DataFrame, resumen_diario: pd.DataFrame, col_asesor: str) -> pd.DataFrame:
	if "Hora" not in base_rango.columns or "Fecha" not in base_rango.columns or base_rango.empty:
		salida = resumen_diario.copy()
		salida["deberia_llevar"] = 0.0
		return salida

	hoy = pd.Timestamp.now().normalize()
	agora = pd.Timestamp.now()
	hora_corte_hoy = pd.to_timedelta(f"{agora.hour:02d}:{agora.minute:02d}:{agora.second:02d}")
	inicio_almuerzo = pd.to_timedelta("12:00:00")
	fin_almuerzo = pd.to_timedelta("13:00:00")

	totales_asesor = {}

	for fecha, df_dia in base_rango.groupby("Fecha"):
		base_horas = df_dia[[col_asesor, "Hora"]].copy()
		base_horas["Hora"] = pd.to_timedelta(base_horas["Hora"].astype("string"), errors="coerce")
		base_horas = base_horas.dropna(subset=["Hora"])

		if base_horas.empty:
			continue

		primera_hora_asesor = base_horas.groupby(col_asesor, dropna=False)["Hora"].min()

		fecha_norm = pd.to_datetime(fecha).normalize()
		if fecha_norm == hoy:
			hora_corte = hora_corte_hoy
		else:
			hora_corte = base_horas["Hora"].max()

		total_transcurrido = (hora_corte - primera_hora_asesor).clip(lower=pd.Timedelta(0))

		if hora_corte <= inicio_almuerzo:
			cruce_almuerzo = pd.Series(pd.Timedelta(0), index=primera_hora_asesor.index)
		else:
			fin_cruce = min(hora_corte, fin_almuerzo)
			inicio_cruce = primera_hora_asesor.where(primera_hora_asesor > inicio_almuerzo, inicio_almuerzo)
			cruce_almuerzo = (fin_cruce - inicio_cruce).clip(lower=pd.Timedelta(0))

		horas_productivas = (total_transcurrido - cruce_almuerzo).clip(lower=pd.Timedelta(0))
		deberia = (horas_productivas.dt.total_seconds() / 3600.0) * 25.0
		deberia = deberia.clip(lower=0)
		deberia = (deberia / 5.0).round() * 5.0

		for asesor, val in deberia.items():
			totales_asesor[asesor] = totales_asesor.get(asesor, 0.0) + float(val)

	tmp = pd.DataFrame(list(totales_asesor.items()), columns=[col_asesor, "deberia_llevar"])
	salida = resumen_diario.merge(tmp, on=col_asesor, how="left")
	salida["deberia_llevar"] = salida["deberia_llevar"].fillna(0.0)
	return salida



def icono_pct(v: float) -> str:
	if v >= 70:
		return "🟢"
	if v >= 50:
		return "🟡"
	return "🔴"


def icono_pct_relativo(v: float, minimo: float, maximo: float) -> str:
	if pd.isna(v):
		return "⚪"

	rango = maximo - minimo
	if abs(rango) < 1e-9:
		return "🟡"

	pos_rel = (v - minimo) / rango
	if pos_rel < (1 / 3):
		return "🔴"
	if pos_rel < (2 / 3):
		return "🟡"
	return "🟢"


def barra_azul_monto(v: float, minimo: float, maximo: float) -> str:
	if pd.isna(v):
		return "⬜"

	rango = maximo - minimo
	if abs(rango) < 1e-9:
		nivel = 3
	else:
		pos_rel = (v - minimo) / rango
		nivel = int(pos_rel * 4) + 1
		nivel = max(1, min(5, nivel))

	return "🟦" * nivel + "⬜" * (5 - nivel)


def formato_moneda(v: float) -> str:
	return f"$ {v:,.0f}".replace(",", ".")


def _kpi_card(label: str, value: str, icon: str, color: str) -> str:
	return (
		f'<div class="kpi-card" style="--accent:{color}">'
		f'<span class="kpi-icon">{icon}</span>'
		f'<span class="kpi-label">{label}</span>'
		f'<span class="kpi-value">{value}</span>'
		f'</div>'
	)


def _render_kpi_row(cards: list) -> str:
	items = "".join(_kpi_card(**c) for c in cards)
	return f'<div class="kpi-row">{items}</div>'


def _render_matriz_html(df: pd.DataFrame) -> str:
	def _e(s: str) -> str:
		return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

	encabezados = "".join(f"<th>{_e(c)}</th>" for c in df.columns)
	filas = []
	for _, row in df.iterrows():
		celdas = "".join(f"<td>{_e(v)}</td>" for v in row.values)
		filas.append(f"<tr>{celdas}</tr>")
	cuerpo = "".join(filas)
	return (
		'<div class="mat-wrap">'
		f'<table class="mat-tbl"><thead><tr>{encabezados}</tr></thead>'
		f'<tbody>{cuerpo}</tbody></table>'
		'</div>'
	)

def construir_matriz_horaria_acuerdos(base_filtrada: pd.DataFrame) -> pd.DataFrame:
	base = base_filtrada.copy()
	base["Cuenta"] = base["Cuenta"].astype("string").str.strip()
	base.loc[base["Cuenta"].isin(["", "<NA>", "nan", "None"]), "Cuenta"] = pd.NA
	base["Fecha"] = pd.to_datetime(base["Fecha"], errors="coerce").dt.date

	perfiles_promesas = {"promesa de pago", "promesa de pago con descuento", "promesa con tercero"}

	if "ultimo_perfil_cliente" not in base.columns:
		return pd.DataFrame(columns=["Fecha", "hora_bin", "cantidad_acuerdos", "valor_acuerdos"])

	perfil_norm = base["ultimo_perfil_cliente"].astype("string").str.strip().str.lower()
	mask_promesas = perfil_norm.isin(perfiles_promesas)

	base["hora_bin"] = pd.to_timedelta(base["Hora"], errors="coerce").dt.components["hours"]
	base = base[base["hora_bin"].between(8, 17)]

	col_valorpromesa = "valorpromesa" if "valorpromesa" in base.columns else "valor_promesa" if "valor_promesa" in base.columns else None

	base_promesas = base.loc[mask_promesas].dropna(subset=["Cuenta", "Fecha"]).copy()

	cantidad = (
		base_promesas.groupby(["Fecha", "hora_bin"], dropna=False)["Cuenta"]
		.nunique()
		.reset_index(name="cantidad_acuerdos")
	)

	if col_valorpromesa:
		base_promesas[col_valorpromesa] = pd.to_numeric(base_promesas[col_valorpromesa], errors="coerce")
		base_con_valor = base_promesas.dropna(subset=[col_valorpromesa])
		if not base_con_valor.empty:
			idx_min = base_con_valor.groupby(["Cuenta", "Fecha"])[col_valorpromesa].idxmin()
			filas_min = base_con_valor.loc[idx_min]
			valor = (
				filas_min.groupby(["Fecha", "hora_bin"], dropna=False)[col_valorpromesa]
				.sum(min_count=1)
				.reset_index(name="valor_acuerdos")
			)
		else:
			valor = pd.DataFrame(columns=["Fecha", "hora_bin", "valor_acuerdos"])
	else:
		valor = pd.DataFrame(columns=["Fecha", "hora_bin", "valor_acuerdos"])

	matriz = cantidad.merge(valor, on=["Fecha", "hora_bin"], how="outer").fillna(0)
	matriz["hora_bin"] = matriz["hora_bin"].astype(int)
	matriz["cantidad_acuerdos"] = matriz["cantidad_acuerdos"].astype(int)
	return matriz






def graficar_heatmap_acuerdos(matriz: pd.DataFrame):
	if matriz.empty:
		return None

	horas = sorted(matriz["hora_bin"].unique())
	fechas = sorted(matriz["Fecha"].unique())

	pivot_cantidad = matriz.pivot(index="hora_bin", columns="Fecha", values="cantidad_acuerdos").reindex(index=horas, columns=fechas).fillna(0)
	pivot_valor = matriz.pivot(index="hora_bin", columns="Fecha", values="valor_acuerdos").reindex(index=horas, columns=fechas).fillna(0)

	etiquetas_hora = [f"{h % 12 if h % 12 != 0 else 12}:00 {'AM' if h < 12 else 'PM'}" for h in horas]

	valores_cantidad = pivot_cantidad.values.astype(float)
	max_por_dia = valores_cantidad.max(axis=0)
	max_por_dia_seguro = np.where(max_por_dia == 0, 1, max_por_dia)
	z_normalizado = valores_cantidad / max_por_dia_seguro

	customdata = np.dstack([valores_cantidad, pivot_valor.values])

	fig = go.Figure(
		data=go.Heatmap(
			z=z_normalizado,
			x=[str(f) for f in fechas],
			y=etiquetas_hora,
			customdata=customdata,
			colorscale="Blues",
			zmin=0,
			zmax=1,
			hovertemplate="Fecha: %{x}<br>Hora: %{y}<br>Acuerdos: %{customdata[0]:.0f}<br>Valor: $%{customdata[1]:,.0f}<extra></extra>",
			colorbar=dict(title="Concentración<br>(relativa al día)"),
		)
	)
	fig.update_layout(
		height=450,
		xaxis_title="Fecha",
		yaxis_title="Hora del día",
		xaxis=dict(tickangle=-45, type="category"),
		yaxis=dict(autorange="reversed"),
		margin=dict(l=60, r=20, t=30, b=80),
	)
	return fig


def construir_matriz_horaria_contactabilidad(base_filtrada: pd.DataFrame) -> pd.DataFrame:
	base = base_filtrada.copy()
	base["Cuenta"] = base["Cuenta"].astype("string").str.strip()
	base.loc[base["Cuenta"].isin(["", "<NA>", "nan", "None"]), "Cuenta"] = pd.NA
	base["Fecha"] = pd.to_datetime(base["Fecha"], errors="coerce").dt.date
 
	perfiles_contacto_directo = {
		"pago parcial", "contesta y cuelga", "ya pago", "promesa de pago", "renuente", "llamar luego",
		"no hubo acuerdo", "colgo", "voluntad de pago", "promesa de pago con descuento",
		"no es el encargado del pago", "promesa con tercero", "dificultad de pago", "pago no abonado",
		"reclamacion", "recordatorio", "encargado renuente", "promesa whatsapp", "abono", "al dia",
	}
 
	if "ultimo_perfil_cliente" not in base.columns:
		return pd.DataFrame(columns=["Fecha", "hora_bin", "gestiones_hora", "contactos_hora", "pct_contactabilidad"])
 
	perfil_norm = base["ultimo_perfil_cliente"].astype("string").str.strip().str.lower()
	mask_directo = perfil_norm.isin(perfiles_contacto_directo)
 
	base["hora_bin"] = pd.to_timedelta(base["Hora"], errors="coerce").dt.components["hours"]
	base = base[base["hora_bin"].between(8, 17)]
	base_valida = base.dropna(subset=["Cuenta", "Fecha"])
 
	gestiones = (
		base_valida.groupby(["Fecha", "hora_bin"], dropna=False)["Cuenta"]
		.nunique()
		.reset_index(name="gestiones_hora")
	)
	contactos = (
		base_valida.loc[mask_directo]
		.groupby(["Fecha", "hora_bin"], dropna=False)["Cuenta"]
		.nunique()
		.reset_index(name="contactos_hora")
	)
 
	matriz = gestiones.merge(contactos, on=["Fecha", "hora_bin"], how="left").fillna(0)
	matriz["gestiones_hora"] = matriz["gestiones_hora"].astype(int)
	matriz["contactos_hora"] = matriz["contactos_hora"].astype(int)
	matriz["pct_contactabilidad"] = (matriz["contactos_hora"] / matriz["gestiones_hora"].replace(0, pd.NA) * 100).fillna(0)
	return matriz


def graficar_heatmap_contactabilidad(matriz: pd.DataFrame):
	if matriz.empty:
		return None
 
	horas = sorted(matriz["hora_bin"].unique())
	fechas = sorted(matriz["Fecha"].unique())
 
	pivot_pct = matriz.pivot(index="hora_bin", columns="Fecha", values="pct_contactabilidad").reindex(index=horas, columns=fechas).fillna(0)
	pivot_gestiones = matriz.pivot(index="hora_bin", columns="Fecha", values="gestiones_hora").reindex(index=horas, columns=fechas).fillna(0)
 
	etiquetas_hora = [f"{h % 12 if h % 12 != 0 else 12}:00 {'AM' if h < 12 else 'PM'}" for h in horas]
 
	fig = go.Figure(
		data=go.Heatmap(
			z=pivot_pct.values,
			x=[str(f) for f in fechas],
			y=etiquetas_hora,
			customdata=pivot_gestiones.values,
			colorscale="Greens",
			zmin=0,
			zmax=100,
			hovertemplate="Fecha: %{x}<br>Hora: %{y}<br>Contactabilidad: %{z:.1f}%<br>Gestiones: %{customdata:.0f}<extra></extra>",
			colorbar=dict(title="% Contacto"),
		)
	)
	fig.update_layout(
		height=450,
		xaxis_title="Fecha",
		yaxis_title="Hora del día",
		yaxis=dict(autorange="reversed"),
		xaxis=dict(tickangle=-45, type="category"),
		margin=dict(l=60, r=20, t=30, b=80),
	)
	return fig


def construir_resumen_diario_mes(matriz_horaria_acuerdos: pd.DataFrame) -> pd.DataFrame:
	if matriz_horaria_acuerdos.empty:
		return pd.DataFrame(columns=["Fecha", "cantidad_acuerdos", "valor_acuerdos"])
	resumen = (
		matriz_horaria_acuerdos.groupby("Fecha", dropna=False)[["cantidad_acuerdos", "valor_acuerdos"]]
		.sum()
		.reset_index()
		.sort_values("Fecha")
	)
	return resumen
 
 
def graficar_combo_mensual(resumen_diario: pd.DataFrame):
	if resumen_diario.empty:
		return None
 
	fechas = pd.to_datetime(resumen_diario["Fecha"]).dt.strftime("%Y-%m-%d").tolist()
 
	fig = go.Figure()
	fig.add_trace(
		go.Bar(
			x=fechas,
			y=resumen_diario["cantidad_acuerdos"],
			name="Cantidad de acuerdos",
			yaxis="y1",
			marker_color="#4C78A8",
		)
	)
	fig.add_trace(
		go.Scatter(
			x=fechas,
			y=resumen_diario["valor_acuerdos"],
			name="Valor de acuerdos",
			yaxis="y2",
			mode="lines+markers",
			line=dict(color="#E45756"),
		)
	)
	fig.update_layout(
		height=450,
		xaxis=dict(title="Fecha", tickangle=-45, type="category"),
		yaxis=dict(title="Cantidad de acuerdos"),
		yaxis2=dict(title="Valor de acuerdos", overlaying="y", side="right"),
		legend=dict(orientation="h", y=1.1),
		margin=dict(l=60, r=60, t=40, b=80),
	)
	return fig

def construir_resumen_mensual_promesa(base_filtrada: pd.DataFrame) -> pd.DataFrame:
	base = base_filtrada.copy()
	base["Cuenta"] = base["Cuenta"].astype("string").str.strip()
	base.loc[base["Cuenta"].isin(["", "<NA>", "nan", "None"]), "Cuenta"] = pd.NA
 
	perfiles_promesas = {"promesa de pago", "promesa de pago con descuento", "promesa con tercero"}
 
	if "ultimo_perfil_cliente" not in base.columns or "FechaPromesa" not in base.columns:
		return pd.DataFrame(columns=["Fecha", "cantidad_acuerdos", "valor_acuerdos"])
 
	perfil_norm = base["ultimo_perfil_cliente"].astype("string").str.strip().str.lower()
	mask_promesas = perfil_norm.isin(perfiles_promesas)
 
	col_valorpromesa = "valorpromesa" if "valorpromesa" in base.columns else "valor_promesa" if "valor_promesa" in base.columns else None
 
	base_promesas = base.loc[mask_promesas].dropna(subset=["Cuenta", "FechaPromesa"]).copy()
 
	cantidad = (
		base_promesas.groupby("FechaPromesa", dropna=False)["Cuenta"]
		.nunique()
		.reset_index(name="cantidad_acuerdos")
	)
 
	if col_valorpromesa:
		base_promesas[col_valorpromesa] = pd.to_numeric(base_promesas[col_valorpromesa], errors="coerce")
		base_con_valor = base_promesas.dropna(subset=[col_valorpromesa])
		if not base_con_valor.empty:
			idx_min = base_con_valor.groupby(["Cuenta", "FechaPromesa"])[col_valorpromesa].idxmin()
			filas_min = base_con_valor.loc[idx_min]
			valor = (
				filas_min.groupby("FechaPromesa", dropna=False)[col_valorpromesa]
				.sum(min_count=1)
				.reset_index(name="valor_acuerdos")
			)
		else:
			valor = pd.DataFrame(columns=["FechaPromesa", "valor_acuerdos"])
	else:
		valor = pd.DataFrame(columns=["FechaPromesa", "valor_acuerdos"])
 
	resumen = cantidad.merge(valor, on="FechaPromesa", how="outer").fillna(0)
	resumen["cantidad_acuerdos"] = resumen["cantidad_acuerdos"].astype(int)
	resumen = resumen.rename(columns={"FechaPromesa": "Fecha"}).sort_values("Fecha")
	return resumen


# ── Sección de Actualización de Datos (Mantenida en Sidebar) ──────────────
with st.sidebar.expander("🔄 Actualizar desde Carpeta Local", expanded=False):
    carpetas_texto = st.text_area(
        "Carpetas Gestiones (una por línea)",
        value="\n".join(DEFAULT_CARPETAS),
        key="carpetas_gestiones_input",	
        height=80,
    )
    carpetas_lista = [c.strip() for c in carpetas_texto.splitlines() if c.strip()]
    forzar_reimport = st.checkbox("Reimportar todo", value=False, key="chk_forzar_etl")
    if st.button("Recargar Gestiones", key="btn_recargar_db", use_container_width=True):
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

json_catalogo = "asesores_catalogo.json"

# ── Cargar datos desde SQLite ────────────────────────────────────────────
if not Path(_DB_PATH).exists():
	st.error(
		"No se encontro la base de datos **gestiones.db**.\n\n"
		"Utiliza la sección **'🔄 Actualizar Base de Datos'** en la barra lateral para procesar los archivos de gestiones."
	)
	st.stop()

df_raw = cargar_desde_sqlite(_DB_PATH, _firma_db(_DB_PATH))
if df_raw.empty:
	st.warning("La base de datos esta vacia. Utiliza el botón en la barra lateral para recargar las gestiones.")
	st.stop()


# Normalizar Fecha
df_raw["Fecha"] = pd.to_datetime(df_raw["Fecha"], errors="coerce").dt.normalize()

firma_catalogo = obtener_firma_archivo(json_catalogo)
catalogo = cargar_catalogo(json_catalogo, firma_catalogo)
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


# ── Sección de Filtros (Movida a la Pantalla Principal) ──────────────────
st.markdown("### 🔍 Filtros")
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

st.markdown(_render_kpi_row([
	{"label": "Total cuentas gestionadas",       "value": f"{total_cuentas_gestionadas:,}".replace(",", "."),             "icon": "📋", "color": "#4e9af1"},
	{"label": "Total clientes gestionados",       "value": f"{total_clientes_gestionados:,}".replace(",", "."),           "icon": "👥", "color": "#4ecdc4"},
	{"label": "Promedio cuentas x asesor",        "value": f"{promedio_cuentas_gestionadas_x_asesor_kpi:,}".replace(",", "."), "icon": "📊", "color": "#a78bfa"},
	{"label": "Promedio cuentas unicas x asesor", "value": f"{promedio_cuentas_unicas_x_asesor_kpi:,}".replace(",", "."),  "icon": "🔢", "color": "#818cf8"},
]), unsafe_allow_html=True)

st.markdown(_render_kpi_row([
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

col1, col2, col3, col4, col5, col6=st.columns(6)
with col1:
	st.image("scripts/image/Elite_H_color.png", width=300)
with col6:
	st.image("scripts/image/logo_claro.png", width=200)

st.markdown(
	f"<h3 style='text-align: center; margin-top: 15px; margin-bottom: 15px;'>📊 Productividad x Asesor - Campaña CLARO &nbsp;&nbsp;·&nbsp;&nbsp; Actualizado: {_hora_actualiz}</h3>",
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
st.markdown(_render_matriz_html(matriz_mostrar_consolidado), unsafe_allow_html=True)

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
	st.markdown(_render_matriz_html(matriz_mostrar_diario), unsafe_allow_html=True)

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
		st.plotly_chart(fig_acuerdos, use_container_width=True)
	else:
		st.info("No hay acuerdos para los filtros seleccionados.")

with col_hm2:
	st.markdown("**Contactabilidad por hora del día**")
	fig_contacto = graficar_heatmap_contactabilidad(matriz_horaria_contacto)
	if fig_contacto is not None:
		st.plotly_chart(fig_contacto, use_container_width=True)
	else:
		st.info("No hay gestiones para los filtros seleccionados.")

st.divider()
st.markdown("<h3 style='text-align: center; margin-top: 20px; margin-bottom: 15px;'>📈 Comportamiento Mensual de Acuerdos</h3>", unsafe_allow_html=True)

resumen_diario_mes = construir_resumen_mensual_promesa(base)
fig_mensual = graficar_combo_mensual(resumen_diario_mes)
if fig_mensual is not None:
	st.plotly_chart(fig_mensual, use_container_width=True)
else:
	st.info("No hay acuerdos para los filtros seleccionados.")
