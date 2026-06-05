from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def leer_csv_robusto(path_csv: Path) -> pd.DataFrame:
    encodings = ["utf-8", "utf-8-sig", "cp1252", "latin-1"]
    separadores = [None, ";", ",", "\t", "|"]
    ultimo_error = None

    for enc in encodings:
        for sep in separadores:
            try:
                return pd.read_csv(
                    path_csv,
                    encoding=enc,
                    sep=sep,
                    engine="python",
                    on_bad_lines="skip",
                )
            except Exception as e:
                ultimo_error = e

    raise RuntimeError(f"No se pudo leer CSV: {ultimo_error}")


def leer_carpeta_tabular(carpeta: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not carpeta.exists() or not carpeta.is_dir():
        return pd.DataFrame(), pd.DataFrame(columns=["archivo", "error"])

    extensiones = {".csv", ".xlsx", ".xls", ".json", ".parquet"}
    archivos = sorted([p for p in carpeta.rglob("*") if p.is_file() and p.suffix.lower() in extensiones])

    dfs = []
    omitidos: list[tuple[str, str]] = []

    for archivo in archivos:
        try:
            sufijo = archivo.suffix.lower()
            if sufijo == ".csv":
                tmp = leer_csv_robusto(archivo)
            elif sufijo in {".xlsx", ".xls"}:
                tmp = pd.read_excel(archivo)
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

    if not dfs:
        return pd.DataFrame(), pd.DataFrame(omitidos, columns=["archivo", "error"])

    df = pd.concat(dfs, ignore_index=True, sort=False)
    return df, pd.DataFrame(omitidos, columns=["archivo", "error"])


def primera_columna(df_base: pd.DataFrame, candidatas: list[str]):
    for c in candidatas:
        if c in df_base.columns:
            return c
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
    col_id = primera_columna(df, ["Identificacion", "identification", "identificacion"])
    col_cuenta = primera_columna(df, ["Cuenta", "cuenta"])

    if col_fecha:
        df["Fecha"] = pd.to_datetime(df[col_fecha], errors="coerce").dt.normalize()
    if col_hora:
        df["Hora"] = a_hora_hhmmss(df[col_hora])
    if col_id:
        df["Identificacion"] = df[col_id].astype("string").str.strip()
    if col_cuenta:
        df["Cuenta"] = df[col_cuenta].astype("string").str.replace("-", "", regex=False).str.strip()

    return df


def cargar_catalogo(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def construir_mapa_catalogo(catalogo: dict) -> pd.DataFrame:
    filas = []
    for asesor_gestion, cfg in catalogo.items():
        if not isinstance(cfg, dict):
            continue
        filas.append(
            {
                "asesor_gestion": asesor_gestion,
                "Nombre_Asesor": cfg.get("Nombre_Asesor", asesor_gestion),
                "Campo": cfg.get("Campo", "Pendiente"),
            }
        )
    if not filas:
        return pd.DataFrame(columns=["asesor_gestion", "Nombre_Asesor", "Campo"])
    return pd.DataFrame(filas)


def aplicar_homologacion(df_base: pd.DataFrame, catalogo: dict) -> pd.DataFrame:
    if "asesor_gestion" not in df_base.columns:
        base = df_base.copy()
        if "Nombre_Asesor" not in base.columns:
            base["Nombre_Asesor"] = "Sin asesor"
        if "Campo" not in base.columns:
            base["Campo"] = "Pendiente"
        return base

    base = df_base.copy()
    mapa_df = construir_mapa_catalogo(catalogo)
    if mapa_df.empty:
        base["Nombre_Asesor"] = base["asesor_gestion"]
        base["Campo"] = "Pendiente"
        return base

    out = base.merge(mapa_df, on="asesor_gestion", how="left")
    out["Nombre_Asesor"] = out["Nombre_Asesor"].fillna(out["asesor_gestion"])
    out["Campo"] = out["Campo"].fillna("Pendiente")
    return out


def deduplicar_por_llave_negocio(df_base: pd.DataFrame, col_asesor: str) -> pd.DataFrame:
    base = df_base.copy()
    cols_llave = [c for c in ["Fecha", "Hora", "Cuenta", col_asesor, "Identificacion"] if c in base.columns]
    if not cols_llave:
        return base

    for c in cols_llave:
        base[c] = base[c].astype("string").str.strip().fillna("")

    return base.drop_duplicates(subset=cols_llave, keep="first")


def _normalizar_na_texto(serie: pd.Series) -> pd.Series:
    out = serie.astype("string").str.strip()
    out = out.mask(out.isin(["", "<NA>", "nan", "None"]), pd.NA)
    return out


def calcular_deberia_llevar_por_fecha_asesor(df_base: pd.DataFrame) -> pd.DataFrame:
    """Replica la logica de la app: 25 cuentas/hora productiva menos cruce de almuerzo (12-13)."""
    required_cols = {"Fecha", "Asesor", "Hora"}
    if not required_cols.issubset(set(df_base.columns)):
        return pd.DataFrame(columns=["Fecha", "Asesor", "deberia_llevar"])

    base = df_base[["Fecha", "Asesor", "Hora"]].copy()
    base["Fecha"] = pd.to_datetime(base["Fecha"], errors="coerce").dt.normalize()
    base["Hora_td"] = pd.to_timedelta(base["Hora"].astype("string"), errors="coerce")
    base = base.dropna(subset=["Fecha", "Asesor", "Hora_td"])
    if base.empty:
        return pd.DataFrame(columns=["Fecha", "Asesor", "deberia_llevar"])

    primera = (
        base.groupby(["Fecha", "Asesor"], dropna=False)["Hora_td"]
        .min()
        .reset_index(name="primera_hora")
    )

    corte_por_fecha = base.groupby("Fecha", dropna=False)["Hora_td"].max()
    hoy = pd.Timestamp.now().normalize()
    ahora = pd.Timestamp.now()
    corte_hoy = pd.to_timedelta(f"{ahora.hour:02d}:{ahora.minute:02d}:{ahora.second:02d}")
    if hoy in corte_por_fecha.index:
        corte_por_fecha.loc[hoy] = corte_hoy

    primera["hora_corte"] = primera["Fecha"].map(corte_por_fecha)
    primera["total_transcurrido"] = (primera["hora_corte"] - primera["primera_hora"]).clip(lower=pd.Timedelta(0))

    inicio_almuerzo = pd.to_timedelta("12:00:00")
    fin_almuerzo = pd.to_timedelta("13:00:00")

    primera["fin_cruce"] = primera["hora_corte"].where(primera["hora_corte"] < fin_almuerzo, fin_almuerzo)
    primera["inicio_cruce"] = primera["primera_hora"].where(primera["primera_hora"] > inicio_almuerzo, inicio_almuerzo)
    primera["cruce_almuerzo"] = (primera["fin_cruce"] - primera["inicio_cruce"]).clip(lower=pd.Timedelta(0))
    primera.loc[primera["hora_corte"] <= inicio_almuerzo, "cruce_almuerzo"] = pd.Timedelta(0)

    horas_productivas = (primera["total_transcurrido"] - primera["cruce_almuerzo"]).clip(lower=pd.Timedelta(0))
    deberia = (horas_productivas.dt.total_seconds() / 3600.0) * 25.0
    deberia = deberia.clip(lower=0)
    primera["deberia_llevar"] = ((deberia / 5.0).round() * 5.0).fillna(0.0)

    return primera[["Fecha", "Asesor", "deberia_llevar"]]


def construir_vista_minima(df_base: pd.DataFrame) -> pd.DataFrame:
    df = df_base.copy()
    if "Fecha" not in df.columns:
        raise ValueError("No existe columna Fecha en los datos procesados")

    df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce").dt.normalize()

    col_asesor = "Nombre_Asesor" if "Nombre_Asesor" in df.columns else "asesor_gestion" if "asesor_gestion" in df.columns else None
    if col_asesor is None:
        raise ValueError("No existe columna de asesor (Nombre_Asesor/asesor_gestion)")

    df = df[df["Fecha"].notna()].copy()
    if df.empty:
        return pd.DataFrame()

    if "Cuenta" not in df.columns:
        df["Cuenta"] = pd.NA
    if "Identificacion" not in df.columns:
        df["Identificacion"] = pd.NA
    if "Hora" not in df.columns:
        df["Hora"] = pd.NA

    df["Asesor"] = df[col_asesor].astype("string").fillna("Sin asesor")
    df["Campo"] = df["Campo"].astype("string").fillna("Todos") if "Campo" in df.columns else "Todos"
    if "Marca" in df.columns:
        df["Marca"] = df["Marca"].astype("string").fillna("Todas")
    else:
        df["Marca"] = "Todas"

    df["Cuenta"] = _normalizar_na_texto(df["Cuenta"])
    df["Identificacion"] = _normalizar_na_texto(df["Identificacion"])
    df["Hora"] = df["Hora"].astype("string").str.strip().fillna("")

    perfil_norm = df["ultimo_perfil_cliente"].astype("string").str.strip().str.lower() if "ultimo_perfil_cliente" in df.columns else pd.Series("", index=df.index, dtype="string")

    perfiles_contacto_directo = {
        "pago parcial",
        "contesta y cuelga",
        "ya pago",
        "promesa de pago",
        "renuente",
        "llamar luego",
        "no hubo acuerdo",
        "colgo",
        "voluntad de pago",
        "promesa de pago con descuento",
        "no es el encargado del pago",
        "promesa con tercero",
        "dificultad de pago",
        "pago no abonado",
        "reclamacion",
        "recordatorio",
        "encargado renuente",
        "promesa whatsapp",
        "abono",
        "al dia",
    }
    perfiles_contacto_indirecto = {
        "equivocado",
        "mensaje con tercero",
        "tercero no conoce al titular",
        "tercero no toma mensaje",
        "fallecio",
    }
    perfiles_no_contacto = {"no contesta", "mensaje en buzon", "no contacto", "ilocalizado"}
    perfiles_promesas = {"promesa de pago", "promesa de pago con descuento", "promesa con tercero"}

    df["llave_gestion_unica"] = df["Cuenta"].astype("string").fillna("") + "|" + df["Hora"].astype("string").fillna("")

    group_cols = ["Fecha", "Asesor"]

    resumen_gestiones = df.groupby(group_cols, dropna=False)["llave_gestion_unica"].nunique().reset_index(name="cuentas_gestionadas")
    resumen_gest_cuentas = df.groupby(group_cols, dropna=False)["Cuenta"].nunique(dropna=True).reset_index(name="Gest_cuentas")
    resumen_clientes = df.groupby(group_cols, dropna=False)["Identificacion"].nunique(dropna=True).reset_index(name="clientes_Gestionados")

    resumen_contacto_directo = (
        df.loc[perfil_norm.isin(perfiles_contacto_directo)]
        .groupby(group_cols, dropna=False)["Cuenta"]
        .nunique(dropna=True)
        .reset_index(name="contacto_directo")
    )
    resumen_contacto_indirecto = (
        df.loc[perfil_norm.isin(perfiles_contacto_indirecto)]
        .groupby(group_cols, dropna=False)["Cuenta"]
        .nunique(dropna=True)
        .reset_index(name="contacto_indirecto")
    )
    resumen_no_contacto = (
        df.loc[perfil_norm.isin(perfiles_no_contacto)]
        .groupby(group_cols, dropna=False)["Cuenta"]
        .nunique(dropna=True)
        .reset_index(name="no_contacto")
    )
    resumen_promesas = (
        df.loc[perfil_norm.isin(perfiles_promesas)]
        .groupby(group_cols, dropna=False)["Cuenta"]
        .nunique(dropna=True)
        .reset_index(name="Promesas")
    )

    col_valorpromesa = "valorpromesa" if "valorpromesa" in df.columns else "valor_promesa" if "valor_promesa" in df.columns else None
    if col_valorpromesa:
        tmp_valor = df[group_cols + ["Cuenta", col_valorpromesa]].copy()
        tmp_valor[col_valorpromesa] = pd.to_numeric(tmp_valor[col_valorpromesa], errors="coerce")
        min_por_cuenta = (
            tmp_valor.dropna(subset=["Cuenta"])
            .groupby(group_cols + ["Cuenta"], dropna=False)[col_valorpromesa]
            .min()
            .reset_index(name="min_valor_cuenta")
        )
        resumen_valor_promesa = (
            min_por_cuenta.groupby(group_cols, dropna=False)["min_valor_cuenta"]
            .sum(min_count=1)
            .reset_index(name="valor_promesa")
        )
    else:
        resumen_valor_promesa = pd.DataFrame(columns=group_cols + ["valor_promesa"])

    resumen = (
        resumen_gestiones.merge(resumen_gest_cuentas, on=group_cols, how="outer")
        .merge(resumen_clientes, on=group_cols, how="outer")
        .merge(resumen_contacto_directo, on=group_cols, how="outer")
        .merge(resumen_contacto_indirecto, on=group_cols, how="outer")
        .merge(resumen_no_contacto, on=group_cols, how="outer")
        .merge(resumen_promesas, on=group_cols, how="outer")
        .merge(resumen_valor_promesa, on=group_cols, how="outer")
        .fillna(0)
    )

    deberia_df = calcular_deberia_llevar_por_fecha_asesor(df[["Fecha", "Asesor", "Hora"]])
    resumen = resumen.merge(deberia_df, on=group_cols, how="left")
    resumen["deberia_llevar"] = pd.to_numeric(resumen["deberia_llevar"], errors="coerce").fillna(0)
    resumen["Campo"] = "Todos"
    resumen["Marca"] = "Todas"

    for c in [
        "cuentas_gestionadas",
        "Gest_cuentas",
        "clientes_Gestionados",
        "contacto_directo",
        "contacto_indirecto",
        "no_contacto",
        "Promesas",
    ]:
        resumen[c] = pd.to_numeric(resumen[c], errors="coerce").fillna(0).astype(int)

    resumen["valor_promesa"] = pd.to_numeric(resumen["valor_promesa"], errors="coerce").fillna(0)
    resumen["deberia_llevar"] = pd.to_numeric(resumen["deberia_llevar"], errors="coerce").fillna(0)

    cols = [
        "Fecha",
        "Asesor",
        "Campo",
        "Marca",
        "cuentas_gestionadas",
        "Gest_cuentas",
        "deberia_llevar",
        "clientes_Gestionados",
        "contacto_directo",
        "contacto_indirecto",
        "no_contacto",
        "Promesas",
        "valor_promesa",
    ]

    out = resumen[cols].sort_values(["Fecha", "Asesor"]).reset_index(drop=True)
    out["Fecha"] = pd.to_datetime(out["Fecha"], errors="coerce").dt.strftime("%Y-%m-%d")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Genera productividad_view.json anonimizado para despliegue web")
    parser.add_argument("--input-folder", required=True, help="Carpeta local con archivos fuente")
    parser.add_argument("--catalog", default="asesores_catalogo.json", help="Ruta al catalogo de asesores")
    parser.add_argument("--output", default="productividad_view.json", help="Archivo JSON de salida")
    args = parser.parse_args()

    carpeta = Path(args.input_folder)
    catalogo_path = Path(args.catalog)
    output_path = Path(args.output)

    df_raw, df_omitidos = leer_carpeta_tabular(carpeta)
    if df_raw.empty:
        print("No se encontraron datos para procesar.")
        if not df_omitidos.empty:
            print(df_omitidos.to_string(index=False))
        return 1

    df = transformar_df(df_raw)
    catalogo = cargar_catalogo(catalogo_path)
    df = aplicar_homologacion(df, catalogo)

    col_asesor = "Nombre_Asesor" if "Nombre_Asesor" in df.columns else "asesor_gestion" if "asesor_gestion" in df.columns else "Asesor"
    df = deduplicar_por_llave_negocio(df, col_asesor)
    vista = construir_vista_minima(df)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(vista.to_json(orient="records", force_ascii=False, indent=2), encoding="utf-8")

    print(f"Vista generada: {output_path} ({len(vista)} filas)")
    if not df_omitidos.empty:
        print(f"Archivos omitidos: {len(df_omitidos)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
