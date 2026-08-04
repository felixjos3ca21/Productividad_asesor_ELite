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
    con.commit()
    return con


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


def main() -> int:
    parser = argparse.ArgumentParser(description="ETL incremental de gestiones a SQLite")
    parser.add_argument("--carpeta", default=DEFAULT_CARPETA)
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

