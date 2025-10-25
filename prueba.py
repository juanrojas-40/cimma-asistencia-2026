# prueba.py
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import json
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os

# ==============================
# CONFIGURACIÓN LOCAL (usa variables directas o .env)
# ==============================

# 🔑 Reemplaza estos valores con tus claves reales
GOOGLE_SHEET_ID_ASISTENCIA =  "1u-Ay1yJJUEtKdTdV2xXGVLAtWo09wk_LhuL69tNBJpc"
GOOGLE_SHEET_ID_CLASES = "1R1KosQtbzJiWc9oQj96NnSybYDevbj0rK2gvKxa1IZM"
CREDENTIALS_JSON_PATH = "credentials.json"  # archivo descargado de Google Cloud

# 📧 Configuración de correo (Gmail)
EMAIL_CONFIG = {
    "smtp_server": "smtp.gmail.com",
    "smtp_port": 587,
    "sender_email": "juan.rojas.valencia@gmail.com",
    "sender_password": "ummf dwdq ytwj vbmt"  # usa contraseña de app de Gmail
}

# ==============================
# FUNCIONES
# ==============================

def get_client():
    creds = Credentials.from_service_account_file(
        CREDENTIALS_JSON_PATH,
        scopes=["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    )
    return gspread.authorize(creds)

def send_email(to_email, subject, body):
    try:
        server = smtplib.SMTP(EMAIL_CONFIG["smtp_server"], EMAIL_CONFIG["smtp_port"])
        server.starttls()
        server.login(EMAIL_CONFIG["sender_email"], EMAIL_CONFIG["sender_password"])
        msg = MIMEMultipart()
        msg["From"] = EMAIL_CONFIG["sender_email"]
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        st.warning(f"Error al enviar correo: {e}")
        return False

def load_courses_local():
    """Carga cursos desde CLASES 2026.xlsx (local)"""
    xls = pd.ExcelFile("CLASES 2026.xlsx")
    courses = {}
    for sheet in xls.sheet_names:
        df = pd.read_excel(xls, sheet_name=sheet, header=None)
        colA = df.iloc[:, 0].dropna().astype(str).str.strip().tolist()
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
                if val and any(c.isalpha() for c in val):
                    estudiantes.append(val)
                elif val:
                    fechas.append(val)
        except ValueError:
            pass

        if profesor and dia and horario and estudiantes:
            courses[sheet] = {
                "profesor": profesor,
                "dia": dia,
                "horario": horario,
                "fechas": fechas,
                "estudiantes": estudiantes
            }
    return courses

def load_emails_local():
    """Carga correos desde hoja MAILS de Asistencia 2026 (Google Sheet)"""
    client = get_client()
    sheet = client.open_by_key(GOOGLE_SHEET_ID_ASISTENCIA).worksheet("MAILS")
    data = sheet.get_all_records()
    emails = {}
    nombres = {}
    for row in data:
        est = str(row.get("NOMBRE ESTUDIANTE", "")).strip().lower()
        mail = str(row.get("MAIL APODERADO", "")).strip()
        apod = str(row.get("NOMBRE APODERADO", "")).strip()
        if est and mail:
            emails[est] = mail
            nombres[est] = apod
    return emails, nombres

def send_monthly_summary_test():
    """Versión de prueba del resumen mensual (se puede forzar)"""
    st.info("🧪 Probando envío de resumen mensual...")
    
    client = get_client()
    asistencia_sheet = client.open_by_key(GOOGLE_SHEET_ID_ASISTENCIA)
    emails, nombres_apoderados = load_emails_local()

    for worksheet in asistencia_sheet.worksheets():
        if worksheet.title == "MAILS":
            continue
        data = worksheet.get_all_records()
        students_data = {}

        for row in data:
            try:
                # Formato de fecha en tu Sheet: "1-Aug" → convertir a datetime
                fecha_str = str(row.get("Fecha", "")).strip()
                if not fecha_str or "-" not in fecha_str:
                    continue
                # Asumir año actual
                fecha = datetime.strptime(fecha_str + "-2026", "%d-%b-%Y")
                estudiante = str(row.get("Estudiante", "")).strip()
                asistencia = int(row.get("Asistencia", 0))
                if estudiante:
                    if estudiante not in students_data:
                        students_data[estudiante] = {"presente": 0, "ausente": 0}
                    if asistencia == 1:
                        students_data[estudiante]["presente"] += 1
                    else:
                        students_data[estudiante]["ausente"] += 1
            except Exception as e:
                continue

        for estudiante, stats in students_data.items():
            total = stats["presente"] + stats["ausente"]
            if total == 0:
                continue
            asist_pct = (stats["presente"] / total) * 100
            inasist_pct = (stats["ausente"] / total) * 100

            nombre_lower = estudiante.strip().lower()
            correo = emails.get(nombre_lower)
            apoderado = nombres_apoderados.get(nombre_lower, "Apoderado")

            if not correo:
                continue

            subject = f"[PRUEBA] Resumen Mensual - {worksheet.title}"
            body = f"""Hola {apoderado},

Este es un resumen de prueba.

✅ Asistencia: {asist_pct:.1f}%
❌ Inasistencia: {inasist_pct:.1f}%

Saludos,
Preuniversitario CIMMA"""
            if send_email(correo, subject, body):
                st.success(f"📧 Correo de prueba enviado a {correo}")
            else:
                st.error(f"❌ Error al enviar a {correo}")

# ==============================
# APP PRINCIPAL (PRUEBA LOCAL)
# ==============================

st.title("🧪 Prueba Local - Asistencia CIMMA")

# Botón para probar el resumen mensual
if st.button("📤 Probar Envío de Resumen Mensual"):
    send_monthly_summary_test()

# Resto de la app (registro de asistencia)
courses = load_courses_local()
if not courses:
    st.error("❌ No se cargó CLASES 2026.xlsx")
    st.stop()

curso = st.selectbox("Curso", list(courses.keys()))
data = courses[curso]

st.write(f"Profesor: {data['profesor']}")
fecha = st.selectbox("Fecha", data["fechas"])

asistencia = {}
for est in data["estudiantes"]:
    asistencia[est] = st.checkbox(est)

if st.button("💾 Guardar (solo prueba)"):
    st.success("✅ Simulación de guardado completada.")