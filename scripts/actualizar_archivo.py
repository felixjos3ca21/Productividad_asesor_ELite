from pathlib import Path

import pandas as pd
import streamlit as st

from scripts.importar_gestiones import transformar_df, insertar_registros_safe, inicializar_db

# Columnas candidatas por cada campo clave (mismas listas que usa importar_gestiones.py)
CAMPOS_CLAVE = {
    "Fecha": ["Fecha", "fechagestion", "fecha_gestion"],
    "Hora": ["Hora", "horagestion", "hora_gestion"],
    "Cuenta": ["Cuenta", "cuenta"],
    "asesor_gestion": ["asesor_gestion", "asesor", "usuario", "agente"],
    "Identificacion": ["Identificacion", "identification", "identificacion"],
}


def _columnas_normalizadas(df: pd.DataFrame) -> set[str]:
    return {str(c).strip().lower() for c in df.columns}


def validar_columnas_clave(df: pd.DataFrame) -> list[str]:
    """Devuelve los campos clave que NO se encontraron en el archivo (columna completa ausente)."""
    cols_norm = _columnas_normalizadas(df)
    faltantes = []
    for campo, candidatas in CAMPOS_CLAVE.items():
        if not any(c.lower() in cols_norm for c in candidatas):
            faltantes.append(campo)
    return faltantes


def leer_archivo_subido(archivo) -> pd.DataFrame:
    """Lee un archivo entregado por st.file_uploader (no una ruta de disco)."""
    sufijo = Path(archivo.name).suffix.lower()

    if sufijo == ".csv":
        ultimo_error = None
        for enc in ["utf-8", "utf-8-sig", "cp1252", "latin-1"]:
            for sep in [None, ";", ",", "\t", "|"]:
                try:
                    archivo.seek(0)
                    return pd.read_csv(archivo, encoding=enc, sep=sep, engine="python", on_bad_lines="skip")
                except Exception as e:
                    ultimo_error = e
        raise ValueError(f"No se pudo leer el CSV: {ultimo_error}")

    if sufijo in {".xlsx", ".xls"}:
        archivo.seek(0)
        return pd.read_excel(archivo)

    if sufijo == ".parquet":
        archivo.seek(0)
        return pd.read_parquet(archivo)

    raise ValueError(f"Extension no soportada: {sufijo}")


def procesar_archivos(archivos, db_path: str) -> list[dict]:
    """Valida, transforma e inserta cada archivo subido. Devuelve un resumen por archivo."""
    con = inicializar_db(db_path)
    resumen = []

    for archivo in archivos:
        try:
            df_raw = leer_archivo_subido(archivo)
        except Exception as e:
            resumen.append({"archivo": archivo.name, "estado": f"Error de lectura: {e}"})
            continue

        if df_raw.empty:
            resumen.append({"archivo": archivo.name, "estado": "Archivo vacio, no se proceso"})
            continue

        faltantes = validar_columnas_clave(df_raw)
        if faltantes:
            resumen.append({
                "archivo": archivo.name,
                "estado": f"Rechazado: faltan columnas para {', '.join(faltantes)}",
            })
            continue

        try:
            df = transformar_df(df_raw, origen=archivo.name)
            nuevas = insertar_registros_safe(con, df)
            con.commit()
            resumen.append({"archivo": archivo.name, "estado": f"OK: {nuevas} registros nuevos"})
        except Exception as e:
            resumen.append({"archivo": archivo.name, "estado": f"Error al procesar: {e}"})

    con.close()
    return resumen


def render_actualizar_archivo_sidebar(db_path: str) -> None:
    """Dibuja en el sidebar el uploader y el boton de procesar. Llamar desde cualquier pagina."""
    with st.sidebar.expander("🔄 Actualizar desde archivo", expanded=False):
        archivos = st.file_uploader(
            "Selecciona uno o varios archivos",
            type=["csv", "xlsx", "xls", "parquet"],
            accept_multiple_files=True,
            key="uploader_actualizar_archivo",
        )

        if st.button("Procesar", disabled=not archivos, key="btn_procesar_actualizar_archivo"):
            resumen = procesar_archivos(archivos, db_path)
            st.dataframe(pd.DataFrame(resumen), use_container_width=True)
