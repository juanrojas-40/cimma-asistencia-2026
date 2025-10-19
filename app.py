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



# ==============================
# CARGA DE DATOS - emails
# ==============================

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
                fecha_str = row[fecha_col].strip() if fecha_col < len(row) and row[fecha_col] else ""
                estudiante = row[estudiante_col].strip() if estudiante_col < len(row) and row[estudiante_col] else ""
                hora_registro = row[hora_registro_col].strip() if (hora_registro_col is not None and hora_registro_col < len(row) and row[hora_registro_col]) else ""
                informacion = row[informacion_col].strip() if (informacion_col is not None and informacion_col < len(row) and row[informacion_col]) else ""

                all_data.append({
                    "Curso": curso,
                    "Fecha": fecha_str,
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
        # Diccionario completo de meses en español
        meses_espanol = {
            'enero': '01', 'febrero': '02', 'marzo': '03', 'abril': '04',
            'mayo': '05', 'junio': '06', 'julio': '07', 'agosto': '08',
            'septiembre': '09', 'octubre': '10', 'noviembre': '11', 'diciembre': '12',
            'ene': '01', 'feb': '02', 'mar': '03', 'abr': '04', 'may': '05', 'jun': '06',
            'jul': '07', 'ago': '08', 'sep': '09', 'oct': '10', 'nov': '11', 'dic': '12'
        }

        def convertir_fecha_manual(fecha_str):
            if not fecha_str or pd.isna(fecha_str) or fecha_str.strip() == "":
                return pd.NaT
            
            fecha_str = str(fecha_str).strip().lower()
            
            try:
                # Caso 1: Formato "6 de abril de 2026"
                if ' de ' in fecha_str:
                    partes = fecha_str.split(' de ')
                    if len(partes) == 3:
                        dia = partes[0].strip().zfill(2)  # Asegurar 2 dígitos
                        mes_str = partes[1].strip()
                        año = partes[2].strip()
                        
                        # Buscar el mes en el diccionario
                        for mes_es, mes_num in meses_espanol.items():
                            if mes_es in mes_str:
                                fecha_iso = f"{año}-{mes_num}-{dia}"
                                return pd.to_datetime(fecha_iso, format='%Y-%m-%d', errors='coerce')
                
                # Caso 2: Formato "6/4/2026" o "06/04/2026"
                elif '/' in fecha_str:
                    return pd.to_datetime(fecha_str, format='%d/%m/%Y', errors='coerce')
                
                # Caso 3: Formato "2026-04-06" (ISO)
                elif '-' in fecha_str and len(fecha_str) == 10:
                    return pd.to_datetime(fecha_str, format='%Y-%m-%d', errors='coerce')
                
                # Caso 4: Intentar cualquier otro formato con pandas
                return pd.to_datetime(fecha_str, errors='coerce')
                
            except Exception:
                return pd.NaT

        # Aplicar la conversión
        df["Fecha"] = df["Fecha"].apply(convertir_fecha_manual)
        
        # Verificar resultados
        fechas_convertidas = df["Fecha"].notna().sum()
        fechas_totales = len(df)
        
        st.success(f"✅ {fechas_convertidas} de {fechas_totales} fechas convertidas exitosamente")
        
        if df["Fecha"].isna().any():
            fechas_problematicas = df[df["Fecha"].isna()]["Fecha"].unique()
            st.warning(f"⚠️ {df['Fecha'].isna().sum()} fechas no pudieron ser convertidas")
            
            # Mostrar ejemplos de fechas problemáticas para debugging
            fechas_originales_problematicas = df[df["Fecha"].isna()]["Fecha_Original"].unique() if "Fecha_Original" in df.columns else df[df["Fecha"].isna()]["Fecha"].unique()
            st.info(f"📋 Ejemplos de fechas problemáticas: {list(fechas_originales_problematicas[:5])}")
    
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

    # Cargar datos
    df = load_all_asistencia()
    
    if df.empty:
        st.warning("No hay datos de asistencia aún.")
        return
 
    # Diccionario de meses en español
    meses_espanol = {
        'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4, 'mayo': 5, 'junio': 6,
        'julio': 7, 'agosto': 8, 'septiembre': 9, 'octubre': 10, 'noviembre': 11, 'diciembre': 12
    }
    
    def convertir_fecha_espanol(fecha_texto):
        if pd.isna(fecha_texto) or fecha_texto == '':
            return pd.NaT
        
        try:
            # Ejemplo: "6 de abril de 2026"
            partes = fecha_texto.lower().split(' de ')
            if len(partes) == 3:
                dia = int(partes[0].strip())
                mes = meses_espanol[partes[1].strip()]
                año = int(partes[2].strip())
                return datetime(año, mes, dia)
        except Exception as e:
            st.warning(f"Error convirtiendo fecha: {fecha_texto} - {e}")
        
        return pd.NaT
    
    # Aplicar conversión si la columna Fecha existe y es texto
    if 'Fecha' in df.columns and df['Fecha'].dtype == 'object':
        df['Fecha'] = df['Fecha'].apply(convertir_fecha_espanol)
        st.success(f"✅ Fechas convertidas: {df['Fecha'].notna().sum()} fechas válidas")
        
        # Mostrar resultado de la conversión
        with st.expander("🔍 Resultado de conversión de fechas"):
            fechas_convertidas = df[df['Fecha'].notna()]['Fecha']
            if not fechas_convertidas.empty:
                st.write("**Fechas convertidas correctamente:**")
                st.write(f"- Rango: {fechas_convertidas.min().strftime('%d/%m/%Y')} a {fechas_convertidas.max().strftime('%d/%m/%Y')}")
                st.write("**Ejemplos de fechas convertidas:**")
                st.write(fechas_convertidas.head(10))
            else:
                st.warning("⚠️ No se pudieron convertir las fechas")

    # Filtros en sidebar
    st.sidebar.header("📊 Información de Datos")
    st.sidebar.write(f"**Total de registros:** {len(df)}")
    
    if not df.empty:
        st.sidebar.write(f"**Cursos encontrados:** {len(df['Curso'].unique())}")
        st.sidebar.write(f"**Estudiantes únicos:** {len(df['Estudiante'].unique())}")
        
        # Información sobre fechas después de la conversión
        if 'Fecha' in df.columns and df['Fecha'].notna().any():
            fechas_validas = df[df['Fecha'].notna()]['Fecha']
            st.sidebar.write(f"**Rango de fechas:**")
            st.sidebar.write(f"{fechas_validas.min().strftime('%d/%m/%Y')} - {fechas_validas.max().strftime('%d/%m/%Y')}")
        else:
            st.sidebar.write("**❌ No hay fechas válidas**")

    # Filtros en sidebar
    st.sidebar.header("🔍 Filtros")
    
    # CORRECCIÓN: Inicializar session_state para los filtros
    if 'curso_seleccionado' not in st.session_state:
        st.session_state.curso_seleccionado = "Todos"
    if 'estudiante_seleccionado' not in st.session_state:
        st.session_state.estudiante_seleccionado = "Todos"
    
    # Fechas - usar el rango real de los datos después de la conversión
    if 'Fecha' in df.columns and df['Fecha'].notna().any():
        fecha_min = df['Fecha'].min().date()
        fecha_max = df['Fecha'].max().date()
    else:
        fecha_min = datetime(2026, 4, 1).date()
        fecha_max = datetime(2026, 12, 1).date()
    
    if 'fecha_inicio' not in st.session_state:
        st.session_state.fecha_inicio = fecha_min
    if 'fecha_fin' not in st.session_state:
        st.session_state.fecha_fin = fecha_max

    # CORRECCIÓN: Siempre mostrar los selectboxes, pero controlar sus valores con session_state
    # Lista de cursos
    cursos = ["Todos"] + sorted(df['Curso'].unique().tolist())
    curso_seleccionado = st.sidebar.selectbox(
        "Seleccionar Curso", 
        cursos, 
        index=cursos.index(st.session_state.curso_seleccionado) if st.session_state.curso_seleccionado in cursos else 0
    )
    
    # Actualizar session_state con la selección actual
    st.session_state.curso_seleccionado = curso_seleccionado
    
    # Lista de estudiantes (filtrada por curso si se selecciona uno)
    if curso_seleccionado != "Todos":
        estudiantes_curso = df[df['Curso'] == curso_seleccionado]['Estudiante'].unique()
        estudiantes = ["Todos"] + sorted(estudiantes_curso.tolist())
    else:
        estudiantes = ["Todos"] + sorted(df['Estudiante'].unique().tolist())
    
    estudiante_seleccionado = st.sidebar.selectbox(
        "Seleccionar Estudiante", 
        estudiantes, 
        index=estudiantes.index(st.session_state.estudiante_seleccionado) if st.session_state.estudiante_seleccionado in estudiantes else 0
    )
    
    # Actualizar session_state con la selección actual
    st.session_state.estudiante_seleccionado = estudiante_seleccionado
    
    col1, col2 = st.sidebar.columns(2)
    with col1:
        fecha_inicio = st.date_input(
            "Desde", 
            value=st.session_state.fecha_inicio, 
            min_value=fecha_min, 
            max_value=fecha_max
        )
        st.session_state.fecha_inicio = fecha_inicio
        
    with col2:
        fecha_fin = st.date_input(
            "Hasta", 
            value=st.session_state.fecha_fin, 
            min_value=fecha_min, 
            max_value=fecha_max
        )
        st.session_state.fecha_fin = fecha_fin

    # CORRECCIÓN: Botón para limpiar filtros - resetear session_state
    if st.sidebar.button("🧹 Limpiar Filtros", use_container_width=True):
        st.session_state.curso_seleccionado = "Todos"
        st.session_state.estudiante_seleccionado = "Todos"
        st.session_state.fecha_inicio = fecha_min
        st.session_state.fecha_fin = fecha_max
        st.rerun()

    # Aplicar filtros progresivamente
    datos_filtrados = df.copy()
    filtros_aplicados = []
    
    # Filtrar por curso
    if st.session_state.curso_seleccionado != "Todos":
        datos_filtrados = datos_filtrados[datos_filtrados['Curso'] == st.session_state.curso_seleccionado]
        filtros_aplicados.append(f"📚 Curso: {st.session_state.curso_seleccionado}")
    
    # Filtrar por estudiante
    if st.session_state.estudiante_seleccionado != "Todos":
        datos_filtrados = datos_filtrados[datos_filtrados['Estudiante'] == st.session_state.estudiante_seleccionado]
        filtros_aplicados.append(f"👤 Estudiante: {st.session_state.estudiante_seleccionado}")
    
    # Filtrar por fecha (solo si hay fechas válidas)
    if 'Fecha' in datos_filtrados.columns and datos_filtrados['Fecha'].notna().any():
        datos_filtrados = datos_filtrados[
            (datos_filtrados['Fecha'].dt.date >= st.session_state.fecha_inicio) & 
            (datos_filtrados['Fecha'].dt.date <= st.session_state.fecha_fin)
        ]
        filtros_aplicados.append(f"📅 Período: {st.session_state.fecha_inicio.strftime('%d/%m/%Y')} - {st.session_state.fecha_fin.strftime('%d/%m/%Y')}")

    # MOSTRAR RESULTADOS
    st.header("📈 Resultados del Análisis")
    
    if datos_filtrados.empty:
        st.error("🚫 No se encontraron datos con los filtros seleccionados")
        
        # Diagnóstico detallado
        with st.expander("🔍 Diagnóstico - ¿Por qué no hay datos?"):
            st.write("### Datos originales disponibles:")
            st.write(f"- **Total de registros:** {len(df)}")
            st.write(f"- **Cursos:** {', '.join(sorted(df['Curso'].unique()))}")
            st.write(f"- **Estudiantes:** {len(df['Estudiante'].unique())} estudiantes")
            
            if df['Fecha'].notna().any():
                fechas = df[df['Fecha'].notna()]['Fecha']
                st.write(f"- **Rango de fechas real:** {fechas.min().strftime('%d/%m/%Y')} - {fechas.max().strftime('%d/%m/%Y')}")
            else:
                st.write("- **❌ No hay fechas válidas en los datos**")
            
            st.write("### Filtros aplicados:")
            for filtro in filtros_aplicados:
                st.write(f"- {filtro}")
            
            st.write("### 💡 Sugerencias:")
            st.write("1. **Verifica las fechas** - Asegúrate de que el rango incluya datos existentes")
            st.write("2. **Prueba con 'Todos'** - Selecciona 'Todos' en curso o estudiante")
            st.write("3. **Revisa los datos** - Los filtros pueden estar muy restrictivos")
        
        # Mostrar muestra de datos originales
        st.info("### 📋 Muestra de datos disponibles (sin filtros):")
        muestra_df = df.head(10).copy()
        if 'Fecha' in muestra_df.columns:
            # CORRECCIÓN: Formato de fecha sin hora
            muestra_df['Fecha'] = muestra_df['Fecha'].dt.strftime('%d/%m/%Y')
        st.dataframe(muestra_df, use_container_width=True)
        
        return

    # Si hay datos, mostrar métricas y análisis
    st.success(f"✅ Encontrados {len(datos_filtrados)} registros")
    
    # Mostrar filtros aplicados
    if filtros_aplicados:
        st.info(" | ".join(filtros_aplicados))

    # MÉTRICAS PRINCIPALES
    st.subheader("📊 Métricas de Asistencia")
    
    total_registros = len(datos_filtrados)
    total_asistencias = datos_filtrados['Asistencia'].sum()
    total_ausencias = total_registros - total_asistencias
    porcentaje_asistencia = (total_asistencias / total_registros * 100) if total_registros > 0 else 0

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Registros", total_registros)
    with col2:
        st.metric("Asistencias", total_asistencias)
    with col3:
        st.metric("Ausencias", total_ausencias)
    with col4:
        st.metric("% Asistencia", f"{porcentaje_asistencia:.1f}%")

    # GRÁFICOS
    st.subheader("📈 Análisis Visual")
    
    # Gráfico 1: Asistencia por curso (solo si hay múltiples cursos)
    if len(datos_filtrados['Curso'].unique()) > 1:
        try:
            asistencia_por_curso = datos_filtrados.groupby('Curso')['Asistencia'].agg(['sum', 'count']).reset_index()
            asistencia_por_curso['Porcentaje'] = (asistencia_por_curso['sum'] / asistencia_por_curso['count'] * 100)
            
            fig1 = px.bar(asistencia_por_curso, x='Curso', y='Porcentaje', 
                         title='Porcentaje de Asistencia por Curso',
                         color='Porcentaje',
                         color_continuous_scale='Blues',
                         hover_data=['sum', 'count'],
                         text='Porcentaje')

            # AGREGAR ESTAS LÍNEAS PARA FORMATEAR EL TEXTO
            fig1.update_traces(texttemplate='%{text:.1f}%', 
                            textposition='inside',  # 'inside', 'outside', 'auto', etc.
                            textfont_size=16)           

            fig1.update_layout(uniformtext_minsize=8, 
                            uniformtext_mode='hide')

            st.plotly_chart(fig1, use_container_width=True)
        except Exception as e:
            st.error(f"Error en gráfico de cursos: {e}")
    else:
        curso_actual = datos_filtrados['Curso'].iloc[0] if len(datos_filtrados) > 0 else "N/A"
        st.info(f"📚 Mostrando datos del curso: **{curso_actual}**")

    # Gráfico 2: Asistencia por estudiante (solo si hay múltiples estudiantes)
    if len(datos_filtrados['Estudiante'].unique()) > 1:
        try:
            asistencia_por_estudiante = datos_filtrados.groupby('Estudiante')['Asistencia'].agg(['sum', 'count']).reset_index()
            asistencia_por_estudiante['Porcentaje'] = (asistencia_por_estudiante['sum'] / asistencia_por_estudiante['count'] * 100)
            asistencia_por_estudiante = asistencia_por_estudiante.sort_values('Porcentaje', ascending=False)
            
            fig2 = px.bar(asistencia_por_estudiante, x='Estudiante', y='Porcentaje',
                         title='Asistencia por Estudiante',
                         color='Porcentaje',
                         color_continuous_scale='Greens',
                         hover_data=['sum', 'count'])
            fig2.update_layout(xaxis_tickangle=-45)
            st.plotly_chart(fig2, use_container_width=True)
        except Exception as e:
            st.error(f"Error en gráfico de estudiantes: {e}")
    else:
        if len(datos_filtrados) > 0:
            estudiante_actual = datos_filtrados['Estudiante'].iloc[0]
            st.info(f"👤 Mostrando datos del estudiante: **{estudiante_actual}**")

    # Gráfico 3: Tendencia temporal (solo si hay fechas válidas)
    if 'Fecha' in datos_filtrados.columns and datos_filtrados['Fecha'].notna().any() and len(datos_filtrados) > 1:
        try:
            # Agrupar por fecha y calcular asistencia diaria
            asistencia_diaria = datos_filtrados.groupby(datos_filtrados['Fecha'].dt.date)['Asistencia'].agg(['sum', 'count']).reset_index()
            asistencia_diaria['Porcentaje'] = (asistencia_diaria['sum'] / asistencia_diaria['count'] * 100)
            asistencia_diaria['Fecha'] = pd.to_datetime(asistencia_diaria['Fecha'])
            
            fig3 = px.line(asistencia_diaria, x='Fecha', y='Porcentaje',
                          title='Tendencia de Asistencia Diaria',
                          markers=True,
                          hover_data=['sum', 'count'])
            fig3.update_layout(xaxis_title='Fecha', yaxis_title='Porcentaje de Asistencia (%)')
            st.plotly_chart(fig3, use_container_width=True)
        except Exception as e:
            st.error(f"Error en gráfico de tendencia: {e}")

    # TABLA DE DATOS DETALLADOS
    st.subheader("📋 Datos Detallados")
    
    # Preparar datos para mostrar
    datos_mostrar = datos_filtrados.copy()
    
    # CORRECCIÓN: Formatear fechas para mostrar SIN HORA
    if 'Fecha' in datos_mostrar.columns:
        # Crear columna formateada solo con fecha (sin hora)
        datos_mostrar['Fecha_Formateada'] = datos_mostrar['Fecha'].apply(
            lambda x: x.strftime('%d/%m/%Y') if pd.notna(x) else 'Sin fecha'  # Solo fecha, sin hora
        )
    else:
        datos_mostrar['Fecha_Formateada'] = 'Columna no disponible'
    
    # Seleccionar columnas para mostrar
    columnas_a_mostrar = ['Fecha_Formateada', 'Estudiante', 'Curso', 'Asistencia']
    
    # Agregar columnas adicionales si existen
    columnas_extra = ['Hora Registro', 'Información']
    for col in columnas_extra:
        if col in datos_mostrar.columns:
            columnas_a_mostrar.append(col)
    
    # Filtrar solo las columnas que existen
    columnas_finales = [col for col in columnas_a_mostrar if col in datos_mostrar.columns]
    
    # Mostrar tabla con nombres de columnas amigables
    nombres_amigables = {
        'Fecha_Formateada': 'Fecha',
        'Hora Registro': 'Hora',
        'Información': 'Información'
    }
    
    datos_tabla = datos_mostrar[columnas_finales].rename(columns=nombres_amigables)
    
    st.dataframe(datos_tabla, use_container_width=True, height=400)
    st.caption(f"Mostrando {len(datos_tabla)} registros")

    # OPCIONES DE EXPORTACIÓN
    st.subheader("📤 Exportar Datos")
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Preparar CSV
        csv_df = datos_filtrados.copy()
        if 'Fecha' in csv_df.columns:
            # En el CSV también usar solo fecha sin hora
            csv_df['Fecha'] = csv_df['Fecha'].apply(
                lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) else ''  # Solo fecha en CSV también
            )
        
        csv = csv_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            "💾 Descargar CSV",
            csv,
            "asistencia_filtrada.csv",
            "text/csv",
            use_container_width=True
        )
    
    with col2:
        # Preparar Excel
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            excel_df = datos_filtrados.copy()
            if 'Fecha' in excel_df.columns:
                # En Excel también usar solo fecha sin hora
                excel_df['Fecha'] = excel_df['Fecha'].apply(
                    lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) else ''
                )
            excel_df.to_excel(writer, index=False, sheet_name='Asistencia')
            
            # Agregar hoja de resumen
            resumen_data = {
                'Métrica': ['Total Registros', 'Asistencias', 'Ausencias', 'Porcentaje Asistencia', 'Período'],
                'Valor': [
                    total_registros,
                    total_asistencias,
                    total_ausencias,
                    f"{porcentaje_asistencia:.1f}%",
                    f"{st.session_state.fecha_inicio.strftime('%d/%m/%Y')} - {st.session_state.fecha_fin.strftime('%d/%m/%Y')}"
                ]
            }
            pd.DataFrame(resumen_data).to_excel(writer, index=False, sheet_name='Resumen')
            
        excel_data = output.getvalue()
        st.download_button(
            "📊 Descargar Excel",
            excel_data,
            "asistencia_filtrada.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

    # BOTONES DE CONTROL
    st.markdown("---")
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("🔄 Recargar Datos", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
    
    with col2:
        if st.button("📊 Ver Todos los Datos", use_container_width=True):
            st.rerun()

























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