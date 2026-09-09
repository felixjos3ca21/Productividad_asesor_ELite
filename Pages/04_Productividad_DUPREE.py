import streamlit as st
from pathlib import Path

_ICON = Path(__file__).parent / "scripts" / "image" / "icono.ico"
st.set_page_config(page_title="Productividad - DUPREE", layout="wide", page_icon=str(_ICON))


st.title("Productividad DUPREE")

st.write("Próximamente")