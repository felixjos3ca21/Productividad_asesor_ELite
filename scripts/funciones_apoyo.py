# scripts/funciones_apoyo.py
"""
Funciones auxiliares compartidas por la página de Productividad
(secciones Productividad y Adherencia).
"""
import json
import sqlite3
from pathlib import Path
from datetime import datetime
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import plotly.express as px
from st_aggrid import AgGrid, JsCode
from scripts.importar_logueo import reset_malla_turno, reset_reporte_logueo

# ===========================================================================
# Carga de datos / firmas de archivo (cache)
# ===========================================================================

def obtener_firma_archivo(path_texto: str) -> tuple:
    path = Path(path_texto)
    if not path.exists() or not path.is_file():
        return tuple()
    stat = path.stat()
    return (str(path.resolve()), stat.st_mtime_ns, stat.st_size)


def firma_db(db_path: str) -> tuple:
    """Firma del archivo gestiones.db para invalidar cache cuando cambia."""
    return obtener_firma_archivo(db_path)


@st.cache_data(show_spinner="Cargando gestiones desde base de datos...", ttl=None)
def cargar_desde_sqlite(db_path: str, firma_db_val: tuple) -> pd.DataFrame:
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


@st.cache_data(show_spinner=False)
def cargar_catalogo(path_texto: str, firma_catalogo: tuple) -> dict:
    path = Path(path_texto)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8-sig"))
    return {}


# ===========================================================================
# Utilidades de columnas / formato
# ===========================================================================

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


def formato_moneda(v: float) -> str:
    return f"$ {v:,.0f}".replace(",", ".")


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


# ===========================================================================
# Catálogo de asesores / homologación
# ===========================================================================

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


# ===========================================================================
# Deduplicación y resumen de productividad
# ===========================================================================

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
        "cuentas_gestionadas", "Gest_cuentas", "clientes_Gestionados",
        "contacto_directo", "contacto_indirecto", "no_contacto", "Promesas",
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


# ===========================================================================
# Render HTML (KPIs / matriz)
# ===========================================================================

def kpi_card(label: str, value: str, icon: str, color: str) -> str:
    return (
        f'<div class="kpi-card" style="--accent:{color}">'
        f'<span class="kpi-icon">{icon}</span>'
        f'<span class="kpi-label">{label}</span>'
        f'<span class="kpi-value">{value}</span>'
        f'</div>'
    )


def render_kpi_row(cards: list) -> str:
    items = "".join(kpi_card(**c) for c in cards)
    return f'<div class="kpi-row">{items}</div>'


def render_matriz_html(df: pd.DataFrame) -> str:
    def _e(s: str) -> str:
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    encabezados = "".join(
        f'<th style="font-size:1.05rem !important;">{_e(c)}</th>' for c in df.columns
    )
    filas = []
    for _, row in df.iterrows():
        celdas = "".join(
            f'<td style="font-size:0.95rem !important;">{_e(v)}</td>' for v in row.values
        )
        filas.append(f"<tr>{celdas}</tr>")
    cuerpo = "".join(filas)
    return (
        '<div class="mat-wrap">'
        f'<table class="mat-tbl"><thead><tr>{encabezados}</tr></thead>'
        f'<tbody>{cuerpo}</tbody></table>'
        '</div>'
    )


# ===========================================================================
# Heatmaps horarios (acuerdos / contactabilidad)
# ===========================================================================

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


# ===========================================================================
# Vista mensual de promesas
# ===========================================================================

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

# ===========================================================================
# Sección Adherencia (UI completa)
# ===========================================================================

# Tiempo permitido (en minutos) por tipo de almuerzo.
LIMITES_ALMUERZO_MIN = {
    "Almuerzo_1Hora_Min": ("Almuerzo 1 Hora", 60),
    "Almuerzo_40Min_Min": ("Almuerzo 40 Min", 40),
    "Almuerzo_30Min_Min": ("Almuerzo 30 Min", 30),
}

# Tiempo permitido (en minutos) por tipo de pausa.
LIMITES_PAUSAS_MIN = {
    "Bano_Min": ("Baño", 5),
    "Break10_Min": ("Break 10", 10),
    "Break15_Min": ("Break 15", 15),
    "PausasActivas_Min": ("Pausas Activas", 5),
}


