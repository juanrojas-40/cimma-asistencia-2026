import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import json

# ==============================
# Conexión a Google Sheets
# ==============================
@st.cache_resource
def get_client():
    # En producción: usa st.secrets
    # En local: usa secrets.toml
    try:
        creds_dict = json.loads(st.secrets["google"]["credentials"])
    except:
        # Fallback para desarrollo local
        with open(".streamlit/secrets.toml", "r") as f:
            import toml
            secrets = toml.load(f)
            creds_dict = json.loads(secrets["google"]["credentials"])
    
    creds = Credentials.from_service_account_info(creds_dict, scopes=[
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ])
    return gspread.authorize(creds)

# ==============================
# Cargar cursos (solo nombres de hojas)
# ==============================
@st.cache_data
def load_sheet_names():
    client = get_client()
    sheet = client.open_by_key(st.secrets["google"]["clases_sheet_id"])
    return [ws.title for ws in sheet.worksheets()]

# ==============================
# Mostrar contenido de una hoja
# ==============================
@st.cache_data
def load_sheet_content(sheet_name):
    client = get_client()
    sheet = client.open_by_key(st.secrets["google"]["clases_sheet_id"]).worksheet(sheet_name)
    return sheet.get_all_values()

# ==============================
# APP PRINCIPAL
# ==============================
st.set_page_config(page_title="Prueba de carga", layout="centered")
st.title("✅ Prueba de carga de hojas")

sheet_names = load_sheet_names()
st.write("📚 Hojas disponibles:", sheet_names)

selected_sheet = st.selectbox("Selecciona una hoja", sheet_names)
content = load_sheet_content(selected_sheet)

st.write("📄 Contenido de la hoja:")
st.dataframe(content)