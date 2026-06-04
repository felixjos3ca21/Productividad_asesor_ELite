import json
from pathlib import Path

import pandas as pd
import streamlit as st


st.set_page_config(page_title="Elite Abogados BPO - Productividad", layout="wide")
st.title("Productividad Asesores")
st.caption("Lectura de carpeta, transformaciones y matriz dinamica por filtros")


def leer_csv_robusto(path_csv: Path) -> pd.DataFrame:
	encodings = ["utf-8", "utf-8-sig", "cp1252", "latin-1"]
	separadores = [None, ";", ",", "\t", "|"]
	ultimo_error = None

	for enc in encodings:
		for sep in separadores:
			try:
				return pd.read_csv(
					path_csv,
					encoding=enc,
					sep=sep,
					engine="python",
					on_bad_lines="skip",
				)
			except Exception as e:
				ultimo_error = e

	raise RuntimeError(f"No se pudo leer CSV: {ultimo_error}")


@st.cache_data(show_spinner=True)
def leer_carpeta_tabular(carpeta_texto: str, firma_archivos: tuple):
	carpeta = Path(carpeta_texto)
	if not carpeta.exists() or not carpeta.is_dir():
		return pd.DataFrame(), pd.DataFrame()

	extensiones = {".csv", ".xlsx", ".xls", ".json", ".parquet"}
	archivos = sorted([p for p in carpeta.rglob("*") if p.is_file() and p.suffix.lower() in extensiones])

	dfs = []
	omitidos = []

	for archivo in archivos:
		try:
			sufijo = archivo.suffix.lower()
			if sufijo == ".csv":
				tmp = leer_csv_robusto(archivo)
			elif sufijo in {".xlsx", ".xls"}:
				tmp = pd.read_excel(archivo)
			elif sufijo == ".json":
				tmp = pd.read_json(archivo)
			elif sufijo == ".parquet":
				tmp = pd.read_parquet(archivo)
			else:
				continue

			if tmp is None or tmp.empty:
				omitidos.append((archivo.name, "DataFrame vacio"))
				continue

			tmp["origen_archivo"] = archivo.relative_to(carpeta).as_posix()
			dfs.append(tmp)
		except Exception as e:
			omitidos.append((archivo.name, str(e)))

	if not dfs:
		return pd.DataFrame(), pd.DataFrame(omitidos, columns=["archivo", "error"])

	df = pd.concat(dfs, ignore_index=True, sort=False)
	return df, pd.DataFrame(omitidos, columns=["archivo", "error"])


def obtener_firma_carpeta(carpeta_texto: str) -> tuple:
	carpeta = Path(carpeta_texto)
	if not carpeta.exists() or not carpeta.is_dir():
		return tuple()

	extensiones = {".csv", ".xlsx", ".xls", ".json", ".parquet"}
	firma = []
	for p in sorted([x for x in carpeta.rglob("*") if x.is_file() and x.suffix.lower() in extensiones]):
		stat = p.stat()
		firma.append((p.relative_to(carpeta).as_posix(), stat.st_mtime_ns, stat.st_size))

	return tuple(firma)


def obtener_firma_archivo(path_texto: str) -> tuple:
	path = Path(path_texto)
	if not path.exists() or not path.is_file():
		return tuple()
	stat = path.stat()
	return (str(path.resolve()), stat.st_mtime_ns, stat.st_size)


