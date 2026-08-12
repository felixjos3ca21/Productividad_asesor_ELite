"""
importar_gestiones.py
---------------------
ETL incremental: lee archivos de gestiones, deduplica por llave de negocio
y los almacena en gestiones.db (SQLite) en la raiz del proyecto.

Uso:
    python scripts/importar_gestiones.py
    python scripts/importar_gestiones.py --carpeta "D:\\OtraCarpeta\\Gestiones"
    python scripts/importar_gestiones.py --db gestiones.db --verbose

Logica de deduplicacion:
    La llave de negocio es: Fecha + Hora + Cuenta + asesor_gestion + Identificacion.
    Se computa un SHA-1 de esos campos como columna `llave_hash` con restriccion UNIQUE.
    INSERT OR IGNORE garantiza que el mismo registro nunca se inserte dos veces,
    aunque aparezca en multiples archivos o el mismo archivo se reimporte.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sqlite3
from pathlib import Path
from scripts.catalogo_asesores import cargar_catalogo, aplicar_homologacion
import pandas as pd


logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CARPETAS = [
    r"C:\Users\elite\OneDrive\Desktop\Gestiones",
]
DEFAULT_DB = str(REPO_ROOT / "gestiones.db")
DEFAULT_CATALOG = str(REPO_ROOT / "asesores_catalogo.json")

# Columnas que se normalizan y guardan; las demas se descartan.
COLUMNAS_REPORTE = [
    "llave_hash",
    "Fecha",
    "Hora",
    "Cuenta",
    "Identificacion",
    "asesor_gestion",
    "FechaPromesa",
    "Tiempo_Gestion",
    "Tiempo_Llamada",
    "ultimo_perfil_cliente",
    "valorpromesa",
    "Marca",
    "CRM",
    "origen_archivo",
]

DDL_GESTIONES = """
CREATE TABLE IF NOT EXISTS gestiones (
    llave_hash          TEXT PRIMARY KEY,
    Fecha               TEXT,
    Hora                TEXT,
    Cuenta              TEXT,
    Identificacion      TEXT,
    asesor_gestion      TEXT,
    FechaPromesa        TEXT,
    Tiempo_Gestion      TEXT,
    Tiempo_Llamada      TEXT,
    ultimo_perfil_cliente TEXT,
    valorpromesa        REAL,
    Marca               TEXT,
    CRM                 TEXT,
    origen_archivo      TEXT
);
"""
DDL_PAGOS_X_ASESOR = """
CREATE TABLE IF NOT EXISTS pagos_x_asesor (
    clave_pago            TEXT PRIMARY KEY,
    cuenta                TEXT,
    identificacion        TEXT,
    usuario_mejor_gestion TEXT,
    Nombre_Asesor         TEXT,
    Campo                 TEXT,
    valor_pago            REAL,
    fecha_pago            TEXT,
    fecha_asignacion      TEXT,
    fechagestion          TEXT,
    mejorperfil           TEXT,
    estado                TEXT,
    marca                 TEXT,
    customer_type         TEXT,
    nombre_campana        TEXT,
    origen_archivo        TEXT,
    actualizado_en        TEXT NOT NULL
);
"""

DDL_ARCHIVOS = """
CREATE TABLE IF NOT EXISTS archivos_importados (
    ruta        TEXT PRIMARY KEY,
    mtime_ns    INTEGER NOT NULL,
    size_bytes  INTEGER NOT NULL,
    filas_nuevas INTEGER NOT NULL DEFAULT 0,
    importado_en TEXT NOT NULL
);
"""


# ── Helpers de lectura ──────────────────────────────────────────────────────

def leer_csv_robusto(path: Path) -> pd.DataFrame:
    encodings = ["utf-8", "utf-8-sig", "cp1252", "latin-1"]
    separadores = [None, ";", ",", "\t", "|"]
    ultimo_error = None
    for enc in encodings:
        for sep in separadores:
            try:
                return pd.read_csv(path, encoding=enc, sep=sep,
                                   engine="python", on_bad_lines="skip")
            except Exception as e:
                ultimo_error = e
    raise RuntimeError(f"No se pudo leer CSV: {ultimo_error}")


def leer_archivo(path: Path) -> pd.DataFrame:
    sufijo = path.suffix.lower()
    if sufijo == ".csv":
        return leer_csv_robusto(path)
    if sufijo in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    if sufijo == ".parquet":
        return pd.read_parquet(path)
    raise ValueError(f"Extension no soportada: {sufijo}")


# ── Normalizacion de columnas ───────────────────────────────────────────────

def _primera(df: pd.DataFrame, candidatas: list[str]) -> str | None:
    for c in candidatas:
        if c in df.columns:
            return c
    return None


def _primera_ci(df: pd.DataFrame, candidatas: list[str]) -> str | None:
    mapa = {str(c).strip().lower(): c for c in df.columns}
    for c in candidatas:
        col = mapa.get(c.lower())
        if col:
            return col
    return None


def a_hora_hhmmss(serie: pd.Series) -> pd.Series:
    s = serie.astype("string").str.strip()
    salida = pd.Series(pd.NA, index=serie.index, dtype="string")
    dt = pd.to_datetime(s, format="%H:%M:%S", errors="coerce")
    mask = dt.notna()
    salida.loc[mask] = dt.loc[mask].dt.strftime("%H:%M:%S")
    if salida.isna().any():
        dt2 = pd.to_datetime(s.loc[salida.isna()], format="%H:%M", errors="coerce")
        m2 = dt2.notna()
        if m2.any():
            salida.loc[dt2.index[m2]] = dt2.loc[m2].dt.strftime("%H:%M:%S")
    if salida.isna().any():
        td = pd.to_timedelta(s.loc[salida.isna()], errors="coerce")
        m3 = td.notna()
        if m3.any():
            idx = td.index[m3]
            segs = td.loc[idx].dt.total_seconds().astype(int).abs()
            salida.loc[idx] = (
                (segs // 3600).astype(str).str.zfill(2) + ":" +
                ((segs % 3600) // 60).astype(str).str.zfill(2) + ":" +
                (segs % 60).astype(str).str.zfill(2)
            ).astype("string")
    return salida


def transformar_df(df_raw: pd.DataFrame, origen: str) -> pd.DataFrame:
    df = df_raw.copy()

    # ── Columnas clave ──────────────────────────────────────────────────────
    col_fecha  = _primera(df, ["Fecha", "fechagestion", "fecha_gestion"])
    col_hora   = _primera(df, ["Hora", "horagestion", "hora_gestion"])
    col_tg     = _primera(df, ["Tiempo_Gestion", "tiempogestion", "tiempo_gestion"])
    col_tl     = _primera(df, ["Tiempo_Llamada", "tiempollamada", "tiempo_llamada"])
    col_id     = _primera(df, ["Identificacion", "identification", "identificacion"])
    col_cuenta = _primera(df, ["Cuenta", "cuenta"])
    col_fp     = _primera(df, ["FechaPromesa", "fechapromesa", "fecha_promesa"])
    col_perfil = _primera_ci(df, ["ultimo_perfil_cliente", "ultimo perfil cliente", "perfil_cliente"])
    col_valor  = _primera_ci(df, ["valorpromesa", "valor_promesa", "valor promesa"])
    col_asesor = _primera_ci(df, ["asesor_gestion", "asesor", "usuario", "agente"])
    col_marca  = _primera_ci(df, ["Marca", "marca"])
    col_crm    = _primera_ci(df, ["CRM", "crm", "Crm"])

    out = pd.DataFrame()

    out["Fecha"] = pd.to_datetime(df[col_fecha], errors="coerce").dt.normalize().dt.strftime("%Y-%m-%d") if col_fecha else pd.NA
    out["Hora"]  = a_hora_hhmmss(df[col_hora]) if col_hora else pd.NA
    out["Cuenta"] = (df[col_cuenta].astype("string").str.replace("-", "", regex=False).str.strip()
                     if col_cuenta else pd.NA)
    out["Identificacion"] = df[col_id].astype("string").str.strip() if col_id else pd.NA
    out["asesor_gestion"] = df[col_asesor].astype("string").str.strip() if col_asesor else pd.NA
    out["FechaPromesa"] = (pd.to_datetime(df[col_fp], errors="coerce").dt.normalize().dt.strftime("%Y-%m-%d")
                           if col_fp else pd.NA)
    out["Tiempo_Gestion"]  = a_hora_hhmmss(df[col_tg]) if col_tg else pd.NA
    out["Tiempo_Llamada"]  = a_hora_hhmmss(df[col_tl]) if col_tl else pd.NA
    out["ultimo_perfil_cliente"] = df[col_perfil].astype("string").str.strip().str.lower() if col_perfil else pd.NA
    out["valorpromesa"] = pd.to_numeric(df[col_valor], errors="coerce") if col_valor else pd.NA
    out["Marca"] = df[col_marca].astype("string").str.strip() if col_marca else pd.NA
    out["CRM"]   = df[col_crm].astype("string").str.strip() if col_crm else pd.NA
    out["origen_archivo"] = origen

    # Limpiar NA de texto a None para SQLite
    for c in ["Fecha", "Hora", "Cuenta", "Identificacion", "asesor_gestion",
              "FechaPromesa", "Tiempo_Gestion", "Tiempo_Llamada",
              "ultimo_perfil_cliente", "Marca", "CRM"]:
        s = out[c].astype("string")
        out[c] = s.where(~s.isin(["<NA>", "nan", "None", "", "NaT"]), other=None)

    return out


# ── Hash de llave de negocio ────────────────────────────────────────────────

def calcular_hash(row: pd.Series) -> str:
    partes = [
        str(row.get("Fecha") or ""),
        str(row.get("Hora") or ""),
        str(row.get("Cuenta") or ""),
        str(row.get("asesor_gestion") or ""),
        str(row.get("Identificacion") or ""),
    ]
    return hashlib.sha1("|".join(partes).encode()).hexdigest()


# ── SQLite helpers ──────────────────────────────────────────────────────────

def inicializar_db(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute(DDL_GESTIONES)
    con.execute(DDL_ARCHIVOS)
    con.execute(DDL_PAGOS_X_ASESOR)
    con.commit()
    return con

def leer_carpeta_pagos(carpeta: str) -> pd.DataFrame:
    carpeta = Path(carpeta)
    extensiones = {".csv", ".xlsx", ".xls", ".json", ".parquet"}
    archivos = sorted(p for p in carpeta.rglob("*") if p.is_file() and p.suffix.lower() in extensiones)

    dfs, omitidos = [], []
    for archivo in archivos:
        try:
            sufijo = archivo.suffix.lower()
            if sufijo == ".csv":
                tmp = leer_csv_robusto(archivo)
            elif sufijo in {".xlsx", ".xls"}:
                tmp = pd.read_excel(archivo, dtype=str)
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

    if omitidos:
        for nombre, error in omitidos:
            log.warning("Omitido %s: %s", nombre, error)

    if not dfs:
        return pd.DataFrame()
    return pd.concat(dfs, ignore_index=True, sort=False)

def cargar_consolidado_pagos(archivo: str, hoja: str = "Consolidado Pagos") -> pd.DataFrame:
    df = pd.read_excel(archivo, sheet_name=hoja, usecols=["CUENTA", "PAGO", "FECHA"], dtype={"CUENTA": str})
    df.columns = df.columns.str.strip().str.upper()
    df = df.drop_duplicates(subset=["CUENTA", "PAGO", "FECHA"])
    df = df.groupby("CUENTA", as_index=False).agg(PAGO=("PAGO", "sum"), FECHA=("FECHA", "max"))
    return df

COLUMNAS_A_DESCARTAR_PAGOS = [
    'direccion', 'fecha_final', 'email1', 'email2', 'email3', 'email4',
    'celular1', 'celular2', 'celular3', 'celular4', 'celular5', 'celular6',
    'celular7', 'celular8', 'celular9', 'celular10', 'fijo1', 'fijo2',
    'fijo3', 'fijo4', 'ciudad', 'nombrecompleto', 'min', 'plan',
    'acepta_nocobrorx', 'acepta_salvamento', 'gestion', 'rotacion', 'rotacion_dia',
    'fechanogestion', 'fechapagossinaplicar', 'numeromarcado', 'fecha_ingreso',
    'fecha_reingreso', 'fecha_retiro', 'tipo_terminal', 'rango_monto_inicial',
    'rango_deuda_real', 'salvamento', 'n_servicios', 'casa_cobro', 'pago',
    'fecha_de_pago', 'estado_actual', 'recuperada', 'red_dth', 'raiz_ranking_alto',
    'custcode_ranking_alto', 'segmento_cliente_ranking_alto', 'dct_ranking_alto',
    'agencia_ranking_alto', 'segmento_dto_ranking_alto', 'concepto_ranking_alto',
    'gestion_ranking_alto', 'raiz_ranking_medio', 'custcode_ranking_medio',
    'segmento_cliente_ranking_medio', 'agencia_ranking_medio',
    'concepto_ranking_medio', 'gestion_ranking_medio',
]

SGA_CODIGOS = {"82", "83", "85", "86", "88", "89"}

COLUMNAS_FINALES_PAGOS = [
    "cuenta", "identificacion", "usuario_mejor_gestion", "Nombre_Asesor", "Campo",
    "valor_pago", "fecha_pago", "fecha_asignacion", "fechagestion", "mejorperfil",
    "estado", "marca", "customer_type", "nombre_campana", "origen_archivo",
]


def transformar_pagos_x_asesor(
    df_unificado: pd.DataFrame,
    catalogo: dict,
    df_pagos_consolidado: pd.DataFrame,
) -> pd.DataFrame:
    df = df_unificado.copy()
    df.drop(columns=COLUMNAS_A_DESCARTAR_PAGOS, inplace=True, errors="ignore")

    df["cuenta_limpia"] = (
        df["cuenta"].astype("string").str.replace("-", "", regex=False)
        .str.replace(".", "", regex=False).str.strip()
    )

    df = pd.merge(df, df_pagos_consolidado, how="left", left_on="cuenta_limpia", right_on="CUENTA")
    df["PAGO"] = df["PAGO"].astype(str)
    df["valor_pago"] = df["valor_pago"].fillna(df["PAGO"])
    df["fecha_pago"] = df["fecha_pago"].fillna(df["FECHA"])
    df.drop(columns=["PAGO", "FECHA", "CUENTA"], inplace=True, errors="ignore")
    df["fecha_asignacion"] = pd.to_datetime(df["fecha_asignacion"], errors="coerce").dt.strftime("%Y-%m-%d")
    df["marca"] = df["marca"].replace({"0": "CERO", "0_v": "CERO"}).str.strip().str.upper()
    df["customer_type"] = df["customer_type_id"].apply(
        lambda x: "SGA" if str(x).strip() in SGA_CODIGOS else "Masivo"
    )

    df = df[df["valor_pago"].notna()].copy()

    df = aplicar_homologacion(df, catalogo)  # import desde catalogo_asesores.py

    df["fechagestion"] = pd.to_datetime(df["fechagestion"], errors="coerce").dt.strftime("%Y-%m-%d")
    df["fecha_pago"] = pd.to_datetime(df["fecha_pago"], errors="coerce").dt.strftime("%Y-%m-%d")
    df["fecha_asignacion"] = pd.to_datetime(df["fecha_asignacion"], errors="coerce").dt.strftime("%Y-%m-%d")
    df["identificacion"] = df["identificacion"].astype("string").str.strip()

    df = df.rename(columns={"cuenta_limpia": "cuenta_final"})
    df = df.drop(columns=["cuenta"], errors="ignore").rename(columns={"cuenta_final": "cuenta"})

    faltan_fecha = df["fecha_asignacion"].isna() | df["fechagestion"].isna()
    if faltan_fecha.any():
        log.warning("Filas sin fecha_asignacion/fechagestion, se excluyen: %d", faltan_fecha.sum())
        df = df.loc[~faltan_fecha].copy()

    df["clave_pago"] = (
        df["cuenta"].astype(str).str.strip() + "|" +
        df["fecha_asignacion"] + "|" +
        df["fechagestion"] + "|" +
        df["fecha_pago"].fillna("")
    )

    cols = [c for c in COLUMNAS_FINALES_PAGOS if c in df.columns]
    return df[["clave_pago"] + cols].copy()

def archivo_ya_procesado(con: sqlite3.Connection, ruta: str, mtime_ns: int, size: int) -> bool:
    row = con.execute(
        "SELECT mtime_ns, size_bytes FROM archivos_importados WHERE ruta = ?", (ruta,)
    ).fetchone()
    if row is None:
        return False
    return row[0] == mtime_ns and row[1] == size


def registrar_archivo(con: sqlite3.Connection, ruta: str, mtime_ns: int,
                       size: int, filas_nuevas: int) -> None:
    con.execute(
        """INSERT INTO archivos_importados(ruta, mtime_ns, size_bytes, filas_nuevas, importado_en)
           VALUES(?,?,?,?, datetime('now','localtime'))
           ON CONFLICT(ruta) DO UPDATE SET
               mtime_ns=excluded.mtime_ns,
               size_bytes=excluded.size_bytes,
               filas_nuevas=excluded.filas_nuevas,
               importado_en=excluded.importado_en""",
        (ruta, mtime_ns, size, filas_nuevas),
    )


def insertar_registros(con: sqlite3.Connection, df: pd.DataFrame) -> int:
    if df.empty:
        return 0

    df = df.copy()
    df["llave_hash"] = df.apply(calcular_hash, axis=1)

    # Ordenar columnas segun DDL
    cols = [c for c in COLUMNAS_REPORTE if c in df.columns]
    df = df[cols]

    antes = con.execute("SELECT COUNT(*) FROM gestiones").fetchone()[0]
    df.to_sql("gestiones", con, if_exists="append", index=False, method="multi",
              chunksize=500)
    # to_sql no falla en duplicados; usamos INSERT OR IGNORE via executemany
    # Mejor: insertar via executemany con INSERT OR IGNORE
    return 0  # se recalcula abajo

def insertar_pagos_x_asesor(con: sqlite3.Connection, df: pd.DataFrame) -> int:
    if df.empty:
        return 0

    columnas = ["clave_pago"] + COLUMNAS_FINALES_PAGOS
    df = df.reindex(columns=columnas)

    sets = ", ".join(f"{c}=excluded.{c}" for c in COLUMNAS_FINALES_PAGOS)
    placeholders = ",".join(["?" for _ in columnas])
    sql = f"""
        INSERT INTO pagos_x_asesor({','.join(columnas)}, actualizado_en)
        VALUES({placeholders}, datetime('now','localtime'))
        ON CONFLICT(clave_pago) DO UPDATE SET {sets}, actualizado_en=datetime('now','localtime')
    """

    filas = [tuple(None if pd.isna(v) else v for v in row) for row in df.itertuples(index=False, name=None)]

    antes = con.execute("SELECT COUNT(*) FROM pagos_x_asesor").fetchone()[0]
    con.executemany(sql, filas)
    con.commit()
    despues = con.execute("SELECT COUNT(*) FROM pagos_x_asesor").fetchone()[0]
    log.info("pagos_x_asesor: %d filas nuevas, %d filas totales", despues - antes, despues)
    return despues - antes

def insertar_registros_safe(con: sqlite3.Connection, df: pd.DataFrame) -> int:
    """INSERT OR IGNORE usando executemany para respetar UNIQUE en llave_hash."""
    if df.empty:
        return 0

    df = df.copy()
    df["llave_hash"] = df.apply(calcular_hash, axis=1)

    cols = [c for c in COLUMNAS_REPORTE if c in df.columns]
    missing = [c for c in COLUMNAS_REPORTE if c not in df.columns]
    for c in missing:
        df[c] = None
    df = df[COLUMNAS_REPORTE]

    placeholders = ",".join(["?" for _ in COLUMNAS_REPORTE])
    sql = f"INSERT OR IGNORE INTO gestiones({','.join(COLUMNAS_REPORTE)}) VALUES({placeholders})"

    filas = [
        tuple(None if pd.isna(v) else v for v in row)
        for row in df.itertuples(index=False, name=None)
    ]

    antes = con.execute("SELECT COUNT(*) FROM gestiones").fetchone()[0]
    con.executemany(sql, filas)
    despues = con.execute("SELECT COUNT(*) FROM gestiones").fetchone()[0]
    return despues - antes


# ── Main / API ──────────────────────────────────────────────────────────────

def ejecutar_etl(
    carpeta_path: str | list[str] = DEFAULT_CARPETAS,
    db_path: str = DEFAULT_DB,
    forzar: bool = False,
    verbose: bool = False,
) -> dict:
    if verbose:
        log.setLevel(logging.DEBUG)

    # Acepta tanto una sola carpeta (string) como una lista de carpetas
    carpetas_input = [carpeta_path] if isinstance(carpeta_path, str) else list(carpeta_path)

    carpetas_validas = []
    carpetas_no_encontradas = []
    for c in carpetas_input:
        p = Path(c)
        if p.exists():
            carpetas_validas.append(p)
        else:
            carpetas_no_encontradas.append(str(p))
            log.error("Carpeta no encontrada: %s", p)

    if not carpetas_validas:
        return {"error": f"Ninguna carpeta encontrada: {', '.join(carpetas_no_encontradas)}"}

    con = inicializar_db(db_path)
    extensiones = {".csv", ".xlsx", ".xls", ".parquet"}

    archivos = []
    for carpeta in carpetas_validas:
        archivos.extend(
            sorted(p for p in carpeta.rglob("*") if p.is_file() and p.suffix.lower() in extensiones)
        )

    total_nuevas = 0
    total_omitidos = 0
    total_saltados = 0

    for archivo in archivos:
        stat = archivo.stat()
        ruta_str = str(archivo.resolve())

        if not forzar and archivo_ya_procesado(con, ruta_str, stat.st_mtime_ns, stat.st_size):
            log.debug("Sin cambios, omitido: %s", archivo.name)
            total_saltados += 1
            continue

        try:
            df_raw = leer_archivo(archivo)
            if df_raw.empty:
                log.warning("Vacio: %s", archivo.name)
                total_omitidos += 1
                continue

            # origen relativo a la carpeta base que le corresponde a este archivo
            carpeta_base = next(c for c in carpetas_validas if archivo.is_relative_to(c))
            origen = archivo.relative_to(carpeta_base).as_posix()

            df = transformar_df(df_raw, origen)
            filas_nuevas = insertar_registros_safe(con, df)
            con.commit()
            registrar_archivo(con, ruta_str, stat.st_mtime_ns, stat.st_size, filas_nuevas)
            con.commit()
            total_nuevas += filas_nuevas
            log.info("%-50s  +%d registros nuevos", archivo.name, filas_nuevas)
        except Exception as e:
            log.error("Error en %s: %s", archivo.name, e)
            total_omitidos += 1

    con.close()

    resumen = {
        "procesados": len(archivos) - total_saltados - total_omitidos,
        "sin_cambios": total_saltados,
        "con_error": total_omitidos,
        "nuevas": total_nuevas,
        "db": db_path,
    }
    if carpetas_no_encontradas:
        resumen["advertencia"] = f"No encontradas: {', '.join(carpetas_no_encontradas)}"
    return resumen

def ejecutar_etl_pagos(carpeta_pagos: str, archivo_consolidado: str, db_path: str = DEFAULT_DB) -> dict:
    con = inicializar_db(db_path)
    catalogo = cargar_catalogo(Path(DEFAULT_CATALOG))

    df_unificado = leer_carpeta_pagos(carpeta_pagos)
    if df_unificado.empty:
        con.close()
        return {"error": "No se encontraron archivos en la carpeta de pagos"}

    df_consolidado = cargar_consolidado_pagos(archivo_consolidado)
    df_final = transformar_pagos_x_asesor(df_unificado, catalogo, df_consolidado)
    nuevas = insertar_pagos_x_asesor(con, df_final)
    con.close()
    return {"filas_procesadas": len(df_final), "filas_nuevas_o_actualizadas": nuevas}

def main() -> int:
    parser = argparse.ArgumentParser(description="ETL incremental de gestiones a SQLite")
    parser.add_argument("--carpeta", default=DEFAULT_CARPETAS)
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument(
        "--forzar",
        action="store_true",
        help="Reimporta todos los archivos aunque no hayan cambiado",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    res = ejecutar_etl(
        carpeta_path=args.carpeta,
        db_path=args.db,
        forzar=args.forzar,
        verbose=args.verbose,
    )
    resultado = ejecutar_etl_pagos(
    carpeta_pagos=r"C:\Users\elite\OneDrive\Desktop\Pagos - Productividad",
    archivo_consolidado=r"C:\Users\elite\OneDrive\Desktop\Claro\4.Pagos\Consolidado de pagos Claro.xlsx",
    )
    print(resultado)

    if "error" in res:
        return 1

    print(f"\nResumen ETL")
    print(f"  Archivos procesados : {res['procesados']}")
    print(f"  Archivos sin cambios: {res['sin_cambios']}")
    print(f"  Archivos con error  : {res['con_error']}")
    print(f"  Registros nuevos    : {res['nuevas']}")
    print(f"  DB                  : {res['db']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

