import hashlib
import pandas as pd
from scripts.catalogo_baguer import cargar_catalogo, aplicar_homologacion


def _primera_columna(df_base, candidatas):
    for c in candidatas:
        if c in df_base.columns:
            return c
    return None


def _a_hora_hhmmss(serie):
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

        def fmt_td(x):
            if pd.isna(x):
                return pd.NA
            total = abs(int(x.total_seconds()))
            h, resto = divmod(total, 3600)
            m, sec = divmod(resto, 60)
            return f"{h:02d}:{m:02d}:{sec:02d}"

        if mask_td.any():
            idx_td = td.index[mask_td]
            salida.loc[idx_td] = td.loc[idx_td].apply(fmt_td).astype("string")

    return salida


def _transformar_fechas_horas(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    col_fecha = _primera_columna(df, ["fechagestion"])
    col_hora = _primera_columna(df, ["horagestion"])
    col_tg = _primera_columna(df, ["tiempogestion"])
    col_tl = _primera_columna(df, ["tiempollamada"])
    col_id = _primera_columna(df, ["identificacion"])
    col_cuenta = _primera_columna(df, ["cuenta"])
    col_fp = _primera_columna(df, ["fechapromesa"])

    if col_fecha:
        df["Fecha"] = pd.to_datetime(df[col_fecha], errors="coerce").dt.tz_localize(None).dt.normalize()
    if col_hora:
        df["Hora"] = _a_hora_hhmmss(df[col_hora])
    if col_tg:
        df["Tiempo_Gestion"] = _a_hora_hhmmss(df[col_tg])
    if col_tl:
        df["Tiempo_Llamada"] = _a_hora_hhmmss(df[col_tl])
    if col_id:
        df["Identificacion_limpia"] = (
            df[col_id].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
        )
    if col_cuenta:
        df["Cuenta_limpia"] = (
            df[col_cuenta].astype("string")
            .str.replace("-", "", regex=False)
            .str.replace(r'\.0$', '', regex=True)
            .str.strip()
        )
    if col_fp:
        df["Fecha_Promesa_limpia"] = pd.to_datetime(df[col_fp], errors="coerce").dt.tz_localize(None).dt.normalize()

    return df


def _generar_hash_id(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    llave_compuesta = (
        df["cuenta"].astype(str).fillna("") + "|" +
        df["horagestion"].astype(str).fillna("") + "|" +
        df["asesor"].astype(str).fillna("") + "|" +
        df["ultimo_perfil"].astype(str).fillna("")
    )
    df["id_registro"] = llave_compuesta.apply(lambda x: hashlib.md5(x.encode("utf-8")).hexdigest())
    return df


COLUMNAS_TABLA = [
    "id_registro", "fechagestion", "horagestion", "tiempogestion", "tiempollamada",
    "identificacion", "nombrecompleto", "cuenta", "asesor_gestion", "asesor",
    "perfil_historico", "ultimo_perfil", "valorpromesa", "fechapromesa",
    "numeromarcado", "intentosmarcacion", "gestion", "motivo_no_pago", "accion",
    "codllamada", "contacto", "usuario_mejor_gestion", "fecha_mejor_gestion",
    "Nombre_Asesor", "Fecha", "Hora", "Tiempo_Gestion", "Tiempo_Llamada",
    "Identificacion_limpia", "Cuenta_limpia", "Fecha_Promesa_limpia",
]


def procesar_reporte_baguer(df_crudo: pd.DataFrame) -> pd.DataFrame:
    catalogo = cargar_catalogo()
    df = aplicar_homologacion(df_crudo, catalogo)
    df = _transformar_fechas_horas(df)
    df = _generar_hash_id(df)

    faltantes = [c for c in COLUMNAS_TABLA if c not in df.columns]
    if faltantes:
        raise ValueError(f"Faltan columnas antes de guardar: {faltantes}")

    return df[COLUMNAS_TABLA]