def primera_columna(df_base: pd.DataFrame, candidatas: list[str]):
	for c in candidatas:
		if c in df_base.columns:
			return c
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
	"""Soporta dos formatos:
	1) Clasico: {"usuario": {"Nombre_Asesor": "...", "Campo": "..."}}
	2) Con vigencias: {"usuario": {"vigencias": [{"desde": "YYYY-MM-DD", "hasta": "YYYY-MM-DD|None", "Nombre_Asesor": "...", "Campo": "..."}]}}
	"""
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
		# Si no hay fecha, prioriza vigencias abiertas y luego la mas reciente.
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
	resumen_gestiones = base.groupby(col_asesor, dropna=False)["llave_gestion_unica"].nunique().reset_index(name="gestiones_unicas")
	resumen_clientes = (
		base.groupby(col_asesor, dropna=False)["Identificacion"].nunique(dropna=True).reset_index(name="clientes_Gestionados")
	)

	perfiles_contacto_directo = {
		"pago parcial",
		"contesta y cuelga",
		"ya pago",
		"promesa de pago",
		"renuente",
		"llamar luego",
		"no hubo acuerdo",
		"colgo",
		"voluntad de pago",
		"promesa de pago con descuento",
		"no es el encargado del pago",
		"promesa con tercero",
		"dificultad de pago",
		"pago no abonado",
		"reclamacion",
		"recordatorio",
		"encargado renuente",
		"promesa whatsapp",
		"abono",
		"al dia",
	}
	perfiles_contacto_indirecto = {
		"equivocado",
		"mensaje con tercero",
		"tercero no conoce al titular",
		"tercero no toma mensaje",
		"fallecio",
	}
	perfiles_no_contacto = {"no contesta", "mensaje en buzon", "no contacto", "ilocalizado"}
	perfiles_promesas = {"promesa de pago", "promesa de pago con descuento", "promesa con tercero"}

	if "ultimo_perfil_cliente" in base.columns:
		perfil_norm = base["ultimo_perfil_cliente"].astype("string").str.strip().str.lower()
		mask_directo = perfil_norm.isin(perfiles_contacto_directo)
		mask_indirecto = perfil_norm.isin(perfiles_contacto_indirecto)
		mask_no_contacto = perfil_norm.isin(perfiles_no_contacto)
		mask_promesas = perfil_norm.isin(perfiles_promesas)

		resumen_contacto_directo = (
			base.loc[mask_directo].groupby(col_asesor, dropna=False)["Cuenta"].nunique(dropna=True).reset_index(name="contacto_directo")
		)
		resumen_contacto_indirecto = (
			base.loc[mask_indirecto]
			.groupby(col_asesor, dropna=False)["Cuenta"]
			.nunique(dropna=True)
			.reset_index(name="contacto_indirecto")
		)
		resumen_no_contacto = (
			base.loc[mask_no_contacto]
			.groupby(col_asesor, dropna=False)["Cuenta"]
			.nunique(dropna=True)
			.reset_index(name="no_contacto")
		)
		resumen_promesas = (
			base.loc[mask_promesas].groupby(col_asesor, dropna=False)["Cuenta"].nunique(dropna=True).reset_index(name="Promesas")
		)
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
		"gestiones_unicas",
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

	return resumen.sort_values(["gestiones_unicas", "clientes_Gestionados"], ascending=False).reset_index(drop=True)


def calcular_deberia_llevar(base_dia: pd.DataFrame, resumen_diario: pd.DataFrame, col_asesor: str, fecha_sel) -> pd.DataFrame:
	if "Hora" not in base_dia.columns:
		salida = resumen_diario.copy()
		salida["deberia_llevar"] = 0.0
		return salida

	base_horas = base_dia[[col_asesor, "Hora"]].copy()
	base_horas["Hora"] = pd.to_timedelta(base_horas["Hora"].astype("string"), errors="coerce")
	base_horas = base_horas.dropna(subset=["Hora"])

	if base_horas.empty:
		salida = resumen_diario.copy()
		salida["deberia_llevar"] = 0.0
		return salida

	primera_hora_asesor = base_horas.groupby(col_asesor, dropna=False)["Hora"].min()

	fecha_reporte = pd.to_datetime(fecha_sel).normalize()
	hoy = pd.Timestamp.now().normalize()
	if fecha_reporte == hoy:
		agora = pd.Timestamp.now()
		hora_corte = pd.to_timedelta(f"{agora.hour:02d}:{agora.minute:02d}:{agora.second:02d}")
	else:
		hora_corte = base_horas["Hora"].max()

	# Horas productivas = tiempo transcurrido - cruce con almuerzo (12:00 a 13:00).
	total_transcurrido = (hora_corte - primera_hora_asesor).clip(lower=pd.Timedelta(0))
	inicio_almuerzo = pd.to_timedelta("12:00:00")
	fin_almuerzo = pd.to_timedelta("13:00:00")

	if hora_corte <= inicio_almuerzo:
		cruce_almuerzo = pd.Series(pd.Timedelta(0), index=primera_hora_asesor.index)
	else:
		fin_cruce = min(hora_corte, fin_almuerzo)
		inicio_cruce = primera_hora_asesor.where(primera_hora_asesor > inicio_almuerzo, inicio_almuerzo)
		cruce_almuerzo = (fin_cruce - inicio_cruce).clip(lower=pd.Timedelta(0))

	horas_productivas = (total_transcurrido - cruce_almuerzo).clip(lower=pd.Timedelta(0))
	deberia_llevar = (horas_productivas.dt.total_seconds() / 3600.0) * 25.0
	deberia_llevar = deberia_llevar.clip(lower=0)
	deberia_llevar = (deberia_llevar / 5.0).round() * 5.0

	tmp = deberia_llevar.reset_index(name="deberia_llevar")
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


