import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st
from pathlib import Path
from scripts.estilos import imagen_sidebar
from scripts.estilos import fondo_logo

_ICON = Path(__file__).parent / "scripts" / "image" / "icono.ico"

st.set_page_config(page_title="Elite Abogados BPO", layout="wide", page_icon=str(_ICON))

fondo_logo()

pagina_productividad = st.Page(
    "Pages/01_productividad_CLARO.py",
    title="Productividad CLARO",
    icon=":material/insights:",
    default=True,
)

pagina_pagos_x_asesor = st.Page(
    "Pages/02_pagos_x_asesor.py",
    title="Pagos por asesor",
    icon=":material/monetization_on:",
)
pagina_productividad_baguer = st.Page(
    "Pages/03_productividad_BAGUER.py",
    title="Productividad BAGUER",
    icon=":material/insights:",
    
)

pagina_productividad_dupree = st.Page(
    "Pages/04_productividad_DUPREE.py",
    title="Productividad DUPREE",
    icon=":material/insights:", 
    
)

navegacion = st.navigation(
    [
        pagina_productividad,
        pagina_pagos_x_asesor,
        pagina_productividad_baguer,
        pagina_productividad_dupree,
    ]
)

# 3. Dibujamos los logos condicionalmente según la página activa
col1, col2, col3, col4, col5, col6 = st.columns(6)
with col1:
    st.image("scripts/image/Elite_H_color.png", width=800)

with col6:
    if navegacion.title == "Productividad BAGUER":
        st.image("scripts/image/baguer_logo.png", width=200) 
    elif navegacion.title == "Productividad DUPREE":
        st.image("scripts/image/dupree_logo.png", width=300)
    else:
        st.image("scripts/image/logo_claro.png", width=250)

# 4. Finalmente, ejecutamos el contenido de la página seleccionada
navegacion.run()

imagen_sidebar()