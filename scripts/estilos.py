import streamlit as st
import base64
from pathlib import Path

def fondo_logo():

    ruta = Path("scripts/image/Elite_icono_gris.png")

    with open(ruta, "rb") as f:
        data = base64.b64encode(f.read()).decode()

    st.markdown(
        f"""
        <style>

        .stApp {{
            background: transparent;
        }}

        .stApp::before {{
            content: "";
            position: fixed;
            inset: 0;

            background-image: url("data:image/png;base64,{data}");
            background-repeat: no-repeat;
            background-position: right top;
            background-size: 50%;
            opacity: 0.20;
            z-index: -1;
        }}

        </style>
        """,
        unsafe_allow_html=True,
    )

def imagen_sidebar():
    ruta = Path("scripts/image/Elite_gris.png")

    with open(ruta, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    st.sidebar.markdown("<br><br><br><br><br><br><br><br>", unsafe_allow_html=True)
    st.sidebar.image(f"data:image/png;base64,{data}", width='content')

def imagen_pages_logo():
    ruta = Path("scripts/image/Elite_H_color.png")

    with open(ruta, "rb") as f:
        data = base64.b64encode(f.read()).decode()

    st.markdown(f"""
    <div style="text-align:left; margin-bottom:20px;">
        <img src="data:image/png;base64,{data}" width="260">
    </div>
    """, unsafe_allow_html=True)
