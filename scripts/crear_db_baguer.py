import sqlite3
from pathlib import Path
import pandas as pd

# Ruta por defecto para la base de datos
DB_PATH = Path("gestiones_baguer.db")

def inicializar_base_datos(ruta_bd: Path = DB_PATH) -> None:
    # Conectar o crear el archivo de la base de datos
    conexion = sqlite3.connect(ruta_bd)
    cursor = conexion.cursor()
    
    # Definir la estructura de la tabla productividad
    # Se usa TEXT para la mayoría para evitar choques de tipos al insertar desde Pandas,
    # a excepción de valores claramente numéricos.
    query_creacion = """
    CREATE TABLE IF NOT EXISTS productividad (
        id_registro TEXT PRIMARY KEY,
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
        intentosmarcacion INTEGER,
        gestion TEXT,
        motivo_no_pago TEXT,
        accion TEXT,
        codllamada TEXT,
        contacto TEXT,
        usuario_mejor_gestion TEXT,
        fecha_mejor_gestion TEXT,
        Nombre_Asesor TEXT,
        Fecha TEXT,
        Hora TEXT,
        Tiempo_Gestion TEXT,
        Tiempo_Llamada TEXT,
        Identificacion_limpia TEXT,
        Cuenta_limpia TEXT,
        Fecha_Promesa_limpia TEXT
    );
    """
    
    cursor.execute(query_creacion)
    conexion.commit()
    conexion.close()


    
def guardar_df_en_bd(df, tabla="productividad", ruta_bd=DB_PATH) -> int:
    conexion = sqlite3.connect(ruta_bd)
    cursor = conexion.cursor()
    
    # 1. Guardar el DF en una tabla temporal
    tabla_temp = f"temp_{tabla}"
    df.to_sql(tabla_temp, conexion, if_exists="replace", index=False)
    
    # 2. Insertar ignorando los id_registro que ya existan
    query_upsert = f"""
        INSERT OR IGNORE INTO {tabla}
        SELECT * FROM {tabla_temp};
    """
    cursor.execute(query_upsert)
    
    # Cuántos registros se insertaron realmente
    registros_nuevos = cursor.rowcount
    
    # 3. Eliminar la tabla temporal y guardar cambios
    cursor.execute(f"DROP TABLE {tabla_temp};")
    conexion.commit()
    conexion.close()
    
    return registros_nuevos

def cargar_datos_productividad(ruta_bd: Path = DB_PATH) -> pd.DataFrame:
    conexion = sqlite3.connect(ruta_bd)
    df = pd.read_sql("SELECT * FROM productividad", conexion, parse_dates=["fechagestion"])
    conexion.close()
    return df