def _fmt_hhmmss_min(minutos: float) -> str:
    minutos = max(minutos, 0.0)
    total_seg = int(round(minutos * 60))
    h, resto = divmod(total_seg, 3600)
    m, s = divmod(resto, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def construir_reporte_adherencia_general(
    df_malla: pd.DataFrame,
    df_log: pd.DataFrame,
    col_asesor: str = "Nombre_Asesor",
    tolerancia_seg: int = 20,
) -> pd.DataFrame:
    """Reporte único de adherencia: entrada/salida real vs. programado,
    cumplimiento de almuerzo y cumplimiento de pausas (Baño/Breaks/Pausas
    Activas), todo en filas tipo 'Concepto' con el tiempo que debe el asesor
    (columna Deuda_Min) para poder totalizar por asesor en el rango."""
    tolerancia = pd.to_timedelta(f"{tolerancia_seg}s")

    def _fmt_td(td):
        if pd.isna(td):
            return ""
        total_seg = int(td.total_seconds())
        h, resto = divmod(total_seg, 3600)
        m, s = divmod(resto, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    filas = []

    # --- Entrada / Salida real vs. programado ---
    if not df_malla.empty and not df_log.empty:
        malla = df_malla.groupby([col_asesor, "Fecha"], as_index=False).agg(
            Hora_Entrada=("Hora_Entrada", "first"),
            Hora_Salida=("Hora_Salida", "first"),
        )
        log_es = df_log.groupby([col_asesor, "Fecha"], as_index=False).agg(
            Primera_Entrada=("Primera_Entrada", "first"),
            Ultima_Salida=("Ultima_Salida", "first"),
        )
        cruce = malla.merge(log_es, on=[col_asesor, "Fecha"], how="left")

        def _td(col):
            return pd.to_timedelta(cruce[col].astype("string"), errors="coerce")

        ent_prog, ent_real = _td("Hora_Entrada"), _td("Primera_Entrada")
        sal_prog, sal_real = _td("Hora_Salida"), _td("Ultima_Salida")

        for i in range(len(cruce)):
            asesor, fecha = cruce[col_asesor].iat[i], cruce["Fecha"].iat[i]
            p_e, r_e = ent_prog.iat[i], ent_real.iat[i]
            p_s, r_s = sal_prog.iat[i], sal_real.iat[i]

            if pd.isna(r_e):
                estado, deuda = "⚠️ Sin registro", 0.0
            else:
                diff = r_e - p_e
                if diff <= tolerancia:
                    estado, deuda = "✅ A tiempo", 0.0
                else:
                    deuda = diff.total_seconds() / 60.0
                    estado = f"🔴 Tarde +{_fmt_hhmmss_min(deuda)}"
            filas.append({
                "Asesor": asesor, "Fecha": fecha, "Concepto": "Llegada",
                "Real": _fmt_td(r_e), "Permitido": _fmt_td(p_e),
                "Estado": estado, "Deuda_Min": deuda,
            })

            if pd.isna(r_s):
                estado, deuda = "⚠️ Sin registro", 0.0
            else:
                diff = p_s - r_s
                if diff <= tolerancia:
                    estado, deuda = "✅ Cumplió", 0.0
                else:
                    deuda = diff.total_seconds() / 60.0
                    estado = f"🔴 Se fue -{_fmt_hhmmss_min(deuda)}"
            filas.append({
                "Asesor": asesor, "Fecha": fecha, "Concepto": "Salida",
                "Real": _fmt_td(r_s), "Permitido": _fmt_td(p_s),
                "Estado": estado, "Deuda_Min": deuda,
            })

    # --- Almuerzo y pausas: mismo criterio, exceso sobre el tiempo permitido ---
    limites_todos = {**LIMITES_ALMUERZO_MIN, **LIMITES_PAUSAS_MIN}
    cols_presentes = [c for c in limites_todos if c in df_log.columns]
    if not df_log.empty and cols_presentes:
        agg = {c: (c, "sum") for c in cols_presentes}
        log_cp = df_log.groupby([col_asesor, "Fecha"], as_index=False).agg(**agg)

        for _, row in log_cp.iterrows():
            for col in cols_presentes:
                etiqueta, limite_min = limites_todos[col]
                duracion_min = row.get(col) or 0.0
                if duracion_min <= 0:
                    continue
                limite_seg = limite_min * 60 + tolerancia_seg
                duracion_seg = duracion_min * 60
                if duracion_seg <= limite_seg:
                    estado, deuda = "✅ Cumplió", 0.0
                else:
                    deuda = (duracion_seg - limite_seg) / 60.0
                    estado = f"🔴 Excedió +{_fmt_hhmmss_min(deuda)}"
                filas.append({
                    "Asesor": row[col_asesor], "Fecha": row["Fecha"], "Concepto": etiqueta,
                    "Real": _fmt_hhmmss_min(duracion_min), "Permitido": _fmt_hhmmss_min(limite_min),
                    "Estado": estado, "Deuda_Min": deuda,
                })

    resultado = pd.DataFrame(filas)
    if resultado.empty:
        return resultado

    resultado["Fecha"] = pd.to_datetime(resultado["Fecha"]).dt.strftime("%d/%m/%Y")

    # --- Novedad de Malla de Turno (texto libre, ~80 caracteres), por asesor/día ---
    resultado["Novedad"] = ""
    if not df_malla.empty and "Novedad" in df_malla.columns:
        novedades = df_malla.groupby([col_asesor, "Fecha"], as_index=False).agg(
            Novedad=("Novedad", lambda s: next((str(v) for v in s if str(v).strip() and str(v).lower() != "nan"), ""))
        )
        novedades["Fecha"] = pd.to_datetime(novedades["Fecha"]).dt.strftime("%d/%m/%Y")
        novedades = novedades.rename(columns={col_asesor: "Asesor"})
        resultado = resultado.drop(columns=["Novedad"]).merge(novedades, on=["Asesor", "Fecha"], how="left")
        resultado["Novedad"] = resultado["Novedad"].fillna("")

    return resultado.sort_values(["Asesor", "Fecha"]).reset_index(drop=True)


def render_modulo_adherencia(db_path: str, catalogo: dict):
    st.markdown("## ⏱️ Adherencia - Claro")
    st.caption("Carga de Malla de Turnos (Programado) y Reporte Real ControlNext (Sucedido) para análisis de cumplimiento y tiempos en línea.")

    with st.expander("📥 Cargar Archivos de Adherencia (Turnos / ControlNext)", expanded=False):
        
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("##### 📅 Malla de Turno (Programado)")
            archivos_malla = st.file_uploader(
                "Subir Malla de Turno (Excel/CSV)",
                type=["csv", "xlsx", "xls"],
                accept_multiple_files=True,
                key="uploader_malla_adherencia",
            )
            if st.button("Guardar Malla de Turno", key="btn_proc_malla_adh"):
                if archivos_malla:
                    with st.spinner("Procesando y guardando malla de turno..."):
                        from scripts.importar_logueo import procesar_archivos_adherencia
                        res = procesar_archivos_adherencia(archivos_malla, db_path, catalogo, tipo="malla")
                        for r in res:
                            st.write(f"• **{r['archivo']}**: {r['estado']}")
                        st.cache_data.clear()
                        st.rerun()
                else:
                    st.warning("Selecciona al menos un archivo de Malla de Turno.")

        with c2:
            st.markdown("##### 📈 Reporte Real ControlNext (Sucedido)")
            archivos_logueo = st.file_uploader(
                "Subir Reporte Real ControlNext (CSV ; / Excel)",
                type=["csv", "xlsx", "xls"],
                accept_multiple_files=True,
                key="uploader_controlnext_adh",
            )
            if st.button("Guardar Reporte ControlNext", key="btn_proc_controlnext_adh"):
                if archivos_logueo:
                    with st.spinner("Procesando e importando reporte ControlNext..."):
                        from scripts.importar_logueo import procesar_archivos_adherencia
                        res = procesar_archivos_adherencia(archivos_logueo, db_path, catalogo, tipo="logueo")
                        for r in res:
                            st.write(f"• **{r['archivo']}**: {r['estado']}")
                        st.cache_data.clear()
                        st.rerun()
                else:
                    st.warning("Selecciona al menos un archivo de Reporte ControlNext.")

    with st.expander("⚠️ Reset de las Tablas de Adherencia", expanded=False):
        c_r1, c_r2 = st.columns(2)
        with c_r1:
                    st.markdown("**Resetear Malla de Turno**")
                    if "confirmar_reset_malla" not in st.session_state:
                        st.session_state["confirmar_reset_malla"] = False
        
                    if not st.session_state["confirmar_reset_malla"]:
                        if st.button("🗑️ Resetear Malla de Turno", key="btn_reset_malla"):
                            st.session_state["confirmar_reset_malla"] = True
                            st.rerun()
                    else:
                        st.warning("⚠️ Esto eliminará **todos** los registros de Malla de Turno. ¿Confirmas?")
                        col_si, col_no = st.columns(2)
                        with col_si:
                            if st.button("✅ Sí, eliminar todo", key="btn_reset_malla_confirmar"):
                                with st.spinner("Reseteando Malla de Turno..."):
                                    reset_malla_turno(db_path)
                                st.session_state["confirmar_reset_malla"] = False
                                st.cache_data.clear()
                                st.success("✅ Malla de Turno reseteada.")
                                st.rerun()
                        with col_no:
                            if st.button("❌ Cancelar", key="btn_reset_malla_cancelar"):
                                st.session_state["confirmar_reset_malla"] = False
                                st.rerun()
        
        with c_r2:
                    st.markdown("**Resetear Reporte ControlNext**")
                    if "confirmar_reset_logueo" not in st.session_state:
                        st.session_state["confirmar_reset_logueo"] = False
        
                    if not st.session_state["confirmar_reset_logueo"]:
                        if st.button("🗑️ Resetear Reporte ControlNext", key="btn_reset_logueo"):
                            st.session_state["confirmar_reset_logueo"] = True
                            st.rerun()
                    else:
                        st.warning("⚠️ Esto eliminará **todos** los registros del Reporte ControlNext. ¿Confirmas?")
                        col_si2, col_no2 = st.columns(2)
                        with col_si2:
                            if st.button("✅ Sí, eliminar todo", key="btn_reset_logueo_confirmar"):
                                with st.spinner("Reseteando Reporte ControlNext..."):
                                    reset_reporte_logueo(db_path)
                                st.session_state["confirmar_reset_logueo"] = False
                                st.cache_data.clear()
                                st.success("✅ Reporte ControlNext reseteado.")
                                st.rerun()
                        with col_no2:
                            if st.button("❌ Cancelar", key="btn_reset_logueo_cancelar"):
                                st.session_state["confirmar_reset_logueo"] = False
                                st.rerun()
    try:
        con = sqlite3.connect(db_path)
        df_log = pd.read_sql_query("SELECT * FROM reporte_logueo", con)
        df_malla = pd.read_sql_query("SELECT * FROM malla_turno", con)
        con.close()
    except Exception as e:
        st.error(f"Error al consultar base de datos: {e}")
        return

    if df_log.empty and df_malla.empty:
        st.info("No hay registros de Malla de Turnos ni Reporte ControlNext cargados todavía. Despliega la sección de carga superior para importar archivos.")
        return

    # ── Homologación de nombres vía catálogo (igual que en Productividad) ──
    if not df_log.empty:
        df_log["Fecha"] = pd.to_datetime(df_log["Fecha"], errors="coerce").dt.normalize()
    if not df_malla.empty:
        df_malla["Fecha"] = pd.to_datetime(df_malla["Fecha"], errors="coerce").dt.normalize()

    fechas_todas = []
    if not df_log.empty:
        fechas_todas.extend(df_log["Fecha"].dropna().unique())
    if not df_malla.empty:
        fechas_todas.extend(df_malla["Fecha"].dropna().unique())
    fechas_todas = sorted(list(set(fechas_todas)))

    if fechas_todas:
        min_f = pd.to_datetime(fechas_todas[0]).date()
        max_f = pd.to_datetime(fechas_todas[-1]).date()
    else:
        min_f = max_f = pd.Timestamp.now().date()

    hoy = pd.Timestamp.now().date()
    fecha_default = hoy if min_f <= hoy <= max_f else max_f
    st.markdown("### 🔍 Filtros")
    fl1, fl2 = st.columns(2)
    with fl1:
        rango_log = st.date_input(
            "Rango de Fechas", value=(fecha_default, fecha_default), min_value=min_f, max_value=max_f, key="rango_date_adh",
        )

    asesores_log = []
    if not df_log.empty and "Nombre_Asesor" in df_log.columns:
        asesores_log.extend(df_log["Nombre_Asesor"].dropna().unique())
    if not df_malla.empty and "Nombre_Asesor" in df_malla.columns:
        asesores_log.extend(df_malla["Nombre_Asesor"].dropna().unique())
    asesores_log = sorted(list(set(asesores_log)))

    with fl2:
        asesores_sel_log = st.multiselect("Asesor", options=asesores_log, key="asesores_sel_adh")

    if isinstance(rango_log, (tuple, list)):
        if len(rango_log) == 2:
            f_desde, f_hasta = rango_log
        elif len(rango_log) == 1:
            f_desde = f_hasta = rango_log[0]
        else:
            f_desde = f_hasta = max_f
    else:
        f_desde = f_hasta = rango_log

    f_desde_dt = pd.to_datetime(f_desde).normalize()
    f_hasta_dt = pd.to_datetime(f_hasta).normalize()

    if not df_log.empty:
        df_log_f = df_log[(df_log["Fecha"] >= f_desde_dt) & (df_log["Fecha"] <= f_hasta_dt)].copy()
        if asesores_sel_log:
            df_log_f = df_log_f[df_log_f["Nombre_Asesor"].isin(asesores_sel_log)]
    else:
        df_log_f = df_log

    if not df_malla.empty:
        df_malla_f = df_malla[(df_malla["Fecha"] >= f_desde_dt) & (df_malla["Fecha"] <= f_hasta_dt)].copy()
        if asesores_sel_log:
            df_malla_f = df_malla_f[df_malla_f["Nombre_Asesor"].isin(asesores_sel_log)]
    else:
        df_malla_f = df_malla

    st.divider()

    resumen_general = construir_reporte_adherencia_general(df_malla_f, df_log_f, col_asesor="Nombre_Asesor")

    if resumen_general.empty:
        st.info("No hay coincidencias entre Malla de Turno y ControlNext Real para los filtros seleccionados.")
        return

    #------------------------------------------------
    # Reporte Adherencia General (entrada/salida, almuerzo y pausas unificados)
    #-------------------------------------------------
    st.markdown("### 📋 Reporte Adherencia General")
    st.caption("Entrada/salida real vs. programado, cumplimiento de almuerzo y de pausas (Baño/Breaks/Pausas Activas) en una sola vista.")

    badge_cell_style = JsCode("""
    function(params) {
        if (!params.value) return {};
        if (params.value.indexOf('🔴') !== -1) {
            return {backgroundColor: '#fde8e9', color: '#990011', fontWeight: '600'};
        }
        if (params.value.indexOf('✅') !== -1) {
            return {backgroundColor: '#e6f9ef', color: '#0f9d58', fontWeight: '600'};
        }
        if (params.value.indexOf('⚠️') !== -1) {
            return {backgroundColor: '#fff8e1', color: '#b8860b', fontWeight: '600'};
        }
        return {};
    }
    """)

    custom_css_adh = {
        ".ag-header": {"background-color": "#990011 !important"},
        ".ag-header-cell-label": {"color": "white !important", "font-weight": "600"},
        ".ag-row-even": {"background-color": "rgba(255,255,255,0.85) !important"},
        ".ag-row-odd": {"background-color": "rgba(253,232,233,0.5) !important"},
    }

    # Se agrega, al final de las filas de cada asesor, una fila "TOTAL RANGO"
    # con la suma de todo lo que debe en el rango filtrado (mismo cuadro,
    # misma descarga: no se separa en una tabla aparte).
    detalle_cols = resumen_general[["Asesor", "Fecha", "Concepto", "Real", "Permitido", "Estado", "Novedad"]].copy()

    totales = (
        resumen_general.groupby("Asesor", as_index=False)["Deuda_Min"]
        .sum()
        .rename(columns={"Deuda_Min": "_total_min"})
    )
    fila_total = pd.DataFrame({
        "Asesor": totales["Asesor"],
        "Fecha": "",
        "Concepto": "TOTAL RANGO",
        "Real": "",
        "Permitido": "",
        "Estado": totales["_total_min"].map(
            lambda v: "✅ Sin deuda" if v <= 0 else f"🔴 Debe {_fmt_hhmmss_min(v)}"
        ),
        "Novedad": "",
    })

    detalle_cols["_orden"] = 0
    fila_total["_orden"] = 1
    tabla_final = pd.concat([detalle_cols, fila_total], ignore_index=True)
    tabla_final = tabla_final.sort_values(["Asesor", "_orden"], kind="stable").drop(columns=["_orden"]).reset_index(drop=True)

    grid_options_gen = {
        "defaultColDef": {"sortable": True, "filter": True, "resizable": True},
        "columnDefs": [
            {"field": "Asesor", "headerName": "Asesor", "pinned": "left", "minWidth": 170},
            {"field": "Fecha", "headerName": "Fecha", "minWidth": 110},
            {"field": "Concepto", "headerName": "Concepto", "minWidth": 150},
            {"field": "Real", "headerName": "Real", "minWidth": 120},
            {"field": "Permitido", "headerName": "Permitido", "minWidth": 120},
            {"field": "Estado", "headerName": "Estado", "cellStyle": badge_cell_style, "minWidth": 180},
            {"field": "Novedad", "headerName": "Novedad", "minWidth": 260, "wrapText": True, "autoHeight": True},
        ],
    }

    # La fila "TOTAL RANGO" de cada asesor se resalta para que no se pierda
    # en el scroll, quedando pegada justo debajo de las filas de ese asesor.
    get_row_style = JsCode("""
    function(params) {
        if (params.data && params.data.Concepto === 'TOTAL RANGO') {
            return {backgroundColor: '#fff3cd', fontWeight: '700', borderTop: '2px solid #990011'};
        }
        return {};
    }
    """)
    grid_options_gen["getRowStyle"] = get_row_style

    altura_fila = 34
    altura_header = 46
    altura_calculada = altura_header + altura_fila * len(tabla_final) + 10
    altura_calculada = min(max(altura_calculada, 200), 600)

    AgGrid(
        tabla_final,
        gridOptions=grid_options_gen,
        custom_css=custom_css_adh,
        allow_unsafe_jscode=True,
        fit_columns_on_grid_load=True,
        theme="alpine",
        height=altura_calculada,
        update_mode="NO_UPDATE",
        key="grid_adherencia_general",
    )
    st.caption(f"{resumen_general['Asesor'].nunique()} asesores · {len(tabla_final)} filas mostradas (incluye total por asesor)")

    csv_bytes_gen = tabla_final.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Descargar Reporte Adherencia General (CSV)",
        data=csv_bytes_gen,
        file_name=f"adherencia_general_{f_desde}_a_{f_hasta}.csv",
        mime="text/csv",
        key="btn_descargar_adherencia_general",
    )

# ===========================================================================
# Sección Pagos x Asesor (UI completa)
# ===========================================================================

@st.cache_data(show_spinner="Cargando pagos desde base de datos...", ttl=None)
def cargar_pagos_desde_sqlite(db_path: str, firma_db_val: tuple) -> pd.DataFrame:
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


def render_modulo_pagos_asesor(db_path: str):
    st.markdown("### 💰 Pagos x Asesor")
    col_f1, col_f2, col_f3, = st.columns(3)

    with col_f1:
        with st.expander("🧹 Limpieza de duplicados en pagos_x_asesor"):
            st.caption(
                "Elimina registros duplicados dejando solo el de clave_pago más alta "
            )
            confirmar_limpieza = st.checkbox(
                "Confirmo que quiero eliminar los duplicados de forma permanente",
                key="chk_confirmar_limpieza_pagos",
            )
            if st.button("Eliminar duplicados", key="btn_limpiar_pagos_duplicados", disabled=not confirmar_limpieza):
                con = sqlite3.connect(db_path)
                try:
                    cur = con.execute(
                        """
                        DELETE FROM pagos_x_asesor
                        WHERE clave_pago NOT IN (
                            SELECT MAX(clave_pago)
                            FROM pagos_x_asesor
                            GROUP BY cuenta, valor_pago, fecha_pago
                        )
                        """
                    )
                    con.commit()
                    filas_eliminadas = cur.rowcount
                finally:
                    con.close()
                st.cache_data.clear()
                st.success(f"Se eliminaron {filas_eliminadas} registros duplicados.")
                st.rerun()

    df_pagos = cargar_pagos_desde_sqlite(db_path, firma_db(db_path))

    if df_pagos.empty:
        st.info("Aun no hay datos en pagos_x_asesor. Usa el panel lateral para cargar archivos.")
        return

    df_pagos["valor_pago"] = pd.to_numeric(df_pagos["valor_pago"], errors="coerce")
    filas_sin_valor = df_pagos["valor_pago"].isna().sum()
    if filas_sin_valor:
        st.warning(f"{filas_sin_valor} filas tienen valor_pago no numerico y se excluyen de los totales.")

    # ── Filtros ──────────────────────────────────────────────────────────
    st.markdown("### 🔍 Filtros - Pagos")
    col_f1, col_f2, col_f3, col_f4, col_f5 = st.columns(5)

    fecha_min = df_pagos["fecha_pago"].min()
    fecha_max = df_pagos["fecha_pago"].max()
    with col_f1:
        rango_fecha = st.date_input(
            "Fecha de pago",
            value=(fecha_min, fecha_max) if pd.notna(fecha_min) else None,
            key="filtro_fecha_pago",
        )

    types_disponibles = sorted(df_pagos["customer_type"].dropna().unique().tolist()) if "customer_type" in df_pagos.columns else []
    with col_f2:
        types_sel = st.multiselect("Tipo de Cliente", types_disponibles, default=types_disponibles, key="filtro_customer_type")

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

    if types_sel and "customer_type" in base.columns:
        base = base[base["customer_type"].isin(types_sel)]
    if marcas_sel:
        base = base[base["marca"].isin(marcas_sel)]
    if asesores_sel:
        base = base[base["Nombre_Asesor"].isin(asesores_sel)]
    if tipificaciones_sel:
        base = base[base["mejorperfil"].isin(tipificaciones_sel)]

    if base.empty:
        st.info("No hay datos para los filtros seleccionados.")
        return

    st.divider()

    # ── KPIs (mismo estilo de tarjetas que Productividad/Adherencia) ──────
    total_pagado = base["valor_pago"].sum()
    cantidad_pagos = len(base)
    asesores_activos = base["Nombre_Asesor"].nunique(dropna=True)
    promedio_x_asesor = total_pagado / asesores_activos if asesores_activos else 0

    st.markdown(render_kpi_row([
        {"label": "Total pagado", "value": f"${total_pagado:,.0f}".replace(",", "."), "icon": "💵", "color": "#34d399"},
        {"label": "Cantidad de pagos", "value": f"{cantidad_pagos:,}".replace(",", "."), "icon": "🧾", "color": "#4e9af1"},
        {"label": "Asesores con pago", "value": f"{asesores_activos}", "icon": "👥", "color": "#a78bfa"},
        {"label": "Promedio x asesor", "value": f"${promedio_x_asesor:,.0f}".replace(",", "."), "icon": "📊", "color": "#fbbf24"},
    ]), unsafe_allow_html=True)

    st.divider()

    # ── Resumen por asesor ──────────────────────────────────────────────
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
        width="stretch",
        hide_index=True,
        column_config={
            "total_pagado": st.column_config.NumberColumn("Total pagado", format="$ %d"),
            "cantidad_pagos": st.column_config.NumberColumn("Cantidad de pagos", format="%d"),
        },
    )
    st.divider()

    # ── Pagos por día ───────────────────────────────────────────────────
    st.subheader("Pagos por día")

    base["dia_pago"] = base["fecha_pago"].dt.day
    col_color = "customer_type" if "customer_type" in base.columns else "Nombre_Asesor"
    pagos_diarios = (
        base.groupby(["dia_pago", col_color], as_index=False)
        .agg(total_dia=("valor_pago", "sum"))
    )

    fig = px.line(
        pagos_diarios,
        x="dia_pago",
        y="total_dia",
        color=col_color,
        markers=True,
        labels={"dia_pago": "Día", "total_dia": "Total pagado", col_color: "Tipo de Cliente"},
    )
    fig.update_layout(hovermode="x unified")
    st.plotly_chart(fig, width="stretch")

    resumen_mes = (
        base.groupby(base["fecha_pago"].dt.day)["valor_pago"]
        .sum()
        .reset_index()
        .rename(columns={"fecha_pago": "dia_pago"})
    )
    st.write(resumen_mes)
    st.write("Total del periodo filtrado:", resumen_mes["valor_pago"].sum())

    # ── Meta por asesor ─────────────────────────────────────────────────
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
    resumen_asesor["estado"] = resumen_asesor["valor_faltante"].apply(lambda v: "✅ Cumplida" if v >= 0 else "⏳ En curso")

    marcas_texto = ", ".join(marcas_sel) if marcas_sel else "Todas"
    types_texto = ", ".join(types_sel) if types_sel else "Todos"
    st.subheader(f"Resumen por asesor — Marca: {marcas_texto} | Tipo de Cliente: {types_texto}")

    resumen_asesor = resumen_asesor.sort_values("total_pagado", ascending=False).reset_index(drop=True)
    resumen_asesor["posicion"] = resumen_asesor.index + 1
    df_grid = resumen_asesor[
        ["posicion", "Nombre_Asesor", "total_pagado", "meta", "valor_faltante", "%_meta", "estado"]
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
        "defaultColDef": {"sortable": True, "filter": True, "resizable": True},
        "columnDefs": [
            {"field": "posicion", "headerName": "Posición", "pinned": "left"},
            {"field": "Nombre_Asesor", "headerName": "Asesor", "pinned": "left"},
            {"field": "total_pagado", "headerName": "Total pagado", "valueFormatter": money_formatter, "type": ["numericColumn"]},
            {"field": "meta", "headerName": "Meta", "valueFormatter": money_formatter, "type": ["numericColumn"]},
            {"field": "valor_faltante", "headerName": "Falta / Excedente", "valueFormatter": money_formatter, "type": ["numericColumn"]},
            {"field": "%_meta", "headerName": "Avance", "cellRenderer": progress_renderer, "type": ["numericColumn"]},
            {"field": "estado", "headerName": "Estado"},
        ],
    }

    # Tema CLARO (rojo) para que la grilla combine con el resto de la página
    custom_css = {
        ".ag-header": {"background-color": "#990011 !important"},
        ".ag-header-cell-label": {"color": "white !important", "font-weight": "600"},
        ".ag-row-even": {"background-color": "rgba(255,255,255,0.85) !important"},
        ".ag-row-odd": {"background-color": "rgba(253,232,233,0.5) !important"},
    }

    altura_fila = 42
    altura_header = 46
    altura_calculada = altura_header + altura_fila * len(df_grid) + 10
    altura_calculada = min(altura_calculada, 900)

    AgGrid(
        df_grid,
        gridOptions=grid_options,
        custom_css=custom_css,
        allow_unsafe_jscode=True,
        fit_columns_on_grid_load=True,
        theme="alpine",
        height=altura_calculada,
        update_mode="NO_UPDATE",
        key="grid_resumen_asesor_watermark_v2",
    )
    st.caption(f"Filas en df_grid: {len(df_grid)}")

    st.divider()

    with st.expander("🔍 Ver detalle de pagos (cuenta, asesor, día, valor, campo, marca, tipo de cliente)"):
        cols_det = ["cuenta", "Nombre_Asesor", "fecha_pago", "valor_pago", "Campo", "marca", "customer_type", "mejorperfil"]
        cols_det = [c for c in cols_det if c in base.columns]
        detalle = base[cols_det].sort_values("fecha_pago", ascending=False).copy()

        st.dataframe(
            detalle,
            width="stretch",
            hide_index=True,
            column_config={
                "cuenta": st.column_config.TextColumn("Cuenta"),
                "Nombre_Asesor": st.column_config.TextColumn("Asesor"),
                "fecha_pago": st.column_config.DateColumn("Fecha de pago", format="DD/MM/YYYY"),
                "valor_pago": st.column_config.NumberColumn("Valor pagado", format="$ %d"),
                "Campo": st.column_config.TextColumn("Campo"),
                "marca": st.column_config.TextColumn("Marca"),
                "customer_type": st.column_config.TextColumn("Tipo de Cliente"),
                "mejorperfil": st.column_config.TextColumn("Mejor Perfil"),
            },
        )
        csv_bytes = detalle.to_csv(index=False, sep=";", encoding="utf-8-sig").encode("utf-8-sig")
        st.download_button(
            label="⬇️ Descargar detalle en CSV",
            data=csv_bytes,
            file_name=f"detalle_pagos_asesor_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
            key="btn_descargar_detalle_pagos",
        )
        st.caption(f"{len(detalle):,} pagos individuales bajo los filtros actuales".replace(",", "."))

# ===========================================================================
#Funciones de apoyyo para modulo de dupree
# ===========================================================================

def cargar_asesores(json_path: str) -> dict:
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)

def buscar_vigencia(usuario: str, fecha_gestion, asesores: dict):
    info = asesores.get(usuario)
    if not info:
        return None, None

    fecha = pd.to_datetime(fecha_gestion).date()

    for v in info["vigencias"]:
        desde = pd.to_datetime(v["desde"]).date()
        hasta = pd.to_datetime(v["hasta"]).date() if v["hasta"] else None
        if desde <= fecha and (hasta is None or fecha <= hasta):
            return v["Nombre_Asesor"], v["Campo"]

    return None, None

def cruzar_con_asesores(df: pd.DataFrame, json_path: str) -> pd.DataFrame:
    asesores = cargar_asesores(json_path)

    resultados = df.apply(
        lambda row: buscar_vigencia(row["asesor_gestion"], row["fechagestion"], asesores),
        axis=1,
        result_type="expand"
    )
    df["Nombre_Asesor"] = resultados[0]
    df["Campo"] = resultados[1]

    return df