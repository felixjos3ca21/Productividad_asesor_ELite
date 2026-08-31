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
pagina_productividad_baguer = st.Page(
    "Pages/03_productividad_BAGUER.py",
    title="Productividad BAGUER",
    icon=":material/insights:",
    
)

navegacion = st.navigation(
    [
        pagina_productividad,
        pagina_pagos_x_asesor,
        pagina_productividad_baguer,
    ]
)

# 3. Dibujamos los logos condicionalmente según la página activa
col1, col2, col3, col4, col5, col6 = st.columns(6)
with col1:
    st.image("scripts/image/Elite_H_color.png", width=600)

with col6:
    # Verificamos si la página actual es la de BAGUER
    if navegacion.title == "Productividad BAGUER":
        # Asegúrate de colocar el nombre real de tu imagen para Baguer aquí
        st.image("scripts/image/baguer_logo.png", width=200) 
    else:
        # Para todas las demás páginas, mostramos el logo de Claro
        st.image("scripts/image/logo_claro.png", width=200)

# 4. Finalmente, ejecutamos el contenido de la página seleccionada
navegacion.run()

imagen_sidebar()