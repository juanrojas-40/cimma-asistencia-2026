import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ==============================
# CONFIGURACIÓN
# ==============================
GOOGLE_SHEET_ID = "1u-Ay1yJJUEtKdTdV2xXGVLAtWo09wk_LhuL69tNBJpc"  # ← ¡REEMPLAZA CON TU ID REAL!
EXCEL_FILE = "CLASES 2026.xlsx"

# ==============================
# FUNCIÓN: Conectar a Google Sheets
# ==============================
@st.cache_resource
def connect_to_sheet():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    client = gspread.authorize(creds)
    return client.open_by_key(GOOGLE_SHEET_ID)

# ==============================
# FUNCIÓN: Cargar cursos desde Excel (formato tabular)
# ==============================
@st.cache_data
def load_courses_from_excel():
    xls = pd.ExcelFile(EXCEL_FILE)
    courses = {}
    for sheet_name in xls.sheet_names:
        try:
            df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
            
            # Extraer datos clave de la columna B (índice 1)
            headers = df.iloc[:, 0].astype(str).str.strip().tolist()  # Columna A
            values = df.iloc[:, 1].astype(str).str.strip().tolist()  # Columna B
            
            data = {}
            for i, h in enumerate(headers):
                if h == "PROFESOR":
                    data["profesor"] = values[i]
                elif h == "DIA":
                    data["dia"] = values[i]
                elif h == "CURSO":
                    data["curso"] = values[i]
                elif h == "HORARIO":
                    data["horario"] = values[i]
            
            # Fechas: fila 4 (índice 4), desde columna B en adelante
            fechas_row = df.iloc[4, 1:].dropna().astype(str).tolist()
            data["fechas"] = [f.strip() for f in fechas_row]

            # Estudiantes: columna A, desde fila 5 en adelante
            estudiantes_col = df.iloc[5:, 0].dropna().astype(str).tolist()
            data["estudiantes"] = [e.strip() for e in estudiantes_col]

            courses[sheet_name] = data
        except Exception as e:
            st.warning(f"⚠️ Error al procesar hoja '{sheet_name}': {e}")
            continue
    return courses

# ==============================
# APP PRINCIPAL
# ==============================
st.set_page_config(page_title="Asistencia Cursos 2026", layout="centered")
st.title("✅ Registro de Asistencia – Cursos 2026")

courses = load_courses_from_excel()

if not courses:
    st.error("❌ No se encontraron cursos válidos en 'CLASES 2026.xlsx'.")
    st.stop()

curso_seleccionado = st.selectbox("Selecciona el curso", list(courses.keys()))
data = courses[curso_seleccionado]

st.write(f"**Profesor:** {data['profesor']}")
st.write(f"**Día:** {data['dia']} | **Horario:** {data['horario']}")
st.write(f"**Curso ID:** {data['curso']}")

fecha_seleccionada = st.selectbox("Selecciona la fecha", data["fechas"])

st.header("📋 Estudiantes")
st.write("Marca asistencia de los presentes:")
asistencia = {}
for est in data["estudiantes"]:
    asistencia[est] = st.checkbox(est, key=f"{curso_seleccionado}_{est}")

if st.button("💾 Guardar Asistencia"):
    try:
        # Conectarse a Google Sheets
        gs = connect_to_sheet()
        
        # Obtener la hoja correspondiente al curso seleccionado
        sheet_name = curso_seleccionado  # Ej: JR_1, JR_2
        try:
            sheet = gs.worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            # Si no existe, crearla
            sheet = gs.add_worksheet(title=sheet_name, rows="100", cols="5")
            # Escribir encabezados
            sheet.append_row(["Fecha", "Estudiante", "Asistencia", "Hora Registro"])
        
        # Preparar filas para guardar
        rows = []
        for estudiante, presente in asistencia.items():
            rows.append([data['curso'],
                fecha_seleccionada,
                estudiante,
                1 if presente else 0,
                pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
            ])
        
        sheet.append_rows(rows)
        st.success(f"✅ Asistencia guardada '{sheet_name}'!")
    except Exception as e:
        st.error(f"❌ Error al guardar: {e}")