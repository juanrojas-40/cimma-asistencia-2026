import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import json
from datetime import datetime, timedelta, time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import pytz
import pandas as pd
import random
import string
import io
from datetime import date

import plotly.express as px

# ==============================
# CONFIGURACIÓN Y CONEXIONES
# ==============================

@st.cache_resource
def get_client():
    try:
        creds_dict = json.loads(st.secrets["google"]["credentials"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=[
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
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

def generate_2fa_code():
    """Generate a random 6-digit 2FA code."""
    return ''.join(random.choices(string.digits, k=6))

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
        if worksheet.title in ["MAILS", "MEJORAS", "PROFESORES", "Respuestas de formulario 2", "AUDIT"]:
            continue

        try:
            all_values = worksheet.get_all_values()
            if not all_values or len(all_values) < 5:
                st.warning(f"⚠️ Hoja '{worksheet.title}' vacía o con menos de 5 filas. Saltando.")
                continue

            # Salta las primeras 3 filas de metadatos
            all_values = all_values[3:]
            headers = all_values[0]
            headers = [h.strip().upper() for h in headers if h.strip()]

            # Buscar índices de columnas
            curso_col = 0
            fecha_col = 1
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

            if asistencia_col is None or estudiante_col is None:
                st.warning(f"⚠️ Hoja '{worksheet.title}' no tiene columnas 'ASISTENCIA' o 'ESTUDIANTE'. Saltando.")
                continue

            for row in all_values[1:]:
                max_index = max(
                    curso_col,
                    fecha_col,
                    estudiante_col,
                    asistencia_col,
                    hora_registro_col or 0,
                    informacion_col or 0
                )
                if len(row) <= max_index:
                    continue

                try:
                    asistencia_val = int(row[asistencia_col]) if row[asistencia_col] else 0
                except (ValueError, TypeError):
                    asistencia_val = 0

                curso = row[curso_col].strip() if curso_col < len(row) and row[curso_col] else worksheet.title
                fecha = row[fecha_col].strip() if fecha_col < len(row) and row[fecha_col] else ""
                estudiante = row[estudiante_col].strip() if estudiante_col < len(row) and row[estudiante_col] else ""
                hora_registro = row[hora_registro_col].strip() if (hora_registro_col is not None and hora_registro_col < len(row) and row[hora_registro_col]) else ""
                informacion = row[informacion_col].strip() if (informacion_col is not None and informacion_col < len(row) and row[informacion_col]) else ""

                all_data.append({
                    "Curso": curso,
                    "Fecha": fecha,  # ← sigue siendo string por ahora
                    "Estudiante": estudiante,
                    "Asistencia": asistencia_val,
                    "Hora Registro": hora_registro,
                    "Información": informacion
                })

        except Exception as e:
            st.warning(f"⚠️ Error al procesar hoja '{worksheet.title}': {str(e)[:80]}")
            continue

    # ✅ Convertir a DataFrame y luego transformar "Fecha" a datetime
    df = pd.DataFrame(all_data)
    if not df.empty:
        # Convertir fechas de forma segura: errores → NaT
        df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")
    return df

# ==============================
# MENÚ LATERAL Y AUTENTICACIÓN
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

        # Inicializar session state
        if "user_type" not in st.session_state:
            st.session_state["user_type"] = None
            st.session_state["user_name"] = None
            st.session_state["2fa_code"] = None
            st.session_state["2fa_email"] = None
            st.session_state["awaiting_2fa"] = False
            st.session_state["2fa_user_name"] = None
            st.session_state["2fa_time"] = None
            st.session_state["2fa_attempts"] = 0

        if st.session_state["user_type"] is None and not st.session_state["awaiting_2fa"]:
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
                            # Generate and send 2FA code
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
                                st.rerun()
                            else:
                                st.error("❌ Error al enviar el código de verificación. Intenta de nuevo.")
                        else:
                            st.error("❌ Clave incorrecta")
                else:
                    st.error("No hay administradores o correos configurados en Secrets.")
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
                    st.rerun()
                elif st.session_state["2fa_attempts"] >= 3:
                    st.error("❌ Demasiados intentos fallidos. Intenta iniciar sesión de nuevo.")
                    st.session_state["awaiting_2fa"] = False
                    st.session_state["2fa_code"] = None
                    st.session_state["2fa_email"] = None
                    st.session_state["2fa_attempts"] = 0
                    st.rerun()
                elif code_input == st.session_state["2fa_code"]:
                    st.session_state["user_type"] = "admin"
                    st.session_state["user_name"] = st.session_state["2fa_user_name"]
                    st.session_state["awaiting_2fa"] = False
                    st.session_state["2fa_code"] = None
                    st.session_state["2fa_email"] = None
                    st.session_state["2fa_attempts"] = 0
                    st.session_state["2fa_time"] = None
                    st.rerun()
                else:
                    st.session_state["2fa_attempts"] += 1
                    st.error(f"❌ Código incorrecto. Intentos restantes: {3 - st.session_state['2fa_attempts']}")
        else:
            st.success(f"👤 {st.session_state['user_name']}")
            if st.button("Cerrar sesión"):
                st.session_state.clear()
                st.rerun()

    if st.session_state["user_type"] is None:
        st.title("📱 Registro de Asistencia")
        st.subheader("Preuniversitario CIMMA 2026")
        st.info("Por favor, inicia sesión desde el menú lateral izquierdo, que se despliega al hacer clic en el emoji »» .")
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

    # Mapear profesores y asignaturas desde cursos
    courses = load_courses()
    curso_to_prof = {k: v['profesor'] for k, v in courses.items()}
    df['Profesor'] = df['Curso'].map(curso_to_prof)
    df['Asignatura'] = df['Curso']  # Asumiendo que 'Curso' representa la asignatura

    # Asegurar que la columna Fecha esté en formato datetime y con timezone
    if not df.empty and 'Fecha' in df.columns:
        if df['Fecha'].dtype != 'datetime64[ns]':
            df['Fecha'] = pd.to_datetime(df['Fecha'], errors='coerce')
        
        # Si no tiene timezone, agregar Chile
        if df['Fecha'].dt.tz is None:
            chile_tz = pytz.timezone("America/Santiago")
            df['Fecha'] = df['Fecha'].dt.tz_localize(chile_tz, ambiguous='NaT', nonexistent='NaT')

    # Filtros en sidebar
    with st.sidebar:
        st.header("🔍 Filtros")

        cursos = ["Todos"] + sorted(df["Curso"].unique())
        curso_sel = st.selectbox("Curso/Asignatura", cursos)

        estudiantes = ["Todos"] + sorted(df["Estudiante"].unique())
        est_sel = st.selectbox("Alumno", estudiantes)

        profesores = ["Todos"] + sorted(df["Profesor"].dropna().unique())
        prof_sel = st.selectbox("Profesor", profesores)

        # RANGO DE FECHAS DINÁMICO
        st.subheader("📅 Rango de Fechas")
        
        current_year = datetime.now().year
        
        # Fechas límite del sistema (1 de abril a 1 de diciembre)
        system_start = datetime(current_year, 4, 1).date()  # 1 de abril
        system_end = datetime(current_year, 12, 1).date()   # 1 de diciembre
        
        # Obtener el rango real de fechas disponibles en los datos (excluyendo NaT)
        if not df.empty and df["Fecha"].notna().any():
            valid_dates = df[df["Fecha"].notna()]["Fecha"]
            min_date_data = valid_dates.min().date()
            max_date_data = valid_dates.max().date()
            
            # Usar el rango más restrictivo entre datos disponibles y sistema
            actual_min_date = max(system_start, min_date_data)
            actual_max_date = min(system_end, max_date_data)
        else:
            actual_min_date = system_start
            actual_max_date = system_end
        
        # Selectores de fecha con límites dinámicos
        col_fecha1, col_fecha2 = st.columns(2)
        with col_fecha1:
            start_date = st.date_input(
                "Fecha de inicio", 
                value=actual_min_date,
                min_value=actual_min_date,
                max_value=actual_max_date,
                key="start_date"
            )
        
        with col_fecha2:
            end_date = st.date_input(
                "Fecha de término", 
                value=actual_max_date,
                min_value=actual_min_date,
                max_value=actual_max_date,
                key="end_date"
            )
        
        # Validar que la fecha de inicio no sea mayor que la de término
        if start_date > end_date:
            st.error("❌ La fecha de inicio no puede ser mayor que la fecha de término")
            st.session_state['apply_filters'] = False
            start_date, end_date = end_date, start_date  # Intercambiar para evitar errores

        # Convertir a timestamp CON LA MISMA TIMEZONE que los datos
        chile_tz = pytz.timezone("America/Santiago")
        
        # Crear datetime objects con timezone - FORMA CORREGIDA
        start_datetime = chile_tz.localize(
            datetime.combine(start_date, time(0, 0, 0))
        )
        end_datetime = chile_tz.localize(
            datetime.combine(end_date, time(23, 59, 59))
        )

        # Botón para aplicar filtros
        if st.button("Aplicar Filtros", use_container_width=True):
            st.session_state['apply_filters'] = True
        else:
            st.session_state['apply_filters'] = st.session_state.get('apply_filters', False)

        # Mostrar información del rango disponible
        st.caption(f"📅 Período académico: {system_start.strftime('%d/%m/%Y')} - {system_end.strftime('%d/%m/%Y')}")

    # Aplicar filtros solo al presionar el botón
    filtered_df = df.copy()
    if 'apply_filters' in st.session_state and st.session_state['apply_filters']:
        # Aplicar filtros de selección
        if curso_sel != "Todos":
            filtered_df = filtered_df[filtered_df["Curso"] == curso_sel]
        if est_sel != "Todos":
            filtered_df = filtered_df[filtered_df["Estudiante"] == est_sel]
        if prof_sel != "Todos":
            filtered_df = filtered_df[filtered_df["Profesor"] == prof_sel]
        
        # Filtrar por rango de fechas - MANERA SEGURA
        try:
            # Primero eliminar valores NaT
            filtered_df = filtered_df[filtered_df["Fecha"].notna()]
            
            # Luego aplicar filtro de fechas
            mask = (
                (filtered_df["Fecha"] >= start_datetime) & 
                (filtered_df["Fecha"] <= end_datetime)
            )
            filtered_df = filtered_df[mask]
            
        except TypeError as e:
            st.error(f"Error en filtro de fechas: {e}")
            # Fallback: convertir a date para comparación simple
            filtered_df = filtered_df[
                (filtered_df["Fecha"].dt.date >= start_date) & 
                (filtered_df["Fecha"].dt.date <= end_date)
            ]

    # Mostrar información del rango de fechas aplicado
    if 'apply_filters' in st.session_state and st.session_state['apply_filters'] and not filtered_df.empty:
        st.success(f"📊 **Rango de fechas aplicado:** {start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')}")
        
        # Calcular días del período seleccionado
        dias_periodo = (end_date - start_date).days + 1
        st.caption(f"Período de {dias_periodo} día{'s' if dias_periodo > 1 else ''}")

    if filtered_df.empty:
        st.info("No hay datos que coincidan con los filtros seleccionados.")
        
        # Mostrar sugerencia si no hay datos pero hay datos en el rango completo - FORMA SEGURA
        if not df.empty:
            # Obtener fechas válidas (excluyendo NaT)
            valid_dates = df[df["Fecha"].notna()]["Fecha"]
            if not valid_dates.empty:
                min_date = valid_dates.min().strftime('%d/%m/%Y')
                max_date = valid_dates.max().strftime('%d/%m/%Y')
                date_range_info = f"Rango completo de datos: {min_date} - {max_date}"
            else:
                date_range_info = "No hay fechas válidas en los datos"
                
            st.caption(f"ℹ️ {date_range_info}")
            st.caption("💡 Prueba ajustar las fechas o filtros para ver datos")
        return

    # Métricas clave basadas en asistencia - TOTALMENTE DINÁMICAS
    col1, col2, col3, col4 = st.columns(4)
    
    total_registros = len(filtered_df)
    total_asistencias = filtered_df["Asistencia"].sum()
    total_ausencias = total_registros - total_asistencias
    porc_asistencia = (total_asistencias / total_registros * 100) if total_registros > 0 else 0
    
    # Calcular días únicos con clases en el período seleccionado (excluyendo NaT)
    dias_con_clases = filtered_df[filtered_df["Fecha"].notna()]["Fecha"].dt.date.nunique()
    total_dias_periodo = (end_date - start_date).days + 1
    
    with col1:
        st.metric("Porcentaje de Asistencia", f"{porc_asistencia:.2f}%")
    with col2:
        st.metric("Total Asistencias", total_asistencias)
    with col3:
        st.metric("Total Ausencias", total_ausencias)
    with col4:
        st.metric("Días con clases", f"{dias_con_clases}/{total_dias_periodo}")

    # Gráficos avanzados con títulos dinámicos
    st.subheader("📈 Análisis por Curso/Asignatura")
    if not filtered_df.empty:
        asist_curso = filtered_df.groupby("Curso")["Asistencia"].agg(['sum', 'count'])
        asist_curso['Porcentaje'] = (asist_curso['sum'] / asist_curso['count'] * 100)
        fig_curso = px.bar(
            asist_curso.reset_index(), 
            x="Curso", 
            y="Porcentaje",
            hover_data=['sum', 'count'], 
            title=f"Asistencia por Curso/Asignatura ({start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')})",
            color="Porcentaje", 
            color_continuous_scale="Blues"
        )
        st.plotly_chart(fig_curso)

    st.subheader("👤 Análisis por Alumno")
    if not filtered_df.empty:
        asist_est = filtered_df.groupby("Estudiante")["Asistencia"].agg(['sum', 'count'])
        asist_est['Porcentaje'] = (asist_est['sum'] / asist_est['count'] * 100)
        asist_est_sorted = asist_est.sort_values("Porcentaje", ascending=False).reset_index()
        fig_est = px.bar(
            asist_est_sorted, 
            x="Estudiante", 
            y="Porcentaje",
            hover_data=['sum', 'count'], 
            title=f"Asistencia por Alumno ({start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')})",
            color="Porcentaje", 
            color_continuous_scale="Greens"
        )
        fig_est.update_layout(xaxis_tickangle=-45)
        st.plotly_chart(fig_est)

    st.subheader("🧑‍🏫 Análisis por Profesor")
    if not filtered_df.empty:
        asist_prof = filtered_df.groupby("Profesor")["Asistencia"].agg(['sum', 'count'])
        asist_prof['Porcentaje'] = (asist_prof['sum'] / asist_prof['count'] * 100)
        fig_prof = px.pie(
            asist_prof.reset_index(), 
            values="Porcentaje", 
            names="Profesor",
            title=f"Distribución de Asistencia por Profesor ({start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')})",
            color_discrete_sequence=px.colors.qualitative.Pastel
        )
        st.plotly_chart(fig_prof)

    st.subheader("📅 Tendencia de Asistencia Diaria")
    if not filtered_df.empty:
        # Filtrar solo fechas válidas para el gráfico
        valid_date_df = filtered_df[filtered_df["Fecha"].notna()]
        if not valid_date_df.empty:
            asist_time = valid_date_df.groupby(valid_date_df["Fecha"].dt.date)["Asistencia"].agg(['sum', 'count'])
            asist_time['Porcentaje'] = (asist_time['sum'] / asist_time['count'] * 100)
            fig_time = px.line(
                asist_time.reset_index(), 
                x="Fecha", 
                y="Porcentaje",
                hover_data=['sum', 'count'], 
                title=f"Tendencia de Asistencia Diaria ({start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')})",
                markers=True
            )
            fig_time.update_layout(xaxis_title="Fecha", yaxis_title="Porcentaje de Asistencia (%)")
            st.plotly_chart(fig_time)
        else:
            st.info("No hay fechas válidas para mostrar la tendencia")

    # Mapa de calor
    st.subheader("🌡️ Mapa de Calor: Asistencia por Alumno y Fecha")
    if not filtered_df.empty:
        try:
            # Usar fecha sin timezone para el pivot, excluyendo NaT
            pivot_df = filtered_df[filtered_df["Fecha"].notna()].copy()
            if not pivot_df.empty:
                pivot_df['Fecha_Date'] = pivot_df['Fecha'].dt.date
                
                pivot_table = pivot_df.pivot_table(
                    index="Estudiante", 
                    columns="Fecha_Date", 
                    values="Asistencia", 
                    aggfunc="mean",
                    fill_value=0
                )
                fig_heatmap = px.imshow(
                    pivot_table, 
                    color_continuous_scale="RdYlGn",
                    title=f"Mapa de Calor de Asistencia ({start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')})",
                    aspect="auto"
                )
                st.plotly_chart(fig_heatmap)
            else:
                st.info("No hay fechas válidas para generar el mapa de calor")
        except Exception as e:
            st.warning(f"No se pudo generar el mapa de calor: {e}")

    # Tabla detallada interactiva - MANEJO SEGURO DE FECHAS
    st.subheader("📋 Registro Detallado")
    display_df = filtered_df.copy()
    
    # Función segura para formatear fechas
    def safe_date_format(x):
        if pd.isna(x):
            return "Sin fecha"
        try:
            return x.strftime("%Y-%m-%d %H:%M")
        except (AttributeError, ValueError):
            return "Fecha inválida"
    
    display_df["Fecha"] = display_df["Fecha"].apply(safe_date_format)
    st.dataframe(display_df, use_container_width=True)

    # Opciones de descarga
    st.subheader("📤 Exportar Datos")
    col_dl1, col_dl2 = st.columns(2)
    with col_dl1:
        # Preparar CSV sin problemas de timezone
        csv_df = filtered_df.copy()
        
        # Función segura para formatear fechas en CSV
        def safe_csv_date(x):
            if pd.isna(x):
                return ""
            try:
                return x.strftime('%Y-%m-%d %H:%M:%S')
            except (AttributeError, ValueError):
                return ""
        
        csv_df['Fecha'] = csv_df['Fecha'].apply(safe_csv_date)
        csv = csv_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            "📥 Descargar como CSV", 
            csv, 
            f"asistencia_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.csv", 
            "text/csv",
            use_container_width=True
        )
    with col_dl2:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            # Preparar datos para Excel
            excel_df = filtered_df.copy()
            # Remover timezone para Excel y manejar NaT
            excel_df['Fecha'] = excel_df['Fecha'].apply(
                lambda x: x.tz_localize(None) if pd.notna(x) else pd.NaT
            )
            excel_df.to_excel(writer, index=False, sheet_name='Asistencia')
            
            # Agregar hoja con resumen
            summary_data = {
                'Métrica': ['Período', 'Total Registros', 'Asistencias', 'Ausencias', 'Porcentaje Asistencia'],
                'Valor': [
                    f"{start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')}",
                    total_registros,
                    total_asistencias,
                    total_ausencias,
                    f"{porc_asistencia:.2f}%"
                ]
            }
            pd.DataFrame(summary_data).to_excel(writer, index=False, sheet_name='Resumen')
            
        excel_data = output.getvalue()
        st.download_button(
            "📥 Descargar como Excel", 
            excel_data, 
            f"asistencia_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.xlsx", 
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

    # Insights adicionales DINÁMICOS
    st.subheader("🔍 Insights Avanzados")
    if not filtered_df.empty:
        # Mejor y peor alumno
        top_est = asist_est_sorted.iloc[0]["Estudiante"] if not asist_est_sorted.empty else "N/A"
        top_porc = asist_est_sorted.iloc[0]["Porcentaje"] if not asist_est_sorted.empty else 0
        low_est = asist_est_sorted.iloc[-1]["Estudiante"] if not asist_est_sorted.empty else "N/A"
        low_porc = asist_est_sorted.iloc[-1]["Porcentaje"] if not asist_est_sorted.empty else 0
        
        # Curso con mejor asistencia
        mejor_curso = asist_curso.loc[asist_curso['Porcentaje'].idxmax()] if not asist_curso.empty else None
        peor_curso = asist_curso.loc[asist_curso['Porcentaje'].idxmin()] if not asist_curso.empty else None
        
        col_insight1, col_insight2 = st.columns(2)
        
        with col_insight1:
            st.write("**👥 Rendimiento por Alumno:**")
            st.write(f"• **Mejor alumno:** {top_est} ({top_porc:.1f}%)")
            st.write(f"• **Alumno con menor asistencia:** {low_est} ({low_porc:.1f}%)")
            st.write(f"• **Asistencia promedio:** {porc_asistencia:.1f}%")
            
        with col_insight2:
            st.write("**📚 Rendimiento por Curso:**")
            if mejor_curso is not None:
                st.write(f"• **Mejor curso:** {mejor_curso.name} ({mejor_curso['Porcentaje']:.1f}%)")
            if peor_curso is not None:
                st.write(f"• **Curso con menor asistencia:** {peor_curso.name} ({peor_curso['Porcentaje']:.1f}%)")
            st.write(f"• **Días con clases:** {dias_con_clases}")
        
        # Alertas basadas en el porcentaje dinámico
        if porc_asistencia < 70:
            st.error("⚠️ **Alerta:** La asistencia promedio es menor al 70%. Considerar acciones correctivas.")
        elif porc_asistencia < 80:
            st.warning("📋 **Atención:** La asistencia promedio está entre 70-80%. Monitorear situación.")
        else:
            st.success("✅ **Excelente:** La asistencia promedio es mayor al 80%.")

        # Estadísticas adicionales
        st.write(f"**📊 Estadísticas del período seleccionado:**")
        st.write(f"• Período analizado: {start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')}")
        st.write(f"• Total de registros: {total_registros}")
        st.write(f"• Ratio asistencia/ausencia: {total_asistencias}:{total_ausencias}")






























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
            if not client:
                st.error("Error connecting to Google Sheets")
                return
            sheet = client.open_by_key(st.secrets["google"]["asistencia_sheet_id"])
            try:
                mejoras_sheet = sheet.worksheet("MEJORAS")
            except gspread.exceptions.WorksheetNotFound:
                mejoras_sheet = sheet.add_worksheet("MEJORAS", 100, 3)
                mejoras_sheet.append_row(["Fecha", "Sugerencia", "Usuario"])
            mejoras_sheet.append_row([datetime.now().strftime("%Y-%m-%d %H:%M"), mejora, st.session_state["user_name"]])
            st.success("¡Gracias por tu aporte!")
        except Exception as e:
            st.error(f"Error al guardar sugerencia: {e}")

if __name__ == "__main__":
    main()