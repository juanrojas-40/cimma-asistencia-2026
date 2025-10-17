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
# CARGA DE DATOS (CORREGIDA)
# ==============================

@st.cache_data(ttl=3600)
def load_courses():
    client = get_client()
    clases_sheet = client.open_by_key(st.secrets["google"]["clases_sheet_id"])
    courses = {}

    for worksheet in clases_sheet.worksheets():
        sheet_name = worksheet.title
        try:
            colA_raw = worksheet.col_values(1)
            colA = [cell.strip() for cell in colA_raw if isinstance(cell, str) and cell.strip()]
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
                estudiantes = sorted([e for e in estudiantes if e.strip()])
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

@st.cache_data(ttl=3600)
def load_emails():
    try:
        client = get_client()
        asistencia_sheet = client.open_by_key(st.secrets["google"]["asistencia_sheet_id"])
        sheet_names = [ws.title for ws in asistencia_sheet.worksheets()]
        if "MAILS" not in sheet_names:
            return {}, {}

        mails_sheet = asistencia_sheet.worksheet("MAILS")
        data = mails_sheet.get_all_records()
        emails = {}
        nombres_apoderados = {}
        for row in data:  # ← CORREGIDO: faltaba "data"
            nombre_estudiante = str(row.get("NOMBRE ESTUDIANTE", "")).strip().lower()
            nombre_apoderado = str(row.get("NOMBRE APODERADO", "")).strip()
            mail_apoderado = str(row.get("MAIL APODERADO", "")).strip()
            email_to_use = mail_apoderado
            if email_to_use and nombre_estudiante:
                emails[nombre_estudiante] = email_to_use
                nombres_apoderados[nombre_estudiante] = nombre_apoderado
        return emails, nombres_apoderados
    except:
        return {}, {}

@st.cache_data(ttl=3600)
def load_all_asistencia():
    client = get_client()
    asistencia_sheet = client.open_by_key(st.secrets["google"]["asistencia_sheet_id"])
    all_data = []

    for worksheet in asistencia_sheet.worksheets():
        if worksheet.title in ["MAILS", "MEJORAS"]:
            continue

        try:
            all_values = worksheet.get_all_values()
            if not all_values or len(all_values) < 2:
                continue

            headers = [h.strip().upper() for h in all_values[0]]
            curso_col = fecha_col = estudiante_col = asistencia_col = None

            for i, h in enumerate(headers):
                if "CURSO" in h: curso_col = i
                elif "FECHA" in h: fecha_col = i
                elif "ESTUDIANTE" in h: estudiante_col = i
                elif "ASISTENCIA" in h: asistencia_col = i

            if asistencia_col is None: continue

            for row in all_values[1:]:  # ← CORREGIDO: iterar sobre all_values[1:]
                if len(row) <= asistencia_col: continue
                try:
                    asistencia_val = int(row[asistencia_col])
                except:
                    asistencia_val = 0

                curso = row[curso_col] if curso_col is not None and curso_col < len(row) else worksheet.title
                fecha = row[fecha_col] if fecha_col is not None and fecha_col < len(row) else ""
                estudiante = row[estudiante_col] if estudiante_col is not None and estudiante_col < len(row) else ""

                all_data.append({
                    "Curso": curso,
                    "Fecha": fecha,
                    "Estudiante": estudiante,
                    "Asistencia": asistencia_val
                })
        except Exception as e:
            st.warning(f"⚠️ Error en hoja '{worksheet.title}': {str(e)[:80]}")
            continue

    return pd.DataFrame(all_data)

# ==============================
# MENÚ LATERAL Y AUTENTICACIÓN CON 2FA
# ==============================

