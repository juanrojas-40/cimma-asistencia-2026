import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import json
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import pytz

# ==============================
# CONFIGURACIÓN Y CONEXIONES
# ==============================

@st.cache_resource
def get_client():
    creds_dict = json.loads(st.secrets["google"]["credentials"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=[
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ])
    return gspread.authorize(creds)

def get_chile_time():
    chile_tz = pytz.timezone("America/Santiago")
    return datetime.now(chile_tz)

def send_email(to_email: str, subject: str, body: str) -> bool:
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
# CARGA DE DATOS (sin cambios)
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

                fechas = [colA[i] for i in range(idx_fechas + 1, idx_estudiantes) if i < len(colA)]
                estudiantes = [colA[i] for i in range(idx_estudiantes + 1, len(colA))]

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

@st.cache_data(ttl=3600)
def load_emails():
    try:
        client = get_client()
        asistencia_sheet = client.open_by_key(st.secrets["google"]["asistencia_sheet_id"])
        sheet_names = [ws.title for ws in asistencia_sheet.worksheets()]
        if "MAILS" not in sheet_names:
            st.error("❌ La hoja 'MAILS' no existe en 'Asistencia 2026'.")
            return {}, {}

        mails_sheet = asistencia_sheet.worksheet("MAILS")
        data = mails_sheet.get_all_records()
        if not data:
            st.warning("⚠️ La hoja 'MAILS' está vacía.")
            return {}, {}

        emails = {}
        nombres_apoderados = {}
        for row in data:
            nombre_estudiante = str(row.get("NOMBRE ESTUDIANTE", "")).strip().lower()
            nombre_apoderado = str(row.get("NOMBRE APODERADO", "")).strip()
            mail_apoderado = str(row.get("MAIL APODERADO", "")).strip()
            mail_estudiante = str(row.get("MAIL ESTUDIANTE", "")).strip()
            email_to_use = mail_apoderado if mail_apoderado else mail_estudiante
            if email_to_use and nombre_estudiante:
                emails[nombre_estudiante] = email_to_use
                nombres_apoderados[nombre_estudiante] = nombre_apoderado
        return emails, nombres_apoderados
    except Exception as e:
        st.error(f"❌ Error al cargar la hoja 'MAILS': {e}")
        return {}, {}

# ==============================
# APP PRINCIPAL (con bloque de asistencia táctil)
# ==============================

def main():
    st.set_page_config(
        page_title="Preuniversitario CIMMA : Asistencia Cursos 2026",
        page_icon="✅",
        layout="centered"
    )
    
    # Mostrar logo
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.image("https://raw.githubusercontent.com/juanrojas-40/asistencia-2026/main/LOGO.jpg", use_container_width=True)

    st.title("📱 Registro de Asistencia")
    st.subheader("Preuniversitario CIMMA 2026")

    courses = load_courses()
    if not courses:
        st.error("❌ No se encontraron cursos en 'CLASES 2026'.")
        st.stop()

    curso_seleccionado = st.selectbox("🎓 Selecciona tu curso", list(courses.keys()))
    data = courses[curso_seleccionado]

    st.markdown(f"**🧑‍🏫 Profesor(a):** {data['profesor']}")
    
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**📅 Día:** {data['dia']}")
    with col2:
        st.markdown(f"**⏰ Horario:** {data['horario']}")

    clase_realizada = st.radio(
        "✅ ¿Se realizó la clase?",
        ("Sí", "No"),
        index=0,
        help="Selecciona 'No' en caso de feriado, suspensión o imprevisto."
    )

    if clase_realizada == "No":
        motivo = st.text_area(
            "📝 Motivo de la no realización",
            placeholder="Ej: Feriado nacional, suspensión por evento escolar, emergencia, etc."
        )
        fecha_seleccionada = st.selectbox("🗓️ Fecha afectada", data["fechas"])
        
        if st.button("💾 Registrar suspensión", use_container_width=True):
            try:
                client = get_client()
                asistencia_sheet = client.open_by_key(st.secrets["google"]["asistencia_sheet_id"])
                try:
                    sheet = asistencia_sheet.worksheet(curso_seleccionado)
                except gspread.exceptions.WorksheetNotFound:
                    sheet = asistencia_sheet.add_worksheet(title=curso_seleccionado, rows=100, cols=6)
                    sheet.append_row(["Curso", "Fecha", "Estudiante", "Asistencia", "Log de correo", "Motivo suspensión"])

                chile_time = get_chile_time()
                log = f"{chile_time.strftime('%Y-%m-%d')}: Clase no realizada. Motivo registrado a las {chile_time.strftime('%H:%M')} (hora de Chile)."
                sheet.append_row([
                    curso_seleccionado,
                    fecha_seleccionada,
                    "TODOS",
                    0,
                    log,
                    motivo
                ])
                st.success(f"✅ Suspensión registrada para la fecha **{fecha_seleccionada}**.")
            except Exception as e:
                st.error(f"❌ Error al registrar suspensión: {e}")
        return

    # Registro normal de asistencia
    fecha_seleccionada = st.selectbox("🗓️ Selecciona la fecha", data["fechas"])
    st.header("👥 Estudiantes")

    # === BLOQUE DE ASISTENCIA: BOTONES ROJO/AZUL (solo para estudiantes) ===
    estado_key = f"asistencia_estado_{curso_seleccionado}"
    if estado_key not in st.session_state:
        st.session_state[estado_key] = {est: False for est in data["estudiantes"]}

    asistencia_estado = st.session_state[estado_key]

    # CSS solo para los botones de estudiantes
    st.markdown("""
    <style>
    /* Solo aplica rojo/azul a los botones de estudiantes */
    div[data-testid="stButton"] button[kind="secondary"]:not([key="guardar_asistencia"]) {
        background-color: #FF6B6B !important;
        color: white !important;
        border: none !important;
        border-radius: 8px !important;
        font-weight: bold !important;
    }
    div[data-testid="stButton"] button[kind="primary"]:not([key="guardar_asistencia"]) {
        background-color: #1A3B8F !important;
        color: white !important;
        border: none !important;
        border-radius: 8px !important;
        font-weight: bold !important;
    }

    /* Botón GUARDAR: forzar verde */
    div[data-testid="stButton"] button[key="guardar_asistencia"] {
        background-color: #28A745 !important;
        color: white !important;
        border: 2px solid #6c757d !important;
        font-weight: bold !important;
        border-radius: 8px !important;
        transition: background-color 0.2s ease !important;
    }
    div[data-testid="stButton"] button[key="guardar_asistencia"]:hover {
        background-color: #218838 !important;
    }
    </style>
    """, unsafe_allow_html=True)

    for est in data["estudiantes"]:
        key = f"btn_{curso_seleccionado}_{est}"
        estado_actual = asistencia_estado[est]

        if estado_actual:
            if st.button(f"✅ {est} — ASISTIÓ", key=key, use_container_width=True, type="primary"):
                asistencia_estado[est] = False
                st.rerun()
        else:
            if st.button(f"❌ {est} — AUSENTE", key=key, use_container_width=True, type="secondary"):
                asistencia_estado[est] = True
                st.rerun()

    asistencia = asistencia_estado
    # === FIN DEL BLOQUE DE ESTUDIANTES ===

    # === BOTÓN DE GUARDAR: USAR UN CONTENEDOR NEUTRO ===
    st.divider()
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button("💾 Guardar Asistencia",key="guardar_asistencia", use_container_width=True,type="primary"):
            try:
                client = get_client()
                asistencia_sheet = client.open_by_key(st.secrets["google"]["asistencia_sheet_id"])
                try:
                    sheet = asistencia_sheet.worksheet(curso_seleccionado)
                except gspread.exceptions.WorksheetNotFound:
                    sheet = asistencia_sheet.add_worksheet(title=curso_seleccionado, rows=100, cols=6)
                    sheet.append_row(["Curso", "Fecha", "Estudiante", "Asistencia", "Log de correo", "Motivo suspensión"])

                chile_time = get_chile_time()
                log_base = f"{chile_time.strftime('%Y-%m-%d')}: Mail de asistencia enviado a las {chile_time.strftime('%H:%M')} (hora de Chile)."

                rows = []
                for estudiante, presente in asistencia.items():
                    rows.append([
                        curso_seleccionado,
                        fecha_seleccionada,
                        estudiante,
                        1 if presente else 0,
                        log_base,
                        ""
                    ])
                sheet.append_rows(rows)
                st.success(f"✅ ¡Asistencia guardada para **{curso_seleccionado}**!")

                st.info("📧 Enviando notificaciones a apoderados...")
                emails, nombres_apoderados = load_emails()
                for estudiante, presente in asistencia.items():
                    nombre_lower = estudiante.strip().lower()
                    correo_destino = emails.get(nombre_lower)
                    nombre_apoderado = nombres_apoderados.get(nombre_lower, "Apoderado")
                    if not correo_destino:
                        continue

                    estado = "✅ ASISTIÓ" if presente else "❌ NO ASISTIÓ"
                    subject = f"Reporte de Asistencia - {curso_seleccionado} - {fecha_seleccionada}"
                    body = f"""Hola {nombre_apoderado},

Este es un reporte automático de asistencia para el curso {curso_seleccionado}.

📅 Fecha: {fecha_seleccionada}
👨‍🎓 Estudiante: {estudiante}
📌 Estado: {estado}

Saludos cordiales,
Preuniversitario CIMMA 2026"""
                    send_email(correo_destino, subject, body)

            except Exception as e:
                st.error(f"❌ Error al guardar o enviar notificaciones: {e}")

if __name__ == "__main__":
    main()