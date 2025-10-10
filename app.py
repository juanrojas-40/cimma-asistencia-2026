import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import json
from datetime import datetime

# ==============================
# Conexión a Google Sheets (usando Secrets)
# ==============================
@st.cache_resource
def get_client():
    creds_dict = json.loads(st.secrets["google"]["credentials"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=[
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ])
    return gspread.authorize(creds)

# ==============================
# Cargar cursos desde "CLASES 2026" (Google Sheet)
# ==============================
@st.cache_data(ttl=300)
def load_courses():
    client = get_client()
    clases_sheet = client.open_by_key(st.secrets["google"]["clases_sheet_id"])
    courses = {}

    for worksheet in clases_sheet.worksheets():
        sheet_name = worksheet.title
        try:
            # Leer solo la primera columna (A)
            colA_raw = worksheet.col_values(1)  # Columna A
            colA = [cell.strip() for cell in colA_raw if isinstance(cell, str)]
            colA_lower = [s.lower() for s in colA]

            def find_next_value(key):
                try:
                    idx = colA_lower.index(key)
                    for i in range(idx + 1, len(colA)):
                        if colA[i]:
                            return colA[i]
                    return ""
                except ValueError:
                    return ""

            profesor = find_next_value("profesor:")
            dia = find_next_value("dia:")
            horario = find_next_value("horario")

            # Extraer fechas y estudiantes
            fechas = []
            estudiantes = []
            try:
                fecha_idx = colA_lower.index("fecha:")
                for i in range(fecha_idx + 1, len(colA)):
                    val = colA[i]
                    if val and any(c.isalpha() for c in val) and not val.lower().startswith(("profesor", "dia", "horario", "fecha")):
                        estudiantes.append(val)
                    elif val and not any(c.isalpha() for c in val):
                        fechas.append(val)
            except ValueError:
                pass

            if profesor and dia and horario and estudiantes:
                courses[sheet_name] = {
                    "profesor": profesor,
                    "dia": dia,
                    "horario": horario,
                    "fechas": fechas or ["Sin fechas"],
                    "estudiantes": estudiantes
                }
        except Exception as e:
            st.warning(f"⚠️ Error en hoja '{sheet_name}': {str(e)[:80]}")
            continue

    return courses

# ==============================
# APP PRINCIPAL
# ==============================
st.set_page_config(page_title="Asistencia Cursos 2026", layout="centered")
st.title("✅ Registro de Asistencia – Cursos 2026")

courses = load_courses()

if not courses:
    st.error("❌ No se encontraron cursos en 'CLASES 2026'.")
    st.stop()

curso_seleccionado = st.selectbox("Selecciona el curso", list(courses.keys()))
data = courses[curso_seleccionado]

st.write(f"**Profesor:** {data['profesor']}")
st.write(f"**Día:** {data['dia']} | **Horario:** {data['horario']}")

fecha_seleccionada = st.selectbox("Selecciona la fecha", data["fechas"])

st.header("📋 Estudiantes")
asistencia = {}
for est in data["estudiantes"]:
    asistencia[est] = st.checkbox(est, key=f"{curso_seleccionado}_{est}")

if st.button("💾 Guardar Asistencia"):
    try:
        client = get_client()
        asistencia_sheet = client.open_by_key(st.secrets["google"]["asistencia_sheet_id"])

        # Usar hoja con nombre del curso
        try:
            sheet = asistencia_sheet.worksheet(curso_seleccionado)
        except gspread.exceptions.WorksheetNotFound:
            sheet = asistencia_sheet.add_worksheet(title=curso_seleccionado, rows=100, cols=5)
            sheet.append_row(["Curso", "Fecha", "Estudiante", "Asistencia", "Hora Registro"])

        rows = []
        for estudiante, presente in asistencia.items():
            rows.append([
                curso_seleccionado,
                fecha_seleccionada,
                estudiante,
                1 if presente else 0,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ])

        sheet.append_rows(rows)
        st.success(f"✅ Asistencia guardada en la hoja '{curso_seleccionado}'!")
    except Exception as e:
        st.error(f"❌ Error al guardar: {e}")