def main():
    st.set_page_config(
        page_title="Preuniversitario CIMMA : Asistencia Cursos 2026",
        page_icon="✅",
        layout="centered"
    )

    with st.sidebar:
        st.image("https://raw.githubusercontent.com/juanrojas-40/asistencia-2026/main/LOGO.jpg", use_container_width=True)
        st.title("🔐 Acceso")

        # Inicializar estado
        if "user_type" not in st.session_state:
            st.session_state["user_type"] = None
            st.session_state["user_name"] = None
            st.session_state["2fa_pendiente"] = None
            st.session_state["2fa_codigo"] = None

        # Si ya está autenticado
        if st.session_state["user_type"]:
            st.success(f"👤 {st.session_state['user_name']}")
            if st.button("Cerrar sesión"):
                st.session_state.clear()
                st.rerun()
            return

        # Si está en paso 2 (2FA)
        if st.session_state["2fa_pendiente"]:
            st.subheader("🔐 Verificación en 2 pasos")
            st.info(f"Se envió un código a tu correo.")
            codigo_ingresado = st.text_input("Código de verificación", max_chars=6)
            if st.button("Verificar"):
                if codigo_ingresado == st.session_state["2fa_codigo"]:
                    st.session_state["user_type"] = "admin"
                    st.session_state["user_name"] = st.session_state["2fa_pendiente"]
                    # Limpiar 2FA
                    st.session_state["2fa_pendiente"] = None
                    st.session_state["2fa_codigo"] = None
                    st.rerun()
                else:
                    st.error("❌ Código incorrecto")
            if st.button("Cancelar"):
                st.session_state["2fa_pendiente"] = None
                st.session_state["2fa_codigo"] = None
                st.rerun()
            return

        # Paso 1: Selección de rol
        user_type = st.radio("Selecciona tu rol", ["Profesor", "Administrador"], key="role_select")

        if user_type == "Profesor":
            profesores = st.secrets.get("profesores", {})
            if profesores:
                nombre = st.selectbox("Nombre", list(profesores.keys()), key="prof_select")
                clave = st.text_input("Clave", type="password", key="prof_pass")
                if st.button("Ingresar como Profesor"):
                    if profesores.get(nombre) == clave:
                        st.session_state["user_type"] = "profesor"
                        st.session_state["user_name"] = nombre
                        st.rerun()
                    else:
                        st.error("❌ Clave incorrecta")
            else:
                st.error("No hay profesores configurados en Secrets.")
        else:
            admins = st.secrets.get("administradores", {})
            admin_emails = st.secrets.get("admin_emails", {})
            if admins and admin_emails:
                nombre = st.selectbox("Usuario", list(admins.keys()), key="admin_select")
                clave = st.text_input("Clave", type="password", key="admin_pass")
                if st.button("Enviar código de verificación"):
                    if admins.get(nombre) == clave:
                        # Generar código de 6 dígitos
                        codigo = str(random.randint(100000, 999999))
                        email_destino = admin_emails.get(nombre)
                        if email_destino:
                            send_email(
                                email_destino,
                                "🔐 Código de Verificación - CIMMA",
                                f"Tu código de acceso es: {codigo}\nVálido por 5 minutos."
                            )
                            st.session_state["2fa_pendiente"] = nombre
                            st.session_state["2fa_codigo"] = codigo
                            st.info("✅ Código enviado a tu correo.")
                        else:
                            st.error("❌ Correo no configurado para este administrador.")
                    else:
                        st.error("❌ Clave incorrecta")
            else:
                st.error("No hay administradores o correos configurados en Secrets.")

    # === CONTENIDO PRINCIPAL ===
    if st.session_state["user_type"] is None:
        st.title("📱 Registro de Asistencia")
        st.subheader("Preuniversitario CIMMA 2026")
        st.info("Por favor, inicia sesión desde el menú lateral.")
        return

    if st.session_state["user_type"] == "admin":
        admin_panel()
    else:
        main_app()

# ==============================
# PANEL ADMINISTRATIVO
# ==============================

def admin_panel():
    st.title("📊 Panel Administrativo - Análisis de Asistencia")
    st.subheader(f"Bienvenido, {st.session_state['user_name']}")

    df = load_all_asistencia()
    if df.empty:
        st.warning("No hay datos de asistencia aún.")
        return

    cursos = ["Todos"] + sorted(df["Curso"].unique().tolist())
    curso_sel = st.selectbox("Curso", cursos)
    if curso_sel != "Todos":
        df = df[df["Curso"] == curso_sel]

    st.subheader("📈 Porcentaje de Asistencia por Curso")
    asistencia_curso = df.groupby("Curso").apply(
        lambda x: (x["Asistencia"].sum() / len(x)) * 100
    ).reset_index(name="Porcentaje")
    st.bar_chart(asistencia_curso.set_index("Curso"))

    st.subheader("📋 Registro Detallado")
    st.dataframe(df)

    if st.button("📤 Descargar como CSV"):
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button("Descargar CSV", csv, "asistencia.csv", "text/csv")

# ==============================
# APP PRINCIPAL (PROFESOR)
# ==============================

def main_app():
    # ... (igual que antes, sin cambios) ...
    st.title("📱 Registro de Asistencia")
    st.subheader("Preuniversitario CIMMA 2026")

    courses = load_courses()
    if not courses:
        st.error("❌ No se encontraron cursos en 'CLASES 2026'.")
        st.stop()

    cursos_filtrados = {
        k: v for k, v in courses.items()
        if v["profesor"] == st.session_state["user_name"]
    }

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

    st.markdown("<hr>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button("💾 Guardar Asistencia", key="guardar_asistencia", use_container_width=True, type="primary"):
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

                st.subheader("📊 Resumen de esta sesión")
                for est, presente in asistencia.items():
                    estado = "✅" if presente else "❌"
                    st.write(f"{estado} {est}")

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

    st.divider()
    st.caption("💡 ¿Tienes ideas para mejorar esta plataforma?")
    mejora = st.text_area("Sugerencia:", placeholder="Ej: Agregar notificación por WhatsApp...")
    if st.button("📤 Enviar sugerencia"):
        try:
            client = get_client()
            sheet = client.open_by_key(st.secrets["google"]["asistencia_sheet_id"])
            try:
                mejoras_sheet = sheet.worksheet("MEJORAS")
            except:
                mejoras_sheet = sheet.add_worksheet("MEJORAS", 100, 3)
                mejoras_sheet.append_row(["Fecha", "Sugerencia", "Usuario"])
            mejoras_sheet.append_row([datetime.now().strftime("%Y-%m-%d %H:%M"), mejora, st.session_state["user_name"]])
            st.success("¡Gracias por tu aporte!")
        except Exception as e:
            st.error(f"Error al guardar sugerencia: {e}")

if __name__ == "__main__":
    main()