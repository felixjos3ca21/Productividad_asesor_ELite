import json
import pandas as pd
from pathlib import Path
display = lambda x: x  # Para evitar error en entorno sin Jupyter


json_path = Path("asesores_catalogo.json")



def guardar_catalogo(catalogo: dict, path: Path = json_path) -> None:

    path.write_text(json.dumps(catalogo, ensure_ascii=False, indent=2), encoding="utf-8")



def cargar_catalogo(path: Path = json_path) -> dict:

    if path.exists():

        return json.loads(path.read_text(encoding="utf-8-sig"))

    # Si no existe, inicia catalogo vacio persistente.

    catalogo = {}

    guardar_catalogo(catalogo, path)

    return catalogo



def normalizar_usuario(usuario: str) -> str:

    return str(usuario).strip().lower().replace(" ", ".")




def crear_asesor(usuario: str, nombre_asesor: str, campo: str, catalogo: dict, desde: str) -> None:
    u = normalizar_usuario(usuario)
    nueva_vigencia = {"desde": desde, "hasta": None, "Nombre_Asesor": nombre_asesor.strip(), "Campo": campo.strip()}
    if u not in catalogo:
        catalogo[u] = {"vigencias": [nueva_vigencia]}
    else:
        for v in catalogo[u]["vigencias"]:
            if v["hasta"] is None:
                v["hasta"] = str(pd.Timestamp(desde) - pd.Timedelta(days=1))[:10]
        catalogo[u]["vigencias"].append(nueva_vigencia)
    guardar_catalogo(catalogo)



def actualizar_asesor(usuario: str, catalogo: dict, nombre_asesor=None, campo=None) -> None:
    u = normalizar_usuario(usuario)
    if u not in catalogo:
        raise ValueError(f"No existe el asesor: {u}")
    vigente = next((v for v in catalogo[u]["vigencias"] if v["hasta"] is None), None)
    if vigente is None:
        raise ValueError(f"No hay vigencia abierta para: {u}")
    if nombre_asesor is not None:
        vigente["Nombre_Asesor"] = str(nombre_asesor).strip()
    if campo is not None:
        vigente["Campo"] = str(campo).strip()
    guardar_catalogo(catalogo)



def borrar_asesor(usuario: str, catalogo: dict) -> None:

    u = normalizar_usuario(usuario)

    if u not in catalogo:

        raise ValueError(f"No existe el asesor: {u}")

    del catalogo[u]

    guardar_catalogo(catalogo)



def ver_catalogo(catalogo: dict) -> pd.DataFrame:
    cols = ["usuario_mejor_gestion", "desde", "hasta", "Nombre_Asesor", "Campo"]
    if not catalogo:
        df = pd.DataFrame(columns=cols + ["vigente"])
        return df
    filas = []
    for usuario, datos in catalogo.items():
        for v in datos["vigencias"]:
            filas.append({"usuario_mejor_gestion": usuario, **v})
    df = pd.DataFrame(filas, columns=cols)
    df["desde"] = pd.to_datetime(df["desde"], errors="coerce")
    df["hasta"] = pd.to_datetime(df["hasta"], errors="coerce")
    df["vigente"] = df["hasta"].isna()
    return df.sort_values(["Campo", "Nombre_Asesor", "usuario_mejor_gestion"]).reset_index(drop=True)



def aplicar_homologacion(df_base: pd.DataFrame, catalogo: dict) -> pd.DataFrame:

    if "usuario_mejor_gestion" not in df_base.columns:

        raise ValueError("La columna 'usuario_mejor_gestion' no existe en el DataFrame.")



    base = df_base.copy()

    # Permite reejecutar la celda sin crear sufijos _x/_y.

    cols_a_reemplazar = [c for c in ["Nombre_Asesor", "Campo"] if c in base.columns]

    if cols_a_reemplazar:

        base = base.drop(columns=cols_a_reemplazar)

    mapa_df = ver_catalogo(catalogo)
    mapa_df = mapa_df.loc[mapa_df["vigente"], ["usuario_mejor_gestion", "Nombre_Asesor", "Campo"]]

    salida = base.merge(mapa_df, on="usuario_mejor_gestion", how="left")

    salida["Nombre_Asesor"] = salida["Nombre_Asesor"].fillna(salida["usuario_mejor_gestion"])

    salida["Campo"] = salida["Campo"].fillna("Pendiente")

    return salida



# Cargar catalogo persistente

asesores_catalogo = cargar_catalogo()

print(f"Catalogo cargado: {len(asesores_catalogo)} asesores")

display(ver_catalogo(asesores_catalogo).head(50))




if __name__ == "__main__":
    asesores_catalogo = cargar_catalogo()
    print(f"Catalogo cargado: {len(asesores_catalogo)} asesores")
    display(ver_catalogo(asesores_catalogo).head(50))
