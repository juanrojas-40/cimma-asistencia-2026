import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import json
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import pytz
import pandas as pd
import random
import string
import plotly.express as px
from twilio.rest import Client as TwilioClient
from googleapiclient.discovery import build

# Configuración inicial con fondo temático mejorado
st.set_page_config(
    page_title="Preuniversitario CIMMA : Asistencia Cursos 2026",
    page_icon="✅",
    layout="centered",
    initial_sidebar_state="collapsed"
)
st.markdown(
    """
    <style>
    .stApp {
        background-image: url('https://thumbs.dreamstime.com/b/science-line-logo-scientific-research-sketch-outline-icons-chemistry-laboratory-analysis-dna-molecule-atom-symbols-biology-lab-385164964.jpg');
        background-size: cover;
        background-repeat: no-repeat;
        background-attachment: fixed;
        background-position: center;
        position: relative;
    }
    .stApp::before {
        content: "";
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background-color: rgba(0, 0, 0, 0.6); /* Overlay oscuro para atenuar colores */
        z-index: 0;
    }
    .main-content {
        position: relative;
        z-index: 1;
        background-color: rgba(255, 255, 255, 0.9); /* Fondo semi-transparente blanco */
        padding: 25px;
        border-radius: 15px;
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2); /* Sombra sutil */
        margin: 20px auto;
        max-width: 1200px;
    }
    .stButton > button {
        font-size: 16px !important;
        min-width: 200px !important;
        padding: 10px 20px !important;
        border-radius: 8px !important;
        transition: all 0.3s ease !important;
    }
    .stButton > button:hover {
        transform: translateY(-2px) !important;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2) !important;
    }
    div[data-testid="stButton"] button[kind="secondary"] {
        background-color: #FF6B6B !important;
        color: white !important;
        border: none !important;
        font-weight: bold !important;
    }
    div[data-testid="stButton"] button[kind="primary"] {
        background-color: #1A3B8F !important;
        color: white !important;
        border: none !important;
        font-weight: bold !important;
    }
    div[data-testid="stButton"] button[key="guardar_asistencia"] {
        background-color: #10B981 !important;
        color: white !important;
        border: 2px solid #6c757d !important;
        font-weight: bold !important;
    }
    h1, h2, h3, h4, h5, h6 {
        color: #1A3B8F !important;
        font-family: 'Arial', sans-serif !important;
    }
    .stText, .stSelectbox, .stRadio, .stTextArea {
        color: #333 !important;
        font-family: 'Arial', sans-serif !important;
    }
    @media (prefers-color-scheme: dark) {
        .stApp::before { background-color: rgba(0, 0, 0, 0.8); }
        .main-content { background-color: rgba(30, 30, 30, 0.9); }
        h1, h2, h3, h4, h5, h6 { color: #10B981 !important; }
        .stText, .stSelectbox, .stRadio, .stTextArea { color: #E0E0E0 !important; }
    }
    </style>
    """,
    unsafe_allow_html=True
)

# Wrap main content in a div for styling
st.markdown('<div class="main-content">', unsafe_allow_html=True)

# ==============================
# CONFIGURACIÓN Y CONEXIONES
# ==============================

