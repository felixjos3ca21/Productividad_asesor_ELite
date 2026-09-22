import sqlite3
import hashlib
import pandas as pd

DB_PATH = "gestiones_dupree.db"

def crear_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS gestiones (
            hash_fila TEXT PRIMARY KEY,
            fechagestion TEXT,
            horagestion TEXT,
            tiempogestion TEXT,
            tiempollamada TEXT,
            identificacion TEXT,
            nombrecompleto TEXT,
            cuenta TEXT,
            asesor_gestion TEXT,
            asesor TEXT,
            perfil_historico TEXT,
            ultimo_perfil TEXT,
            valorpromesa REAL,
            fechapromesa TEXT,
            numeromarcado TEXT,
            intentosmarcacion TEXT,
            gestion TEXT,
            motivo_no_pago TEXT,
            accion TEXT,
            codllamada TEXT,
            contacto TEXT,
            usuario_mejor_gestion TEXT,
            fecha_mejor_perfil TEXT,
            fecha_carga TEXT
        )
    """)
    conn.commit()
    conn.close()

def generar_hash(row):
    base = f"{row['cuenta']}{row['horagestion']}{row['asesor']}"
    return hashlib.md5(base.encode("utf-8")).hexdigest()

def cargar_gestiones(df: pd.DataFrame):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    df["hash_fila"] = df.apply(generar_hash, axis=1)
    df = df.drop_duplicates(subset="hash_fila")  # dedup dentro del propio archivo

    cur.execute("SELECT hash_fila FROM gestiones")
    hashes_existentes = {r[0] for r in cur.fetchall()}

    df_nuevos = df[~df["hash_fila"].isin(hashes_existentes)].copy()

    if not df_nuevos.empty:
        df_nuevos["fecha_carga"] = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
        df_nuevos.to_sql("gestiones", conn, if_exists="append", index=False)

    conn.close()
    return len(df_nuevos)

if __name__ == "__main__":
    crear_db()