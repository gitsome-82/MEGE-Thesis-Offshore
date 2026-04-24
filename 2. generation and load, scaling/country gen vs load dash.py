import pathlib
import sys

import streamlit as st

# Make the countries package importable regardless of working directory
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from countries.common import apply_css
from countries import germany, portugal

st.set_page_config(page_title="Offshore Wind vs Load", layout="wide")
apply_css()

st.title("Offshore Wind Generation vs Load Analysis")

country = st.selectbox("Country", ["Germany", "Portugal"])

if country == "Germany":
    germany.render()
elif country == "Portugal":
    portugal.render()