st.sidebar.title("Filtros")

# Configuracion fija de origen (sin controles en sidebar)
carpeta_fuente = r"C:\Users\felix.contreras\Desktop\Gestiones"
json_catalogo = "asesores_catalogo.json"

firma_archivos = obtener_firma_carpeta(carpeta_fuente)
df_raw, df_omitidos = leer_carpeta_tabular(carpeta_fuente, firma_archivos)
if df_raw.empty:
	st.warning("No se pudieron cargar archivos tabulares desde la carpeta indicada.")
	if not df_omitidos.empty:
		st.dataframe(df_omitidos, use_container_width=True)
	st.stop()

df_proc = transformar_df(df_raw)
firma_catalogo = obtener_firma_archivo(json_catalogo)
catalogo = cargar_catalogo(json_catalogo, firma_catalogo)
df_proc = aplicar_homologacion(df_proc, catalogo)

if "Fecha" not in df_proc.columns:
	st.error("No existe la columna Fecha despues de las transformaciones.")
	st.stop()

fechas_validas = sorted(df_proc["Fecha"].dropna().unique())
if not fechas_validas:
	st.error("No hay fechas validas para filtrar.")
	st.stop()

fecha_sel = st.sidebar.date_input("Dia", value=pd.to_datetime(fechas_validas[-1]).date())

campos_disponibles = sorted(df_proc.get("Campo", pd.Series(dtype="string")).dropna().astype(str).unique().tolist())
campos_sel = st.sidebar.multiselect("Campo", options=campos_disponibles)

col_asesor = "Nombre_Asesor" if "Nombre_Asesor" in df_proc.columns else "asesor_gestion"
asesores_disponibles = sorted(df_proc[col_asesor].dropna().astype(str).unique().tolist())
asesores_sel = st.sidebar.multiselect("Asesor", options=asesores_disponibles)

base = df_proc[df_proc["Fecha"] == pd.to_datetime(fecha_sel).normalize()].copy()
if campos_sel and "Campo" in base.columns:
	base = base[base["Campo"].isin(campos_sel)]
if asesores_sel:
	base = base[base[col_asesor].isin(asesores_sel)]

base, filas_duplicadas_removidas = deduplicar_por_llave_negocio(base, col_asesor)

if base.empty:
	st.info("No hay datos para los filtros seleccionados.")
	st.stop()

resumen_diario = construir_resumen_por_asesor(base, col_asesor)
resumen_diario = calcular_deberia_llevar(base, resumen_diario, col_asesor, fecha_sel)

# Medidas para tarjetas KPI (dinamicas segun filtros)
total_gestiones = int(resumen_diario["gestiones_unicas"].sum())

if "Identificacion" in base.columns:
	ids_limpios = base["Identificacion"].astype("string").str.strip()
	ids_limpios = ids_limpios.mask(ids_limpios.isin(["", "<NA>", "nan", "None"]), pd.NA)
	total_clientes_gestionados = int(ids_limpios.nunique(dropna=True))
else:
	total_clientes_gestionados = int(resumen_diario["clientes_Gestionados"].sum())

asesores_en_vista = max(int(resumen_diario[col_asesor].nunique(dropna=True)), 1)
promedio_gestiones_x_asesor = total_gestiones / asesores_en_vista
promedio_cuentas_unicas_x_asesor = float(resumen_diario["Gest_cuentas"].mean()) if not resumen_diario.empty else 0.0

