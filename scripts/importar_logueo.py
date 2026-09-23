"""
importar_logueo.py
----------------
Modulo ETL especializado para la carga, normalización, homologación con el catálogo
y almacenamiento persistente en gestiones.db de:
1. Malla de Turno (malla_turno - Programado)
2. Reporte Real ControlNext (reporte_logueo - Real Sucedido)
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
import pandas as pd
from scripts.catalogo_asesores import cargar_catalogo, aplicar_homologacion, normalizar_usuario
from scripts.importar_gestiones import inicializar_db, leer_archivo

# Mapeos de columnas flexibles para Malla de Turnos
MAPPING_MALLA = {
    "Fecha": ["fecha", "día", "dia", "fecha_turno", "date"],
    "Identificacion": ["identificacion", "cedula", "documento", "id", "cédula"],
    "asesor_malla": ["asesor_malla", "asesor", "agente", "nombre", "nombre_asesor", "usuario"],
    "Hora_Entrada": ["hora_entrada", "hora entrada", "entrada", "hora_inicio", "inicio"],
    "Hora_Salida": ["hora_salida", "hora salida", "salida", "hora_fin", "fin"],
    "Turno": ["turno", "horario", "programacion"],
    "Novedad": ["novedad", "observacion", "estado", "tipo_novedad"],
}


def _buscar_columna(df: pd.DataFrame, candidatas: list[str]) -> str | None:
    cols_norm = {str(c).strip().lower(): c for c in df.columns}
    for cand in candidatas:
        if cand.lower() in cols_norm:
            return cols_norm[cand.lower()]
    return None


def _convertir_hhmmss_a_minutos(val) -> float:
    if pd.isna(val) or val is None:
        return 0.0
    val_str = str(val).strip()
    if not val_str or val_str.lower() in ["nan", "none", "<na>"]:
        return 0.0
    if ":" in val_str:
        try:
            partes = [float(p) for p in val_str.split(":")]
            if len(partes) == 3:
                return partes[0] * 60.0 + partes[1] + partes[2] / 60.0
            elif len(partes) == 2:
                return partes[0] * 60.0 + partes[1]
        except Exception:
            pass
    try:
        num = float(val_str.replace(",", "."))
        return num
    except Exception:
        return 0.0


def normalizar_malla(df_raw: pd.DataFrame, catalogo: dict, origen: str = "archivo") -> pd.DataFrame:
    df = df_raw.copy()
    col_map = {}
    for col_final, candidatas in MAPPING_MALLA.items():
        encontrada = _buscar_columna(df, candidatas)
        if encontrada:
            col_map[encontrada] = col_final

    df = df.rename(columns=col_map)

    # Normalizar Fecha (ej. 31/08/2026)
    if "Fecha" not in df.columns:
        df["Fecha"] = pd.Timestamp.now().strftime("%Y-%m-%d")
    else:
        df["Fecha"] = pd.to_datetime(df["Fecha"], dayfirst=True, errors="coerce").dt.strftime("%Y-%m-%d")

    col_usuario = _buscar_columna(df, ["usuario", "usuario_mejor_gestion", "asesor_malla", "asesor", "agente"])
    if col_usuario:
        df["usuario_mejor_gestion"] = df[col_usuario].apply(lambda u: normalizar_usuario(u) if pd.notna(u) else None)
        df["asesor_malla"] = df[col_usuario].astype(str).str.strip()
    else:
        df["usuario_mejor_gestion"] = None
        df["asesor_malla"] = None

    df = aplicar_homologacion(df, catalogo)

    for col in ["Identificacion", "Hora_Entrada", "Hora_Salida", "Turno", "Novedad"]:
        if col not in df.columns:
            df[col] = None
        else:
            df[col] = df[col].astype(str).str.strip().replace({"nan": None, "<NA>": None, "None": None})

    def _calc_minutos_prog(row):
        h_in = row.get("Hora_Entrada")
        h_out = row.get("Hora_Salida")
        if h_in and h_out and pd.notna(h_in) and pd.notna(h_out):
            try:
                t_in = pd.to_timedelta(str(h_in).strip())
                t_out = pd.to_timedelta(str(h_out).strip())
                diff = (t_out - t_in).total_seconds() / 60.0
                if diff > 0:
                    return diff
            except Exception:
                pass
        return 0.0

    df["Horas_Programadas_Min"] = df.apply(_calc_minutos_prog, axis=1)
    df["origen_archivo"] = origen

    def _hash_malla(row):
        partes = [
            str(row.get("Fecha") or ""),
            str(row.get("Identificacion") or ""),
            str(row.get("usuario_mejor_gestion") or row.get("asesor_malla") or ""),
        ]
        return hashlib.sha1("|".join(partes).encode()).hexdigest()

    df["llave_hash"] = df.apply(_hash_malla, axis=1)

    columnas_finales = [
        "llave_hash", "Fecha", "Identificacion", "asesor_malla",
        "usuario_mejor_gestion", "Nombre_Asesor", "Campo",
        "Hora_Entrada", "Hora_Salida", "Horas_Programadas_Min",
        "Turno", "Novedad", "origen_archivo"
    ]
    for c in columnas_finales:
        if c not in df.columns:
            df[c] = None

    return df[columnas_finales]


def normalizar_logueo_controlnext(df_raw: pd.DataFrame, catalogo: dict, origen: str = "archivo") -> pd.DataFrame:
    df = df_raw.copy()

    # Identificar columna de usuario ControlNext
    col_usr_cn = _buscar_columna(df, ["usuario controlnext", "usuario", "agente", "usuario_red", "login"])
    if col_usr_cn:
        df["usuario_controlnext"] = df[col_usr_cn].astype(str).str.strip()
        df["usuario_mejor_gestion"] = df[col_usr_cn].apply(lambda u: normalizar_usuario(u) if pd.notna(u) else None)
    else:
        df["usuario_controlnext"] = "Desconocido"
        df["usuario_mejor_gestion"] = None

    # Normalizar Fecha Entrada (Formatos DD-MM-YYYY o auto)
    col_fecha = _buscar_columna(df, ["fecha entrada", "fecha", "date", "día", "dia"])
    if col_fecha:
        df["Fecha"] = pd.to_datetime(df[col_fecha], dayfirst=True, errors="coerce").dt.strftime("%Y-%m-%d")
    else:
        df["Fecha"] = pd.Timestamp.now().strftime("%Y-%m-%d")

    # Identificación / Cédula
    col_id = _buscar_columna(df, ["identificacion", "identificación", "cedula", "cédula", "documento", "id"])
    df["Identificacion"] = df[col_id].astype(str).str.strip() if col_id else None

    # Extensión
    col_ext = _buscar_columna(df, ["extension", "extensión"])
    df["Extension"] = df[col_ext].astype(str).str.strip() if col_ext else None

    # Horarios Entrada / Salida / Gestiones
    col_p_ent = _buscar_columna(df, ["primera entrada", "hora inicio", "hora_entrada"])
    df["Primera_Entrada"] = df[col_p_ent].astype(str).str.strip() if col_p_ent else None

    col_u_sal = _buscar_columna(df, ["última salida", "ultima salida", "hora fin", "hora_salida"])
    df["Ultima_Salida"] = df[col_u_sal].astype(str).str.strip() if col_u_sal else None

    col_p_ges = _buscar_columna(df, ["primera gestión", "primera gestion"])
    df["Primera_Gestion"] = df[col_p_ges].astype(str).str.strip() if col_p_ges else None

    col_u_ges = _buscar_columna(df, ["última gestión", "ultima gestion"])
    df["Ultima_Gestion"] = df[col_u_ges].astype(str).str.strip() if col_u_ges else None

    # Duraciones y Tiempos en minutos
    col_trl = _buscar_columna(df, ["tiempo real en línea", "tiempo real en linea", "tiempo_conectado"])
    df["Tiempo_Real_Linea_Min"] = df[col_trl].apply(_convertir_hhmmss_a_minutos) if col_trl else 0.0

    col_num_ses = _buscar_columna(df, ["número de sesiones", "numero de sesiones", "sesiones"])
    df["Numero_Sesiones"] = pd.to_numeric(df[col_num_ses], errors="coerce").fillna(1).astype(int) if col_num_ses else 1

    col_tot_llam = _buscar_columna(df, ["total llamadas", "llamadas"])
    df["Total_Llamadas"] = pd.to_numeric(df[col_tot_llam], errors="coerce").fillna(0).astype(int) if col_tot_llam else 0

    col_llam_cont = _buscar_columna(df, ["llamadas contestadas"])
    df["Llamadas_Contestadas"] = pd.to_numeric(df[col_llam_cont], errors="coerce").fillna(0).astype(int) if col_llam_cont else 0

    col_llam_nocont = _buscar_columna(df, ["llamadas no contestadas"])
    df["Llamadas_No_Contestadas"] = pd.to_numeric(df[col_llam_nocont], errors="coerce").fillna(0).astype(int) if col_llam_nocont else 0

    col_tt_llam = _buscar_columna(df, ["tiempo total en llamada"])
    df["Tiempo_Total_Llamada_Min"] = df[col_tt_llam].apply(_convertir_hhmmss_a_minutos) if col_tt_llam else 0.0

    # Pausas y Auxiliares
    # El almuerzo viene dividido en varios tipos (1 hora / 40 min / 30 min); se
    # guarda cada tipo por separado (para validar el tiempo permitido de cada uno)
    # y también un total sumado (Almuerzo_Min) para compatibilidad.
    col_alm_1h = _buscar_columna(df, ["almuerzo 1 hora_duracion", "almuerzo_duracion", "almuerzo"])
    df["Almuerzo_1Hora_Min"] = df[col_alm_1h].apply(_convertir_hhmmss_a_minutos) if col_alm_1h else 0.0

    col_alm_40 = _buscar_columna(df, ["almuerzo 40 min_duracion"])
    df["Almuerzo_40Min_Min"] = df[col_alm_40].apply(_convertir_hhmmss_a_minutos) if col_alm_40 else 0.0

    col_alm_30 = _buscar_columna(df, ["amuerzo 30 min_duracion", "almuerzo 30 min_duracion"])
    df["Almuerzo_30Min_Min"] = df[col_alm_30].apply(_convertir_hhmmss_a_minutos) if col_alm_30 else 0.0

    df["Almuerzo_Min"] = df["Almuerzo_1Hora_Min"] + df["Almuerzo_40Min_Min"] + df["Almuerzo_30Min_Min"]

    col_bano = _buscar_columna(df, ["baño_duracion", "baño", "bano"])
    df["Bano_Min"] = df[col_bano].apply(_convertir_hhmmss_a_minutos) if col_bano else 0.0

    col_brk10 = _buscar_columna(df, ["break 10_duracion", "break 10"])
    df["Break10_Min"] = df[col_brk10].apply(_convertir_hhmmss_a_minutos) if col_brk10 else 0.0

    col_brk15 = _buscar_columna(df, ["break 15_duracion", "break 15"])
    df["Break15_Min"] = df[col_brk15].apply(_convertir_hhmmss_a_minutos) if col_brk15 else 0.0

    col_cap = _buscar_columna(df, ["capacitacion_duracion", "capacitacion", "capacitación"])
    df["Capacitacion_Min"] = df[col_cap].apply(_convertir_hhmmss_a_minutos) if col_cap else 0.0

    col_paact = _buscar_columna(df, ["pausas activas_duracion", "pausas activas"])
    df["PausasActivas_Min"] = df[col_paact].apply(_convertir_hhmmss_a_minutos) if col_paact else 0.0

    col_tmuerto = _buscar_columna(df, ["tiempo muerto"])
    df["Tiempo_Muerto_Min"] = df[col_tmuerto].apply(_convertir_hhmmss_a_minutos) if col_tmuerto else 0.0

    # Aplicar homologación del catálogo
    df = aplicar_homologacion(df, catalogo)

    df["origen_archivo"] = origen

    def _hash_logueo(row):
        partes = [
            str(row.get("Fecha") or ""),
            str(row.get("Identificacion") or ""),
            str(row.get("usuario_controlnext") or ""),
        ]
        return hashlib.sha1("|".join(partes).encode()).hexdigest()

    df["llave_hash"] = df.apply(_hash_logueo, axis=1)

    columnas_finales = [
        "llave_hash", "Fecha", "Identificacion", "usuario_controlnext",
        "usuario_mejor_gestion", "Nombre_Asesor", "Campo", "Extension",
        "Primera_Entrada", "Ultima_Salida", "Primera_Gestion", "Ultima_Gestion",
        "Tiempo_Real_Linea_Min", "Numero_Sesiones", "Total_Llamadas",
        "Llamadas_Contestadas", "Llamadas_No_Contestadas", "Tiempo_Total_Llamada_Min",
        "Almuerzo_Min", "Almuerzo_1Hora_Min", "Almuerzo_40Min_Min", "Almuerzo_30Min_Min",
        "Bano_Min", "Break10_Min", "Break15_Min",
        "Capacitacion_Min", "PausasActivas_Min", "Tiempo_Muerto_Min",
        "origen_archivo"
    ]

    for c in columnas_finales:
        if c not in df.columns:
            df[c] = None

    return df[columnas_finales]


def insertar_malla(con: sqlite3.Connection, df: pd.DataFrame) -> int:
    if df.empty:
        return 0

    cols = [
        "llave_hash", "Fecha", "Identificacion", "asesor_malla",
        "usuario_mejor_gestion", "Nombre_Asesor", "Campo",
        "Hora_Entrada", "Hora_Salida", "Horas_Programadas_Min",
        "Turno", "Novedad", "origen_archivo"
    ]
    df = df[cols].copy()

    sets = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "llave_hash")
    placeholders = ",".join(["?" for _ in cols])
    sql = f"""
        INSERT INTO malla_turno({','.join(cols)}, actualizado_en)
        VALUES({placeholders}, datetime('now','localtime'))
        ON CONFLICT(llave_hash) DO UPDATE SET {sets}, actualizado_en=datetime('now','localtime')
    """

    filas = [tuple(None if pd.isna(v) else v for v in row) for row in df.itertuples(index=False, name=None)]
    antes = con.execute("SELECT COUNT(*) FROM malla_turno").fetchone()[0]
    con.executemany(sql, filas)
    con.commit()
    despues = con.execute("SELECT COUNT(*) FROM malla_turno").fetchone()[0]
    return despues - antes


def insertar_logueo(con: sqlite3.Connection, df: pd.DataFrame) -> int:
    if df.empty:
        return 0

    cols = [
        "llave_hash", "Fecha", "Identificacion", "usuario_controlnext",
        "usuario_mejor_gestion", "Nombre_Asesor", "Campo", "Extension",
        "Primera_Entrada", "Ultima_Salida", "Primera_Gestion", "Ultima_Gestion",
        "Tiempo_Real_Linea_Min", "Numero_Sesiones", "Total_Llamadas",
        "Llamadas_Contestadas", "Llamadas_No_Contestadas", "Tiempo_Total_Llamada_Min",
        "Almuerzo_Min", "Almuerzo_1Hora_Min", "Almuerzo_40Min_Min", "Almuerzo_30Min_Min",
        "Bano_Min", "Break10_Min", "Break15_Min",
        "Capacitacion_Min", "PausasActivas_Min", "Tiempo_Muerto_Min",
        "origen_archivo"
    ]
    df = df[cols].copy()

    sets = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "llave_hash")
    placeholders = ",".join(["?" for _ in cols])
    sql = f"""
        INSERT INTO reporte_logueo({','.join(cols)}, actualizado_en)
        VALUES({placeholders}, datetime('now','localtime'))
        ON CONFLICT(llave_hash) DO UPDATE SET {sets}, actualizado_en=datetime('now','localtime')
    """

    filas = [tuple(None if pd.isna(v) else v for v in row) for row in df.itertuples(index=False, name=None)]
    antes = con.execute("SELECT COUNT(*) FROM reporte_logueo").fetchone()[0]
    con.executemany(sql, filas)
    con.commit()
    despues = con.execute("SELECT COUNT(*) FROM reporte_logueo").fetchone()[0]
    return despues - antes


def procesar_archivos_adherencia(archivos, db_path: str, catalogo: dict, tipo: str = "logueo") -> list[dict]:
    con = inicializar_db(db_path)
    resumen = []

    for item in archivos:
        nombre = getattr(item, "name", str(item))
        try:
            if isinstance(item, (str, Path)):
                df_raw = leer_archivo(Path(item))
            else:
                sufijo = Path(nombre).suffix.lower()
                item.seek(0)
                if sufijo == ".csv":
                    for enc in ["utf-8", "utf-8-sig", "cp1252", "latin-1"]:
                        for sep in [";", ",", "\t", "|", None]:
                            try:
                                item.seek(0)
                                df_raw = pd.read_csv(item, encoding=enc, sep=sep, engine="python", on_bad_lines="skip")
                                if len(df_raw.columns) > 1:
                                    break
                            except Exception:
                                continue
                        else:
                            continue
                        break
                elif sufijo in {".xlsx", ".xls"}:
                    df_raw = pd.read_excel(item)
                elif sufijo == ".parquet":
                    df_raw = pd.read_parquet(item)
                else:
                    raise ValueError(f"Extensión no soportada: {sufijo}")

            if df_raw.empty:
                resumen.append({"archivo": nombre, "estado": "Archivo vacío"})
                continue

            if tipo == "malla":
                df = normalizar_malla(df_raw, catalogo, origen=nombre)
                nuevos = insertar_malla(con, df)
            else:
                df = normalizar_logueo_controlnext(df_raw, catalogo, origen=nombre)
                nuevos = insertar_logueo(con, df)

            resumen.append({"archivo": nombre, "estado": f"OK: {len(df)} procesados ({nuevos} nuevos)"})
        except Exception as e:
            resumen.append({"archivo": nombre, "estado": f"Error: {e}"})

    con.close()
    return resumen

def reset_malla_turno(db_path: str) -> None:
    con = sqlite3.connect(db_path)
    con.execute("DELETE FROM malla_turno")
    con.commit()
    con.close()


def reset_reporte_logueo(db_path: str) -> None:
    con = sqlite3.connect(db_path)
    con.execute("DELETE FROM reporte_logueo")
    con.commit()
    con.close()