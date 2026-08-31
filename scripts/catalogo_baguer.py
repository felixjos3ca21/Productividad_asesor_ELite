import json
import pandas as pd
from pathlib import Path

json_path = Path("asesores_baguer.json")

def guardar_catalogo(catalogo: dict, path: Path = json_path) -> None:
    path.write_text(json.dumps(catalogo, ensure_ascii=False, indent=2), encoding="utf-8")

def cargar_catalogo(path: Path = json_path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    catalogo = {}
    guardar_catalogo(catalogo, path)
    return catalogo

def ver_catalogo(catalogo: dict) -> pd.DataFrame:
    if not catalogo:
        return pd.DataFrame(columns=["asesor_gestion", "Nombre_Asesor"])
    datos_planos = []
    for asesor, info in catalogo.items():
        nombre = asesor
        if "vigencias" in info and len(info["vigencias"]) > 0:
            nombre = info["vigencias"][0].get("Nombre_Asesor", asesor)
        datos_planos.append({"asesor_gestion": asesor, "Nombre_Asesor": nombre})
    return pd.DataFrame(datos_planos)

def aplicar_homologacion(df_base: pd.DataFrame, catalogo: dict) -> pd.DataFrame:
    if "asesor_gestion" not in df_base.columns:
        raise ValueError("La columna 'asesor_gestion' no existe en el DataFrame.")
    base = df_base.copy()
    cols_a_reemplazar = [c for c in ["Nombre_Asesor"] if c in base.columns]
    if cols_a_reemplazar:
        base = base.drop(columns=cols_a_reemplazar)
    mapa_df = ver_catalogo(catalogo)
    salida = base.merge(mapa_df, on="asesor_gestion", how="left")
    salida["Nombre_Asesor"] = salida["Nombre_Asesor"].fillna(salida["asesor_gestion"])
    return salida