import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import json

# ==============================
# CONFIGURACIÓN DESDE SECRETS
# ==============================
CLASES_SHEET_ID = st.secrets["google"]["clases_sheet_id"]   # ID de "CLASES 2026" (Google Sheet)
ASISTENCIA_SHEET_ID = st.secrets["google"]["asistencia_sheet_id"]  # ID de "Asistencia 2026"

def get_google_client():
    creds_dict = json.loads(st.secrets["google"]["credentials"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=[
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ])
    return gspread.authorize(creds)

# ==============================
# CARGAR CURSOS DESDE GOOGLE SHEETS
# ==============================
@st.cache_data(ttl=300)  # Cache por 5 minutos
def load_courses_from_gsheets():
    client = get_google_client()
    clases_sheet = client.open_by_key(CLASES_SHEET_ID)
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
            reading_fechas = False
            reading_estudiantes = False

            for row in all_values:
                if len(row) == 0:
                    continue
                cell = row[0].strip() if row[0] else ""
                
                if cell == "profesor:" and len(row) > 1:
                    data["profesor"] = row[1].strip()
                elif cell == "dia:" and len(row) > 1:
                    data["dia"] = row[1].strip()
                elif cell == "horario" and len(row) > 1:
                    data["horario"] = row[1].strip()
                elif cell == "fecha:":
                    reading_fechas = True
                    reading_estudiantes = False
                    # Fechas pueden estar en la misma fila o siguientes
                    fechas = [f.strip() for f in row[1:] if f.strip()]
                elif reading_fechas and cell == "":
                    # Continuar leyendo fechas en filas siguientes si hay más columnas
                    if len(row) > 1:
                        fechas.extend([f.strip() for f in row[1:] if f.strip()])
                    else:
                        reading_fechas = False
                        reading_estudiantes = True
                elif cell and any(c.isalpha() for c in cell):
                    # Es un nombre de estudiante
                    estudiantes.append(cell)
                    reading_estudiantes = True
                elif reading_estudiantes and cell == "" and len(row) > 0 and row[0]:
                    # Caso raro: estudiante en celda no primera
                    pass

            # Si no se encontraron fechas, intentar desde fila 4
            if not fechas:
                if len(all_values) > 4:
                    fechas = [f.strip() for f in all_values[4][1:] if f.strip()]

            # Si no hay estudiantes, tomar desde fila 5 en adelante, columna A
            if not estudiantes:
                for i in range(5, len(all_values)):
                    if len(all_values[i]) > 0 and all_values[i][0].strip():
                        val = all_values[i][0].strip()
                        if any(c.isalpha() for c in val):
                            estudiantes.append(val)

            if "profesor" in data and estudiantes:
                data["fechas"] = fechas or ["Sin fechas"]
                data["estudiantes"] = estudiantes
                courses[sheet_name] = data

        except Exception as e:
            st.warning(f"⚠️ Error en hoja '{sheet_name}': {str(e)[:100]}")
            continue

    return courses

# ==============================
# APP PRINCIPAL
# ==============================
st.set_page_config(page_title="Asistencia Cursos 2026", layout="centered")
st.title("✅ Registro de Asistencia – Cursos 2026")

courses = load_courses_from_gsheets()

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
        client = get_google_client()
        asistencia_sheet = client.open_by_key(ASISTENCIA_SHEET_ID)
        
        # Usar hoja con nombre del curso
        sheet_name = curso_seleccionado
        try:
            sheet = asistencia_sheet.worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            sheet = asistencia_sheet.add_worksheet(title=sheet_name, rows=100, cols=5)
            sheet.append_row(["Curso", "Fecha", "Estudiante", "Asistencia", "Hora Registro"])
        
        rows = []
        for estudiante, presente in asistencia.items():
            rows.append([
                curso_seleccionado,
                fecha_seleccionada,
                estudiante,
                1 if presente else 0,
                st.session_state.get('timestamp', '') or 
                __import__('datetime').datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ])
        
        sheet.append_rows(rows)
        st.success(f"✅ Asistencia guardada en la hoja '{sheet_name}'!")
    except Exception as e:
        st.error(f"❌ Error al guardar: {e}")