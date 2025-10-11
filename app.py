import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import json
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

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
# Función para enviar correo
# ==============================
def send_email(to_email, subject, body):
    try:
        smtp_server = st.secrets["EMAIL"]["smtp_server"]
        smtp_port = int(st.secrets["EMAIL"]["smtp_port"])
        sender_email = st.secrets["EMAIL"]["sender_email"]
        sender_password = st.secrets["EMAIL"]["sender_password"]

        msg = MIMEMultipart()
        msg["From"] = sender_email
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.send_message(msg)

        return True
    except Exception as e:
        st.warning(f"⚠️ Error al enviar correo a {to_email}: {e}")
        return False

# ==============================
# Cargar cursos desde "CLASES 2026"
# ==============================
@st.cache_data(ttl=300)
def load_courses():
    client = get_client()
    clases_sheet = client.open_by_key(st.secrets["google"]["clases_sheet_id"])
    courses = {}

    for worksheet in clases_sheet.worksheets():
        sheet_name = worksheet.title
        try:
            colA_raw = worksheet.col_values(1)
            colA = [cell.strip() for cell in colA_raw if isinstance(cell, str) and cell.strip()]
            colA_upper = [s.upper() for s in colA]

            try:
                idx_prof = colA_upper.index("PROFESOR")
                profesor = colA[idx_prof + 1]
            except (ValueError, IndexError):
                continue

            try:
                idx_dia = colA_upper.index("DIA")
                dia = colA[idx_dia + 1]
            except (ValueError, IndexError):
                continue

            try:
                idx_curso = colA_upper.index("CURSO")
                curso_id = colA[idx_curso + 1]
                horario = colA[idx_curso + 2]
            except (ValueError, IndexError):
                continue

            try:
                idx_fechas = colA_upper.index("FECHAS")
                idx_estudiantes = colA_upper.index("NOMBRES ESTUDIANTES")

                fechas = []
                for i in range(idx_fechas + 1, idx_estudiantes):
                    if i < len(colA):
                        fechas.append(colA[i])

                estudiantes = []
                for i in range(idx_estudiantes + 1, len(colA)):
                    estudiantes.append(colA[i])

            except (ValueError, IndexError):
                fechas = ["Sin fechas"]
                estudiantes = []

            if profesor and dia and horario and estudiantes:
                courses[sheet_name] = {
                    "profesor": profesor,
                    "dia": dia,
                    "horario": horario,
                    "curso_id": curso_id,
                    "fechas": fechas,
                    "estudiantes": estudiantes
                }

        except Exception as e:
            st.warning(f"⚠️ Error en hoja '{sheet_name}': {str(e)[:80]}")
            continue

    return courses

# ==============================
# Cargar correos desde hoja "MAILS"
# ==============================
@st.cache_data(ttl=3600)  # Cache por 1 hora
def load_emails():
    client = get_client()
    asistencia_sheet = client.open_by_key(st.secrets["google"]["asistencia_sheet_id"])
    mails_sheet = asistencia_sheet.worksheet("MAILS")

    data = mails_sheet.get_all_records()
    emails = {}
    for row in data:
        nombre = row.get("NOMBRE ESTUDIANTE", "").strip().lower()
        mail_estudiante = row.get("MAIL ESTUDIANTE", "").strip()
        mail_apoderado = row.get("MAIL APODERADO", "").strip()

        # Usamos el mail del apoderado si está disponible, sino el del estudiante
        email_to_use = mail_apoderado if mail_apoderado else mail_estudiante

        if email_to_use:
            emails[nombre] = email_to_use

    return emails

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

        # ==============================
        # ENVIAR CORREOS
        # ==============================
        st.info("📩 Enviando correos de confirmación...")

        # Cargar correos
        emails = load_emails()

        # Para cada estudiante, enviar correo
        for estudiante, presente in asistencia.items():
            # Normalizar nombre para buscar en la tabla de correos
            nombre_lower = estudiante.strip().lower()

            # Buscar correo
            correo_destino = emails.get(nombre_lower)
            if not correo_destino:
                st.warning(f"📧 No se encontró correo para: {estudiante}")
                continue

            # Preparar mensaje
            estado = "✅ ASISTIÓ" if presente else "❌ NO ASISTIÓ"
            subject = f"Reporte de Asistencia - Curso {curso_seleccionado} - {fecha_seleccionada}"
            body = f"""
Hola,

Este es un reporte automático de asistencia para el curso **{curso_seleccionado}**.

📅 Fecha: {fecha_seleccionada}
👨‍🎓 Estudiante: {estudiante}
📌 Estado: {estado}

Saludos cordiales,
Equipo Académico
"""

            # Enviar correo
            if send_email(correo_destino, subject, body):
                st.success(f"📧 Correo enviado a: {correo_destino}")
            else:
                st.error(f"❌ Fallo al enviar a: {correo_destino}")

    except Exception as e:
        st.error(f"❌ Error al guardar o enviar correos: {e}")