col_kpi_1, col_kpi_2, col_kpi_3, col_kpi_4 = st.columns(4)
col_kpi_1.metric("Total gestiones", f"{total_gestiones:,}".replace(",", "."))
col_kpi_2.metric("Total clientes gestionados", f"{total_clientes_gestionados:,}".replace(",", "."))
col_kpi_3.metric("Promedio gestiones x asesor", f"{promedio_gestiones_x_asesor:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
col_kpi_4.metric("Promedio cuentas unicas x asesor", f"{promedio_cuentas_unicas_x_asesor:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

cantidad_promesas = int(resumen_diario["Promesas"].sum()) if "Promesas" in resumen_diario.columns else 0
total_valor_promesas = float(resumen_diario["valor_promesa"].sum()) if "valor_promesa" in resumen_diario.columns else 0.0
promedio_promesas = float(resumen_diario["Promesas"].mean()) if "Promesas" in resumen_diario.columns and not resumen_diario.empty else 0.0

col_kpi_5, col_kpi_6, col_kpi_7 = st.columns(3)
col_kpi_5.metric("Cantidad promesas", f"{cantidad_promesas:,}".replace(",", "."))
col_kpi_6.metric("Total valor promesas", formato_moneda(total_valor_promesas))
col_kpi_7.metric("Promedio promesas", f"{promedio_promesas:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

st.subheader("Matriz de Productividad")

matriz_ui = resumen_diario.copy()

# Semaforo de gestion contra promedio de asesores en vista
def icono_semaforo_gestion(v: int, promedio: float) -> str:
	if v < promedio:
		return "🔴"
	if abs(v - promedio) < 1e-9:
		return "🟡"
	return "🟢"

matriz_ui["gestiones_unicas"] = matriz_ui["gestiones_unicas"].map(
	lambda v: f"{icono_semaforo_gestion(int(v), promedio_gestiones_x_asesor)} {int(v):,}".replace(",", ".")
)

min_valor, max_valor = resumen_diario["valor_promesa"].min(), resumen_diario["valor_promesa"].max()
matriz_ui["valor_promesa"] = matriz_ui["valor_promesa"].map(
	lambda v: f"{barra_azul_monto(v, min_valor, max_valor)} {formato_moneda(v)}"
)

min_contact, max_contact = resumen_diario["%_contactabilidad"].min(), resumen_diario["%_contactabilidad"].max()
min_conv, max_conv = resumen_diario["%_Conversion"].min(), resumen_diario["%_Conversion"].max()

matriz_ui["%_contactabilidad"] = matriz_ui["%_contactabilidad"].map(
	lambda v: f"{icono_pct_relativo(v, min_contact, max_contact)} {v:.2f}%"
)
matriz_ui["%_Conversion"] = matriz_ui["%_Conversion"].map(
	lambda v: f"{icono_pct_relativo(v, min_conv, max_conv)} {v:.2f}%"
)
matriz_ui["deberia_llevar"] = matriz_ui["deberia_llevar"].map(
	lambda v: f"{int(round(v)):,.0f}".replace(",", ".")
)

columnas_vista = [
	col_asesor,
	"gestiones_unicas",
	"deberia_llevar",
	"Gest_cuentas",
	"clientes_Gestionados",
	"contacto_directo",
	"contacto_indirecto",
	"no_contacto",
	"Promesas",
	"valor_promesa",
	"%_contactabilidad",
	"%_Conversion",
]

matriz_mostrar = matriz_ui[columnas_vista].rename(
	columns={
		col_asesor: "Asesor",
		"gestiones_unicas": "Gestiones",
		"Gest_cuentas": "Cuentas\nunicas",
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
)

ajustar_ancho = st.toggle("Ajustar al ancho de la pagina", value=False)

alto_tabla = 560
alto_tabla = min(1400, max(560, 35 * (len(matriz_mostrar) + 1)))

st.dataframe(
	matriz_mostrar,
	use_container_width=ajustar_ancho,
	height=alto_tabla,
	hide_index=True,
	column_config={
		"Asesor": st.column_config.TextColumn("Asesor"),
		"Gestiones": st.column_config.TextColumn("Gestiones"),
		"Cuentas\nunicas": st.column_config.NumberColumn("Cuentas\nunicas"),
		"Clientes\ngestionados": st.column_config.NumberColumn("Clientes\ngestionados"),
		"Contacto\ndirecto": st.column_config.NumberColumn("Contacto\ndirecto"),
		"Contacto\nindirecto": st.column_config.NumberColumn("Contacto\nindirecto"),
		"No\ncontacto": st.column_config.NumberColumn("No\ncontacto"),
		"Promesas": st.column_config.NumberColumn("Promesas"),
		"Deberia\nllevar": st.column_config.TextColumn("Deberia\nllevar"),
		"Valor\npromesa": st.column_config.TextColumn("Valor\npromesa"),
		"%\nContactabilidad": st.column_config.TextColumn("%\nContactabilidad"),
		"%\nConversion": st.column_config.TextColumn("%\nConversion"),
	},
)

csv_export = resumen_diario.to_csv(index=False).encode("utf-8")
st.download_button(
	label="Descargar resumen filtrado (CSV)",
	data=csv_export,
	file_name=f"resumen_productividad_{fecha_sel}.csv",
	mime="text/csv",
)

with st.expander("Ver archivos omitidos"):
	if df_omitidos.empty:
		st.write("Sin archivos omitidos.")
	else:
		st.dataframe(df_omitidos, use_container_width=True, hide_index=True)

with st.expander("Ver base filtrada (todas las columnas)"):
	st.dataframe(base, use_container_width=False, hide_index=True, height=520)