@st.cache_resource
def get_client():
    try:
        creds_dict = json.loads(st.secrets["google"]["credentials"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=[
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/calendar"
        ])
        return gspread.authorize(creds)
    except (KeyError, json.JSONDecodeError) as e:
        st.error(f"Error loading Google credentials: {e}")
        return None

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
    except (KeyError, ValueError, smtplib.SMTPException) as e:
        st.warning(f"⚠️ Error al enviar correo a {to_email}: {e}")
        return False

def send_whatsapp_notification(to_phone: str, message: str) -> bool:
    try:
        twilio_client = TwilioClient(st.secrets["TWILIO"]["account_sid"], st.secrets["TWILIO"]["auth_token"])
        twilio_client.messages.create(
            body=message,
            from_=st.secrets["TWILIO"]["from_number"],
            to=f"+{to_phone}"
        )
        return True
    except Exception as e:
        st.warning(f"⚠️ Error al enviar WhatsApp a {to_phone}: {e}")
        return False

def generate_2fa_code():
    """Generate a random 6-digit 2FA code."""
    return ''.join(random.choices(string.digits, k=6))

def sync_to_calendar(event_data):
    try:
        creds = Credentials.from_service_account_info(json.loads(st.secrets["google"]["credentials"]), scopes=["https://www.googleapis.com/auth/calendar"])
        service = build("calendar", "v3", credentials=creds)
        event = {
            "summary": f"Clase - {event_data['curso_id']}",
            "start": {"date": event_data["fecha"]},
            "end": {"date": event_data["fecha"]}
        }
        service.events().insert(calendarId="primary", body=event).execute()
        st.success("Sincronizado con Google Calendar!")
    except Exception as e:
        st.error(f"Error al sincronizar con calendario: {e}. Asegúrate de que la API de Google Calendar esté habilitada en tu proyecto.")

def log_action(action: str, user: str):
    client = get_client()
    if client:
        try:
            sheet = client.open_by_key(st.secrets["google"]["asistencia_sheet_id"]).worksheet("AUDIT")
        except gspread.exceptions.WorksheetNotFound:
            sheet = client.open_by_key(st.secrets["google"]["asistencia_sheet_id"]).add_worksheet("AUDIT", 100, 3)
            sheet.append_row(["Fecha", "Usuario", "Acción"])
        sheet.append_row([get_chile_time().strftime("%Y-%m-%d %H:%M"), user, action])

# ==============================
# CARGA DE DATOS
# ==============================

@st.cache_data(ttl=3600)
def load_courses():
    client = get_client()
    if not client:
        return {}
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
            fechas = []
            estudiantes = []
            try:
                idx_fechas = colA_upper.index("FECHAS")
                idx_estudiantes = colA_upper.index("NOMBRES ESTUDIANTES")
                for i in range(idx_fechas + 1, idx_estudiantes):
                    if i < len(colA):
                        fechas.append(colA[i])
                for i in range(idx_estudiantes + 1, len(colA)):
                    if colA[i]:
                        estudiantes.append(colA[i])
            except ValueError:
                pass
            if profesor and dia and curso_id and horario and estudiantes:
                estudiantes = sorted([e for e in estudiantes if e.strip()])
                courses[sheet_name] = {
                    "profesor": profesor,
                    "dia": dia,
                    "horario": horario,
                    "curso_id": curso_id,
                    "fechas": fechas or ["Sin fechas"],
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
        if not client:
            return {}, {}
        asistencia_sheet = client.open_by_key(st.secrets["google"]["asistencia_sheet_id"])
        sheet_names = [ws.title for ws in asistencia_sheet.worksheets()]
        if "MAILS" not in sheet_names:
            return {}, {}
        mails_sheet = asistencia_sheet.worksheet("MAILS")
        data = mails_sheet.get_all_records()
        emails = {}
        nombres_apoderados = {}
        for row in data:
            nombre_estudiante = str(row.get("NOMBRE ESTUDIANTE", "")).strip().lower()
            nombre_apoderado = str(row.get("NOMBRE APODERADO", "")).strip()
            mail_apoderado = str(row.get("MAIL APODERADO", "")).strip()
            email_to_use = mail_apoderado
            if email_to_use and nombre_estudiante:
                emails[nombre_estudiante] = email_to_use
                nombres_apoderados[nombre_estudiante] = nombre_apoderado
        return emails, nombres_apoderados
    except Exception as e:
        st.warning(f"Error loading emails: {e}")
        return {}, {}

@st.cache_data(ttl=3600)
def load_all_asistencia():
    client = get_client()
    if not client:
        return pd.DataFrame()
    asistencia_sheet = client.open_by_key(st.secrets["google"]["asistencia_sheet_id"])
    all_data = []
    for worksheet in asistencia_sheet.worksheets():
        if worksheet.title in ["MAILS", "MEJORAS", "PROFESORES", "AUDIT"]:
            continue
        try:
            all_values = worksheet.get_all_values()
            if not all_values or len(all_values) < 5:
                continue
            all_values = all_values[3:]
            headers = all_values[0]
            headers = [h.strip().upper() for h in headers]
            curso_col = None
            fecha_col = None
            estudiante_col = None
            asistencia_col = None
            hora_registro_col = None
            informacion_col = None
            for i, h in enumerate(headers):
                if "CURSO" in h:
                    curso_col = i
                elif "FECHA" in h:
                    fecha_col = i
                elif "ESTUDIANTE" in h:
                    estudiante_col = i
                elif "ASISTENCIA" in h:
                    asistencia_col = i
                elif "HORA REGISTRO" in h:
                    hora_registro_col = i
                elif "INFORMACION" in h or "MOTIVO" in h:
                    informacion_col = i
            if curso_col is None:
                curso_col = 0
            if fecha_col is None:
                fecha_col = 1
            if asistencia_col is None:
                continue
            for row in all_values[1:]:
                if len(row) <= asistencia_col:
                    continue
                try:
                    asistencia_val = int(row[asistencia_col])
                except (ValueError, TypeError):
                    asistencia_val = 0
                curso = row[curso_col] if curso_col < len(row) and row[curso_col] else worksheet.title
                fecha = row[fecha_col] if fecha_col < len(row) and row[fecha_col] else ""
                estudiante = row[estudiante_col] if estudiante_col < len(row) and row[estudiante_col] else ""
                hora_registro = row[hora_registro_col] if hora_registro_col < len(row) and row[hora_registro_col] else ""
                informacion = row[informacion_col] if informacion_col < len(row) and row[informacion_col] else ""
                all_data.append({
                    "Curso": curso,
                    "Fecha": fecha,
                    "Estudiante": estudiante,
                    "Asistencia": asistencia_val,
                    "Hora Registro": hora_registro,
                    "Información": informacion
                })
        except Exception as e:
            st.warning(f"⚠️ Error al procesar hoja '{worksheet.title}': {str(e)[:80]}")
            continue
    return pd.DataFrame(all_data)

# ==============================
# MENÚ LATERAL Y AUTENTICACIÓN
# ==============================

def main():
    theme = st.sidebar.radio("Modo", ["Claro", "Oscuro"], key="theme")
    if theme == "Oscuro":
        st.markdown('<style>body {background-color: #1a1a1a; color: white;}</style>', unsafe_allow_html=True)
    with st.sidebar:
        st.image("https://raw.githubusercontent.com/juanrojas-40/asistencia-2026/main/LOGO.jpg", use_container_width=True)
        st.title("🔐 Acceso")
        if "user_type" not in st.session_state:
            st.session_state["user_type"] = None
            st.session_state["user_name"] = None
            st.session_state["2fa_code"] = None
            st.session_state["2fa_email"] = None
            st.session_state["awaiting_2fa"] = False
            st.session_state["2fa_user_name"] = None
            st.session_state["2fa_time"] = None
            st.session_state["2fa_attempts"] = 0
            st.session_state["alerted_students"] = {}  # Initialize here to avoid runtime issues
        if st.session_state["user_type"] is None and not st.session_state["awaiting_2fa"]:
            user_type = st.radio("Selecciona tu rol", ["Profesor", "Administrador", "Estudiante"], key="role_select")
            if user_type == "Profesor":
                profesores = st.secrets.get("profesores", {})
                if profesores:
                    nombre = st.selectbox("Nombre", list(profesores.keys()), key="prof_select")
                    clave = st.text_input("Clave", type="password", key="prof_pass")
                    if st.button("Ingresar como Profesor"):
                        if profesores.get(nombre) == clave:
                            st.session_state["user_type"] = "profesor"
                            st.session_state["user_name"] = nombre
                            log_action("Login Profesor", nombre)
                            st.rerun()
                        else:
                            st.error("❌ Clave incorrecta")
                else:
                    st.error("No hay profesores configurados en Secrets.")
            elif user_type == "Administrador":
                try:
                    admins = st.secrets.get("administradores", {})
                    admin_emails = st.secrets.get("admin_emails", {})
                except KeyError:
                    st.error("Configuración de administradores no encontrada en Secrets.")
                    return
                if admins and admin_emails:
                    nombre = st.selectbox("Usuario", list(admins.keys()), key="admin_select")
                    clave = st.text_input("Clave", type="password", key="admin_pass")
                    if st.button("Ingresar como Admin"):
                        if admins.get(nombre) == clave:
                            code = generate_2fa_code()
                            email = admin_emails.get(nombre, "profereport@gmail.com")
                            subject = "Código de Verificación - Preuniversitario CIMMA"
                            body = f"""Estimado/a {nombre},
Su código de verificación para acceder al sistema es: {code}
Este código es válido por 10 minutos.
Saludos,
Preuniversitario CIMMA"""
                            if send_email(email, subject, body):
                                st.session_state["2fa_code"] = code
                                st.session_state["2fa_email"] = email
                                st.session_state["awaiting_2fa"] = True
                                st.session_state["2fa_user_name"] = nombre
                                st.session_state["2fa_time"] = get_chile_time()
                                st.session_state["2fa_attempts"] = 0
                                log_action("2FA Enviado", nombre)
                                st.rerun()
                            else:
                                st.error("❌ Error al enviar el código de verificación. Intenta de nuevo.")
                        else:
                            st.error("❌ Clave incorrecta")
                else:
                    st.error("No hay administradores o correos configurados en Secrets.")
            else:  # Estudiante
                estudiantes = st.secrets.get("estudiantes", {})
                if estudiantes:
                    nombre = st.selectbox("Nombre", list(estudiantes.keys()), key="est_select")
                    clave = st.text_input("Clave", type="password", key="est_pass")
                    if st.button("Ingresar como Estudiante"):
                        if estudiantes.get(nombre) == clave:
                            st.session_state["user_type"] = "estudiante"
                            st.session_state["user_name"] = nombre
                            log_action("Login Estudiante", nombre)
                            st.rerun()
                        else:
                            st.error("❌ Clave incorrecta")
                else:
                    st.error("No hay estudiantes configurados en Secrets.")
        elif st.session_state["awaiting_2fa"]:
            st.subheader("🔐 Verificación en dos pasos")
            st.info(f"Se ha enviado un código de 6 dígitos a {st.session_state['2fa_email']}")
            time_remaining = 600 - (get_chile_time() - st.session_state["2fa_time"]).total_seconds()
            if time_remaining > 0:
                st.write(f"Tiempo restante: {int(time_remaining // 60)} minutos y {int(time_remaining % 60)} segundos")
            code_input = st.text_input("Ingresa el código de verificación", type="password", key="2fa_code_input")
            if st.button("Verificar código"):
                if not code_input.isdigit() or len(code_input) != 6:
                    st.error("El código debe ser un número de 6 dígitos")
                elif (get_chile_time() - st.session_state["2fa_time"]).total_seconds() > 600:
                    st.error("❌ El código ha expirado. Por favor, intenta iniciar sesión de nuevo.")
                    st.session_state["awaiting_2fa"] = False
                    st.session_state["2fa_code"] = None
                    st.session_state["2fa_email"] = None
                    st.session_state["2fa_attempts"] = 0
                    log_action("2FA Expirado", st.session_state["2fa_user_name"])
                    st.rerun()
                elif st.session_state["2fa_attempts"] >= 3:
                    st.error("❌ Demasiados intentos fallidos. Intenta iniciar sesión de nuevo.")
                    st.session_state["awaiting_2fa"] = False
                    st.session_state["2fa_code"] = None
                    st.session_state["2fa_email"] = None
                    st.session_state["2fa_attempts"] = 0
                    log_action("2FA Fallido", st.session_state["2fa_user_name"])
                    st.rerun()
                elif code_input == st.session_state["2fa_code"]:
                    st.session_state["user_type"] = "admin"
                    st.session_state["user_name"] = st.session_state["2fa_user_name"]
                    st.session_state["awaiting_2fa"] = False
                    st.session_state["2fa_code"] = None
                    st.session_state["2fa_email"] = None
                    st.session_state["2fa_attempts"] = 0
                    st.session_state["2fa_time"] = None
                    log_action("Login Admin", st.session_state["user_name"])
                    st.rerun()
                else:
                    st.session_state["2fa_attempts"] += 1
                    st.error(f"❌ Código incorrecto. Intentos restantes: {3 - st.session_state['2fa_attempts']}")
        else:
            st.success(f"👤 {st.session_state['user_name']}")
            if st.button("Cerrar sesión"):
                log_action("Logout", st.session_state["user_name"])
                st.session_state.clear()
                st.rerun()

    if st.session_state["user_type"] is None:
        st.title("📱 Registro de Asistencia")
        st.subheader("Preuniversitario CIMMA 2026")
        st.info("Por favor, inicia sesión desde el menú lateral izquierdo.")
        return

    if st.session_state["user_type"] == "admin":
        admin_panel()
    elif st.session_state["user_type"] == "estudiante":
        student_portal()
    else:
        main_app()

# ==============================
# PANEL ADMINISTRATIVO
# ==============================

def admin_panel():
    st.title("📊 Panel Administrativo - Análisis de Asistencia")
    st.subheader(f"Bienvenido, {st.session_state['user_name']}")
    if st.secrets.get("super_admin_password") and st.text_input("Contraseña de Admin Superior", type="password", key="super_admin_pass") != st.secrets["super_admin_password"]:
        st.warning("Acceso restringido. Ingresa la contraseña de Admin Superior.")
        return
    df = load_all_asistencia()
    if df.empty:
        st.warning("No hay datos de asistencia aún.")
        return
    cursos = ["Todos"] + sorted(df["Curso"].unique().tolist())
    curso_sel = st.selectbox("Curso", cursos)
    asignaturas = ["Todas"] + sorted([c.split("_")[0] for c in df["Curso"].unique() if "_" in c])
    asignatura_sel = st.selectbox("Asignatura", asignaturas)
    if curso_sel != "Todos":
        df = df[df["Curso"] == curso_sel]
    if asignatura_sel != "Todas":
        df = df[df["Curso"].str.contains(asignatura_sel)]
    st.subheader("📈 Porcentaje de Asistencia por Curso")
    asistencia_curso = df.groupby("Curso").apply(lambda x: (x["Asistencia"].sum() / len(x)) * 100).reset_index(name="Porcentaje")
    st.bar_chart(asistencia_curso.set_index("Curso"))
    fig_line = px.line(df, x="Fecha", y="Asistencia", color="Estudiante", title="Tendencias de Asistencia")
    st.plotly_chart(fig_line)
    fig_heatmap = px.imshow(df.pivot_table(index="Fecha", columns="Estudiante", values="Asistencia"), title="Heatmap de Asistencia")
    st.plotly_chart(fig_heatmap)
    st.subheader("📋 Registro Detallado")
    st.dataframe(df)
    if st.button("📤 Descargar como CSV"):
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button("Descargar CSV", csv, "asistencia.csv", "text/csv")
    if st.button("📤 Descargar como XLSX"):
        import io
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='Asistencia')
        excel_data = output.getvalue()
        st.download_button("Descargar XLSX", excel_data, "asistencia.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    check_consecutive_absences(df)

def check_consecutive_absences(df):
    if not df.empty:
        if "alerted_students" not in st.session_state:
            st.session_state["alerted_students"] = {}
        
        df_sorted = df.sort_values(["Estudiante", "Fecha"])
        df_sorted["Prev_Asistencia"] = df_sorted.groupby("Estudiante")["Asistencia"].shift(1)
        df_consecutive = df_sorted[df_sorted["Asistencia"] == 0 & (df_sorted["Prev_Asistencia"] == 0)]
        
        for estudiante in df_consecutive["Estudiante"].unique():
            student_df = df_consecutive[df_consecutive["Estudiante"] == estudiante]
            absences = len(student_df)
            if absences >= 3:
                streak_start = student_df["Fecha"].iloc[0]
                streak_end = student_df["Fecha"].iloc[-1]
                student_key = f"{estudiante}_{streak_start}_{streak_end}"
                if student_key not in st.session_state["alerted_students"]:
                    emails, nombres_apoderados = load_emails()
                    email = emails.get(estudiante.lower().strip())
                    if email:
                        send_email(email, "Alerta de Ausencias", f"Hola {nombres_apoderados.get(estudiante.lower().strip(), 'Apoderado')},\nTu estudiante {estudiante} ha faltado 3 o más veces consecutivas desde {streak_start} hasta {streak_end}. Por favor, contáctenos.\nSaludos,\nPreuniversitario CIMMA")
                        st.warning(f"Alerta enviada a {email} por ausencias de {estudiante}.")
                        st.session_state["alerted_students"][student_key] = True
                        log_action(f"Alerta Ausencias {estudiante} ({streak_start}-{streak_end})", st.session_state["user_name"])

# ==============================
# APP PRINCIPAL (PROFESOR)
# ==============================

def main_app():
    st.title("📱 Registro de Asistencia")
    st.subheader("Preuniversitario CIMMA 2026")
    courses = load_courses()
    if not courses:
        st.error("❌ No se encontraron cursos en 'CLASES 2026'.")
        st.stop()
    cursos_filtrados = {k: v for k, v in courses.items() if v["profesor"] == st.session_state["user_name"]}
    if not cursos_filtrados:
        st.warning("No tienes cursos asignados.")
        st.stop()
    curso_seleccionado = st.selectbox("🎓 Selecciona tu curso", list(cursos_filtrados.keys()))
    data = cursos_filtrados[curso_seleccionado]
    st.markdown(f"**🧑‍🏫 Profesor(a):** {data['profesor']}")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**📅 Día:** {data['dia']}")
    with col2:
        st.markdown(f"**⏰ Horario:** {data['horario']}")
    clase_realizada = st.radio("✅ ¿Se realizó la clase?", ("Sí", "No"), index=0, help="Selecciona 'No' en caso de feriado, suspensión o imprevisto.")
    if clase_realizada == "No":
        motivo = st.text_area("📝 Motivo de la no realización", placeholder="Ej: Feriado nacional, suspensión por evento escolar, emergencia, etc.")
        fecha_seleccionada = st.selectbox("🗓️ Fecha afectada", data["fechas"])
        if st.button("💾 Registrar suspensión", use_container_width=True):
            try:
                client = get_client()
                if not client:
                    st.error("Error connecting to Google Sheets")
                    return
                asistencia_sheet = client.open_by_key(st.secrets["google"]["asistencia_sheet_id"])
                try:
                    sheet = asistencia_sheet.worksheet(curso_seleccionado)
                except gspread.exceptions.WorksheetNotFound:
                    sheet = asistencia_sheet.add_worksheet(title=curso_seleccionado, rows=100, cols=6)
                    sheet.append_row(["Curso", "Fecha", "Estudiante", "Asistencia", "Log de correo", "Motivo suspensión"])
                chile_time = get_chile_time()
                log = f"{chile_time.strftime('%Y-%m-%d')}: Clase no realizada. Motivo registrado a las {chile_time.strftime('%H:%M')} (hora de Chile)."
                sheet.append_row([curso_seleccionado, fecha_seleccionada, "TODOS", 0, log, motivo])
                st.success(f"✅ Suspensión registrada para la fecha **{fecha_seleccionada}**.")
                log_action(f"Suspensión Registrada {curso_seleccionado}", st.session_state["user_name"])
            except Exception as e:
                st.error(f"❌ Error al registrar suspensión: {e}")
        return
    fecha_seleccionada = st.selectbox("🗓️ Selecciona la fecha", data["fechas"])
    st.header("👥 Estudiantes")
    estado_key = f"asistencia_estado_{curso_seleccionado}"
    if estado_key not in st.session_state:
        st.session_state[estado_key] = {est: True for est in data["estudiantes"]}
    asistencia_estado = st.session_state[estado_key]
    st.markdown("""
    <style>
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
    div[data-testid="stButton"] button[key="guardar_asistencia"] {
        background-color: #10B981 !important;
        color: white !important;
        border: 2px solid #6c757d !important;
        font-weight: bold !important;
        border-radius: 8px !important;
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
    st.warning("📧 Al guardar, se enviará un reporte automático a los apoderados.")
    send_whatsapp = st.checkbox("Enviar por WhatsApp", key="whatsapp_notify")
    st.markdown("<hr>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button("💾 Guardar Asistencia", key="guardar_asistencia", use_container_width=True, type="primary"):
            try:
                client = get_client()
                if not client:
                    st.error("Error connecting to Google Sheets")
                    return
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
                    rows.append([curso_seleccionado, fecha_seleccionada, estudiante, 1 if presente else 0, log_base, ""])
                sheet.append_rows(rows)
                st.success(f"✅ ¡Asistencia guardada para **{curso_seleccionado}**!")
                emails, nombres_apoderados = load_emails()
                for estudiante, presente in asistencia.items():
                    nombre_lower = estudiante.strip().lower()
                    correo_destino = emails.get(nombre_lower)
                    nombre_apoderado = nombres_apoderados.get(nombre_lower, "Apoderado")
                    if correo_destino:
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
                        if send_whatsapp and st.secrets.get("TWILIO"):
                            phone = st.secrets.get("phones", {}).get(nombre_lower, "default_phone")
                            send_whatsapp_notification(phone, f"Reporte: {estudiante} {estado} el {fecha_seleccionada}")
                log_action(f"Asistencia Guardada {curso_seleccionado}", st.session_state["user_name"])
            except Exception as e:
                st.error(f"❌ Error al guardar o enviar notificaciones: {e}")
    if st.button("Sincronizar con Calendario"):
        for course in courses.values():
            sync_to_calendar({"curso_id": course["curso_id"], "fecha": course["fechas"][0]})
    st.divider()
    st.caption("💡 ¿Tienes ideas para mejorar esta plataforma?")
    rating = st.slider("Calificación (1-5)", 1, 5, 3, key="rating")
    category = st.selectbox("Categoría", ["Usabilidad", "Funcionalidades", "Otros"], key="category")
    mejora = st.text_area("Sugerencia:", placeholder="Ej: Agregar notificación por WhatsApp...")
    if st.button("📤 Enviar sugerencia"):
        try:
            client = get_client()
            if not client:
                st.error("Error connecting to Google Sheets")
                return
            sheet = client.open_by_key(st.secrets["google"]["asistencia_sheet_id"])
            try:
                mejoras_sheet = sheet.worksheet("MEJORAS")
            except gspread.exceptions.WorksheetNotFound:
                mejoras_sheet = sheet.add_worksheet("MEJORAS", 100, 4)
                mejoras_sheet.append_row(["Fecha", "Sugerencia", "Usuario", "Calificación", "Categoría"])
            mejoras_sheet.append_row([get_chile_time().strftime("%Y-%m-%d %H:%M"), mejora, st.session_state["user_name"], rating, category])
            st.success("¡Gracias por tu aporte!")
            log_action(f"Sugerencia Enviada {category}", st.session_state["user_name"])
        except Exception as e:
            st.error(f"Error al guardar sugerencia: {e}")

# ==============================
# PORTAL ESTUDIANTE
# ==============================

def student_portal():
    st.title("🎯 Portal Estudiantil")
    st.subheader(f"Bienvenido, {st.session_state['user_name']}")
    df = load_all_asistencia()
    if df.empty:
        st.warning("No hay datos de asistencia aún.")
        return
    student_df = df[df["Estudiante"] == st.session_state["user_name"]]
    if not student_df.empty:
        asistencia_pct = (student_df["Asistencia"].sum() / len(student_df)) * 100
        st.metric("Porcentaje de Asistencia", f"{asistencia_pct:.1f}%")
        if asistencia_pct >= 95:
            st.success("🏅 ¡Has ganado el badge 'Asistencia Perfecta'!")
        else:
            st.info("Objetivo: Alcanza 95% para un badge!")
    else:
        st.info("No hay registros de asistencia para ti aún.")

if __name__ == "__main__":
    main()

# Close the main content div
st.markdown('</div>', unsafe_allow_html=True)