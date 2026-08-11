import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st
from pathlib import Path
from scripts.estilos import imagen_sidebar
from scripts.estilos import fondo_logo

_ICON = Path(__file__).parent / "scripts" / "image" / "icono.ico"

st.set_page_config(page_title="Elite Abogados BPO", layout="wide", page_icon=str(_ICON))

fondo_logo()

col1, col2, col3, col4, col5, col6=st.columns(6)
with col1:
	st.image("scripts/image/Elite_H_color.png", width=300)
with col6:
	st.image("scripts/image/logo_claro.png", width=200)

pagina_productividad = st.Page(
    "Pages/01_productividad.py",
    title="Productividad",
    icon=":material/insights:",
    default=True,
)

pagina_pagos_x_asesor = st.Page(
    "Pages/02_pagos_x_asesor.py",
    title="Pagos por asesor",
    icon=":material/monetization_on:",
)

navegacion = st.navigation(
    [
        pagina_productividad,
        pagina_pagos_x_asesor,
    ]
)


navegacion.run()

imagen_sidebar()