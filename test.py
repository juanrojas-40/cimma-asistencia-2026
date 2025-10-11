import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import json

@st.cache_resource
def get_client():
    creds_dict = json.loads(st.secrets["google"]["credentials"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=[
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ])
    return gspread.authorize(creds)

@st.cache_data
def load_courses():
    client = get_client()
    sheet = client.open_by_key(st.secrets["google"]["clases_sheet_id"])
    courses = {}
    for ws in sheet.worksheets():
        data = ws.get_all_values()
        if not data:
            continue
        # Procesar como en tu ejemplo
        courses[ws.title] = data
    return courses

st.title("Prueba")
try:
    courses = load_courses()
    st.write("✅ Cursos cargados:", list(courses.keys()))
except Exception as e:
    st.error(f"❌ Error: {e}")