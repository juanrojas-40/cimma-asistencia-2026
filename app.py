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
            # Leer todas las celdas
            all_values = worksheet.get_all_values()
            if not all_values:
                continue

            # Convertir a diccionario columna A -> columna B
            data = {}
            fechas = []
            estudiantes = []

            for row in all_values:
                if len(row) < 2:
                    continue
                key = row[0].strip().lower() if row[0] else ""
                value = row[1].strip() if len(row) > 1 and row[1] else ""

                if key == "profesor":
                    data["profesor"] = value
                elif key == "dia":
                    data["dia"] = value
                elif key == "horario":
                    data["horario"] = value
                elif key == "fechas":
                    # Las fechas están en la misma fila, desde columna C en adelante
                    fechas = [cell.strip() for cell in row[2:] if cell.strip()]
                elif key == "nombres estudiantes":
                    # Los estudiantes empiezan en la siguiente fila
                    start_row = all_values.index(row) + 1
                    for i in range(start_row, len(all_values)):
                        if len(all_values[i]) > 0 and all_values[i][0].strip():
                            estudiante = all_values[i][0].strip()
                            if any(c.isalpha() for c in estudiante):
                                estudiantes.append(estudiante)
                        else:
                            break

            if "profesor" in data and estudiantes:
                data["fechas"] = fechas or ["Sin fechas"]
                data["estudiantes"] = estudiantes
                courses[sheet_name] = data

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