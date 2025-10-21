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
import socket
from email.utils import formatdate
import traceback
import plotly.express as px
import time
import functools

# ==============================
# SISTEMA DE RETRY Y BACKOFF
# ==============================

def retry_with_backoff(max_retries=5, base_delay=1, max_delay=32):
    """Decorador para reintentos con backoff exponencial"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            retries = 0
            while retries <= max_retries:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if "429" in str(e) and retries < max_retries:
                        delay = min(base_delay * (2 ** retries) + random.uniform(0, 1), max_delay)
                        time.sleep(delay)
                        retries += 1
                    else:
                        raise e
            return func(*args, **kwargs)
        return wrapper
    return decorator

# ==============================
# SISTEMA DE CACHÉ INTELIGENTE
# ==============================

class CacheInteligente:
    """Sistema de caché inteligente con invalidación automática"""
    
    def __init__(self):
        self.cache_data = {}
        self.stats = {
            'hits': 0,
            'misses': 0,
            'invalidaciones': 0
        }
    
    def cached(self, ttl=1800, max_size=100, dependencias=None):
        """Decorador de caché inteligente"""
        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                # Generar clave única
                cache_key = f"{func.__name__}_{str(args)}_{str(kwargs)}"
                
                # Verificar si está en caché y es válido
                if (cache_key in self.cache_data and 
                    datetime.now() < self.cache_data[cache_key]['expira'] and
                    not self._dependencias_invalidadas(cache_key, dependencias)):
                    
                    self.stats['hits'] += 1
                    return self.cache_data[cache_key]['data']
                
                # Cache miss - ejecutar función
                self.stats['misses'] += 1
                result = func(*args, **kwargs)
                
                # Guardar en caché
                self.cache_data[cache_key] = {
                    'data': result,
                    'expira': datetime.now() + timedelta(seconds=ttl),
                    'timestamp': datetime.now(),
                    'dependencias': dependencias or []
                }
                
                # Limpiar caché si excede tamaño máximo
                self._limpiar_cache_excedente(max_size)
                
                return result
            return wrapper
        return decorator
    
    def _dependencias_invalidadas(self, cache_key, dependencias):
        """Verifica si las dependencias han cambiado"""
        if not dependencias:
            return False
        
        for dep in dependencias:
            if dep in self.cache_data:
                # Si la dependencia es más reciente, invalidar
                if (self.cache_data[dep]['timestamp'] > 
                    self.cache_data[cache_key]['timestamp']):
                    self.invalidar(cache_key)
                    return True
        return False
    
    def invalidar(self, clave=None):
        """Invalida caché específico o completo"""
        if clave:
            if clave in self.cache_data:
                del self.cache_data[clave]
                self.stats['invalidaciones'] += 1
        else:
            self.cache_data.clear()
            self.stats['invalidaciones'] += len(self.cache_data)
    
    def get_stats(self):
        """Estadísticas de uso del caché"""
        total_requests = self.stats['hits'] + self.stats['misses']
        hit_rate = (self.stats['hits'] / total_requests * 100) if total_requests > 0 else 0
        return {
            'total_entradas': len(self.cache_data),
            'hit_rate': f"{hit_rate:.1f}%",
            **self.stats
        }
    
    def _limpiar_cache_excedente(self, max_size):
        """Limpia caché si excede el tamaño máximo"""
        if len(self.cache_data) > max_size:
            # Eliminar las entradas más antiguas
            claves_ordenadas = sorted(
                self.cache_data.keys(),
                key=lambda k: self.cache_data[k]['timestamp']
            )
            for clave in claves_ordenadas[:len(self.cache_data) - max_size]:
                del self.cache_data[clave]

# Instancia global de caché
cache_manager = CacheInteligente()

# ==============================
# SISTEMA DE FECHAS COMPLETADAS OPTIMIZADO
# ==============================

class SistemaFechasCompletadas:
    """Sistema para gestionar fechas completadas y pendientes - OPTIMIZADO"""
    
    def __init__(self):
        self.client = None
        self.sheet_id = st.secrets["google"]["asistencia_sheet_id"]
        self._cache_fechas = {}
        self._cache_timestamp = {}
        self.CACHE_TTL = 1800  # 30 minutos
    
    @retry_with_backoff(max_retries=3, base_delay=2)
    def _get_client(self):
        """Obtiene el cliente de Google Sheets con reintentos"""
        if self.client is None:
            self.client = get_client()
        return self.client
    
    def obtener_fechas_completadas(self, curso):
        """Obtiene las fechas ya registradas para un curso - OPTIMIZADO"""
        # Verificar caché local primero
        cache_key = f"fechas_{curso}"
        current_time = time.time()
        
        if (cache_key in self._cache_fechas and 
            cache_key in self._cache_timestamp and
            current_time - self._cache_timestamp[cache_key] < self.CACHE_TTL):
            return self._cache_fechas[cache_key]
        
        try:
            client = self._get_client()
            if not client:
                return []
                
            sheet = client.open_by_key(self.sheet_id)
            try:
                # Leer solo una vez y procesar localmente
                fechas_sheet = sheet.worksheet("FECHAS_COMPLETADAS")
                all_data = fechas_sheet.get_all_values()
                
                # Procesamiento local sin múltiples llamadas a la API
                fechas_curso = []
                if len(all_data) > 1:  # Si hay datos además del header
                    headers = [h.strip().upper() for h in all_data[0]]
                    
                    # Encontrar índices de columnas
                    curso_idx = headers.index("CURSO") if "CURSO" in headers else 0
                    fecha_idx = headers.index("FECHA") if "FECHA" in headers else 1
                    completada_idx = headers.index("COMPLETADA") if "COMPLETADA" in headers else 2
                    
                    for row in all_data[1:]:
                        if (len(row) > max(curso_idx, fecha_idx, completada_idx) and
                            row[curso_idx].strip() == curso and 
                            row[completada_idx].strip().upper() == "SI"):
                            fechas_curso.append(row[fecha_idx].strip())
                
                # Actualizar caché
                self._cache_fechas[cache_key] = fechas_curso
                self._cache_timestamp[cache_key] = current_time
                
                return fechas_curso
                
            except gspread.exceptions.WorksheetNotFound:
                return []
                
        except Exception as e:
            if "429" in str(e):
                st.warning("⚠️ Límite temporal de consultas alcanzado. Usando caché...")
                return self._cache_fechas.get(cache_key, [])
            st.error(f"Error al cargar fechas completadas: {e}")
            return []
    
    @retry_with_backoff(max_retries=3, base_delay=2)
    def marcar_fecha_completada(self, curso, fecha):
        """Marca una fecha como completada con reintentos"""
        try:
            client = self._get_client()
            if not client:
                return False
                
            sheet = client.open_by_key(self.sheet_id)
            try:
                fechas_sheet = sheet.worksheet("FECHAS_COMPLETADAS")
            except gspread.exceptions.WorksheetNotFound:
                fechas_sheet = sheet.add_worksheet("FECHAS_COMPLETADAS", 1000, 4)
                fechas_sheet.append_row(["Curso", "Fecha", "Completada", "Timestamp"])
            
            # Verificar si ya existe usando procesamiento local
            all_data = fechas_sheet.get_all_values()
            existe = False
            
            if len(all_data) > 1:
                headers = [h.strip().upper() for h in all_data[0]]
                curso_idx = headers.index("CURSO") if "CURSO" in headers else 0
                fecha_idx = headers.index("FECHA") if "FECHA" in headers else 1
                
                for row in all_data[1:]:
                    if (len(row) > max(curso_idx, fecha_idx) and
                        row[curso_idx].strip() == curso and 
                        row[fecha_idx].strip() == fecha):
                        existe = True
                        break
            
            if not existe:
                fechas_sheet.append_row([
                    curso,
                    fecha,
                    "SI",
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ])
            
            # Limpiar caché específico
            cache_key = f"fechas_{curso}"
            if cache_key in self._cache_fechas:
                del self._cache_fechas[cache_key]
            if cache_key in self._cache_timestamp:
                del self._cache_timestamp[cache_key]
                
            return True
            
        except Exception as e:
            st.error(f"Error al marcar fecha como completada: {e}")
            return False
    
    @retry_with_backoff(max_retries=3, base_delay=2)
    def reactivar_fecha(self, curso, fecha):
        """Reactivar una fecha completada (solo administradores)"""
        try:
            client = self._get_client()
            if not client:
                return False
                
            sheet = client.open_by_key(self.sheet_id)
            fechas_sheet = sheet.worksheet("FECHAS_COMPLETADAS")
            
            # Buscar y actualizar el registro usando procesamiento local
            all_data = fechas_sheet.get_all_values()
            encontrado = False
            
            if len(all_data) > 1:
                headers = [h.strip().upper() for h in all_data[0]]
                curso_idx = headers.index("CURSO") if "CURSO" in headers else 0
                fecha_idx = headers.index("FECHA") if "FECHA" in headers else 1
                completada_idx = headers.index("COMPLETADA") if "COMPLETADA" in headers else 2
                
                for i, row in enumerate(all_data[1:], start=2):
                    if (len(row) > max(curso_idx, fecha_idx, completada_idx) and
                        row[curso_idx].strip() == curso and 
                        row[fecha_idx].strip() == fecha):
                        fechas_sheet.update_cell(i, completada_idx + 1, "NO")
                        encontrado = True
                        break
            
            if encontrado:
                # Limpiar caché específico
                cache_key = f"fechas_{curso}"
                if cache_key in self._cache_fechas:
                    del self._cache_fechas[cache_key]
                if cache_key in self._cache_timestamp:
                    del self._cache_timestamp[cache_key]
                return True
            else:
                st.warning("No se encontró la fecha especificada")
                return False
                
        except Exception as e:
            st.error(f"Error al reactivar fecha: {e}")
            return False
    
    def obtener_estadisticas_fechas(self, curso, fechas_totales):
        """Obtiene estadísticas de fechas completadas vs pendientes"""
        fechas_completadas = self.obtener_fechas_completadas(curso)
        fechas_pendientes = [f for f in fechas_totales if f not in fechas_completadas]
        
        return {
            "completadas": len(fechas_completadas),
            "pendientes": len(fechas_pendientes),
            "total": len(fechas_totales),
            "porcentaje_completado": (len(fechas_completadas) / len(fechas_totales) * 100) if fechas_totales else 0,
            "fechas_completadas": fechas_completadas,
            "fechas_pendientes": fechas_pendientes
        }
    
    def limpiar_cache(self):
        """Limpia todo el caché local"""
        self._cache_fechas.clear()
        self._cache_timestamp.clear()

# Instancia global del sistema de fechas
sistema_fechas = SistemaFechasCompletadas()

# ==============================
# CONFIGURACIÓN Y CONEXIONES OPTIMIZADAS
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

@retry_with_backoff(max_retries=3, base_delay=2)
def send_email(to_email: str, subject: str, body: str) -> bool:
    """Envía email con mejor feedback de diagnóstico"""
    try:
        smtp_server = st.secrets["EMAIL"]["smtp_server"]
        smtp_port = int(st.secrets["EMAIL"]["smtp_port"])
        sender_email = st.secrets["EMAIL"]["sender_email"]
        sender_password = st.secrets["EMAIL"]["sender_password"]
        
        # Crear mensaje
        msg = MIMEMultipart()
        msg["From"] = sender_email
        msg["To"] = to_email
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=True)
        msg.attach(MIMEText(body, "plain"))
        
        # Enviar email
        server = smtplib.SMTP(smtp_server, smtp_port, timeout=30)
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(msg)
        server.quit()
        
        return True
        
    except Exception as e:
        error_msg = f"❌ Error enviando email a {to_email}: {str(e)}"
        st.error(error_msg)
        return False

def generate_2fa_code():
    return ''.join(random.choices(string.digits, k=6))

# ==============================
# CARGA DE DATOS OPTIMIZADA
# ==============================

@retry_with_backoff(max_retries=3, base_delay=2)
@cache_manager.cached(ttl=3600, dependencias=['cursos'])
def load_courses():
    """Carga optimizada de cursos con manejo de límites"""
    try:
        client = get_client()
        if not client:
            return {}
        
        clases_sheet = client.open_by_key(st.secrets["google"]["clases_sheet_id"])
        courses = {}
        
        # Leer todas las hojas de una vez
        worksheets = clases_sheet.worksheets()
        
        for worksheet in worksheets:
            sheet_name = worksheet.title
            try:
                # Leer todos los valores de una sola vez
                all_values = worksheet.get_all_values()
                if not all_values:
                    continue
                    
                colA = [cell.strip() for cell in all_values[0] if isinstance(cell, str) and cell.strip()]
                colA_upper = [s.upper() for s in colA]
                
                # Buscar índices de una sola vez
                try:
                    idx_prof = colA_upper.index("PROFESOR")
                    idx_dia = colA_upper.index("DIA") 
                    idx_curso = colA_upper.index("CURSO")
                    idx_fechas = colA_upper.index("FECHAS")
                    idx_estudiantes = colA_upper.index("NOMBRES ESTUDIANTES")
                except ValueError:
                    continue
                
                # Extraer datos
                profesor = all_values[idx_prof + 1][0] if len(all_values) > idx_prof + 1 else ""
                dia = all_values[idx_dia + 1][0] if len(all_values) > idx_dia + 1 else ""
                curso_id = all_values[idx_curso + 1][0] if len(all_values) > idx_curso + 1 else ""
                horario = all_values[idx_curso + 2][0] if len(all_values) > idx_curso + 2 else ""
                
                # Procesar fechas y estudiantes localmente
                fechas = []
                for i in range(idx_fechas + 1, idx_estudiantes):
                    if i < len(all_values) and all_values[i] and all_values[i][0]:
                        fechas.append(all_values[i][0].strip())
                
                estudiantes = []
                for i in range(idx_estudiantes + 1, len(all_values)):
                    if all_values[i] and all_values[i][0]:
                        estudiantes.append(all_values[i][0].strip())
                
                estudiantes = sorted([e for e in estudiantes if e.strip()])
                
                if profesor and dia and curso_id and horario and estudiantes:
                    courses[sheet_name] = {
                        "profesor": profesor,
                        "dia": dia,
                        "horario": horario,
                        "curso_id": curso_id,
                        "fechas": fechas or ["Sin fechas"],
                        "estudiantes": estudiantes
                    }
                    
            except Exception as e:
                continue
                
        return courses
        
    except Exception as e:
        st.error(f"Error cargando cursos: {e}")
        return {}

@retry_with_backoff(max_retries=3, base_delay=2)
@cache_manager.cached(ttl=7200)
def load_emails():
    """Carga optimizada de emails"""
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
        if not data:
            return {}, {}
        emails = {}
        nombres_apoderados = {}
        for row in data:
            nombre_estudiante = str(row.get("NOMBRE ESTUDIANTE", "")).strip().lower()
            nombre_apoderado = str(row.get("NOMBRE APODERADO", "")).strip()
            mail_apoderado = str(row.get("MAIL APODERADO", "")).strip()
            if not nombre_estudiante:
                continue
            if mail_apoderado:
                emails[nombre_estudiante] = mail_apoderado
                nombres_apoderados[nombre_estudiante] = nombre_apoderado
        return emails, nombres_apoderados
    except Exception as e:
        st.error(f"❌ Error cargando emails: {e}")
        return {}, {}

@retry_with_backoff(max_retries=3, base_delay=2)
@cache_manager.cached(ttl=1800)
def load_all_asistencia():
    """Carga optimizada de datos de asistencia"""
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
                continue
            all_values = all_values[3:]
            headers = all_values[0]
            headers = [h.strip().upper() for h in headers if h.strip()]
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
            continue
    df = pd.DataFrame(all_data)
    if not df.empty:
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
                if ' de ' in fecha_str:
                    partes = fecha_str.split(' de ')
                    if len(partes) == 3:
                        dia = partes[0].strip().zfill(2)
                        mes_str = partes[1].strip()
                        año = partes[2].strip()
                        for mes_es, mes_num in meses_espanol.items():
                            if mes_es in mes_str:
                                fecha_iso = f"{año}-{mes_num}-{dia}"
                                return pd.to_datetime(fecha_iso, format='%Y-%m-%d', errors='coerce')
                elif '/' in fecha_str:
                    return pd.to_datetime(fecha_str, format='%d/%m/%Y', errors='coerce')
                elif '-' in fecha_str and len(fecha_str) == 10:
                    return pd.to_datetime(fecha_str, format='%Y-%m-%d', errors='coerce')
                return pd.to_datetime(fecha_str, errors='coerce')
            except Exception:
                return pd.NaT
        df["Fecha"] = df["Fecha"].apply(convertir_fecha_manual)
    return df

# ==============================
# COMPONENTES DE UI MEJORADOS
# ==============================

def aplicar_tema_moderno():
    """Aplica un tema visual moderno y consistente"""
    st.markdown(f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    
    * {{
        font-family: 'Inter', sans-serif;
    }}
    
    .main-header {{
        color: #1A3B8F;
        font-weight: 700;
        font-size: 2.5rem;
        margin-bottom: 1rem;
        border-bottom: 3px solid #1A3B8F;
        padding-bottom: 0.5rem;
    }}
    
    .section-header {{
        color: #1A3B8F;
        font-weight: 600;
        font-size: 1.5rem;
        margin: 2rem 0 1rem 0;
    }}
    
    .stButton > button {{
        border-radius: 12px !important;
        padding: 0.75rem 1.5rem !important;
        font-weight: 600 !important;
        transition: all 0.3s ease !important;
        border: none !important;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1) !important;
    }}
    
    .stButton > button:hover {{
        transform: translateY(-2px) !important;
        box-shadow: 0 4px 8px rgba(0,0,0,0.15) !important;
    }}
    
    .card {{
        background: white;
        border-radius: 16px;
        padding: 1.5rem;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
        border: 1px solid #E5E7EB;
        margin: 1rem 0;
    }}
    </style>
    """, unsafe_allow_html=True)

def crear_header_moderno():
    """Crea un header moderno con logo y título"""
    col1, col2, col3 = st.columns([1, 3, 1])
    with col2:
        st.markdown('<h1 class="main-header">🎓 Preuniversitario CIMMA</h1>', unsafe_allow_html=True)
        st.markdown('<p style="text-align: center; color: #6B7280; font-size: 1.1rem;">Sistema de Gestión de Asistencia 2026</p>', unsafe_allow_html=True)

def boton_moderno(texto, tipo="primario", icono="", key=None):
    """Crea un botón moderno con icono"""
    colores = {
        "primario": "#1A3B8F",
        "secundario": "#6B7280", 
        "exito": "#10B981",
        "peligro": "#EF4444"
    }
    
    color = colores.get(tipo, "#1A3B8F")
    
    return st.button(f"{icono} {texto}", key=key, use_container_width=True)

# ==============================
# PANEL DE CONTROL DE LÍMITES
# ==============================

def panel_control_limites():
    """Panel para monitorear y controlar límites de API"""
    with st.sidebar.expander("🚦 Control de Límites API"):
        st.info("""
        **Límites de Google Sheets API:**
        - 100 solicitudes por 100 segundos por usuario
        - 500 solicitudes por 100 segundos por proyecto
        """)
        
        # Controles manuales
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("🔄 Limpiar Caché", use_container_width=True):
                cache_manager.invalidar()
                sistema_fechas.limpiar_cache()
                st.success("Caché limpiado")
                
        with col2:
            if st.button("⏸️ Pausar Consultas", use_container_width=True):
                time.sleep(5)  # Pausa de 5 segundos
                st.success("Pausa completada")
        
        # Estadísticas de uso
        st.metric("Entradas en Caché", len(cache_manager.cache_data))
        st.metric("Hit Rate Cache", cache_manager.get_stats()['hit_rate'])

def panel_monitoreo_cache():
    """Panel para monitorear estado del caché"""
    with st.sidebar.expander("📊 Estado del Caché"):
        stats = cache_manager.get_stats()
        
        st.metric("Entradas en Caché", stats['total_entradas'])
        st.metric("Hit Rate", stats['hit_rate'])
        st.metric("Cache Hits", stats['hits'])
        st.metric("Cache Misses", stats['misses'])
        
        if st.button("🔄 Limpiar Caché", use_container_width=True):
            cache_manager.invalidar()
            st.success("Caché limpiado")
            st.rerun()

# ==============================
# FUNCIONALIDADES PRINCIPALES
# ==============================

def enviar_resumen_asistencia(datos_filtrados, email_template):
    """Envía un resumen de asistencia a TODOS los apoderados con email registrado"""
    
    progress_placeholder = st.empty()
    status_placeholder = st.empty()
    
    progress_placeholder.info("🚀 INICIANDO PROCESO DE ENVÍO DE RESUMENES...")
    
    try:
        if datos_filtrados.empty:
            progress_placeholder.error("❌ ERROR: Los datos filtrados están VACÍOS")
            return False
        
        progress_placeholder.success(f"✅ Datos recibidos: {len(datos_filtrados)} registros")
        
        status_placeholder.info("🔄 Cargando información de apoderados...")
        emails, nombres_apoderados = load_emails()
        
        if not emails:
            progress_placeholder.error("❌ ERROR: No se encontraron emails de apoderados")
            return False
        
        estudiantes_filtrados = datos_filtrados['Estudiante'].unique()
        estudiantes_con_email = []
        estudiantes_sin_email = []
        
        for estudiante in estudiantes_filtrados:
            nombre_variantes = [
                estudiante.strip().lower(),
                estudiante.strip(),
                estudiante.lower(),
                estudiante
            ]
            
            email_encontrado = None
            for variante in nombre_variantes:
                if variante in emails:
                    email_encontrado = emails[variante]
                    break
            
            if email_encontrado:
                estudiantes_con_email.append({
                    'nombre_original': estudiante,
                    'email': email_encontrado,
                    'apoderado': nombres_apoderados.get(variante, "Apoderado")
                })
            else:
                estudiantes_sin_email.append(estudiante)
        
        if not estudiantes_con_email:
            progress_placeholder.error("🚫 No hay estudiantes con email registrado")
            return False
        
        with st.expander("👀 VER DETALLES DE ENVÍO PROGRAMADO", expanded=True):
            st.success(f"📧 **ENVÍO PROGRAMADO:** {len(estudiantes_con_email)} emails a enviar")
            
            if estudiantes_sin_email:
                st.warning(f"⚠️ {len(estudiantes_sin_email)} estudiantes sin email registrado")
        
        fecha_inicio = st.session_state.get('fecha_inicio', date.today())
        fecha_fin = st.session_state.get('fecha_fin', date.today())
        
        if boton_moderno("🚀 EJECUTAR ENVÍO DE RESUMENES", "exito", "📧", "execute_email_send"):
            progress_bar = st.progress(0)
            resultados = []
            emails_enviados = 0
            
            for i, est_data in enumerate(estudiantes_con_email):
                estudiante = est_data['nombre_original']
                correo_destino = est_data['email']
                nombre_apoderado = est_data['apoderado']
                
                status_placeholder.info(f"📨 Enviando {i+1}/{len(estudiantes_con_email)}: {estudiante}")
                
                datos_estudiante = datos_filtrados[datos_filtrados['Estudiante'] == estudiante]
                
                if datos_estudiante.empty:
                    continue
                
                total_clases = len(datos_estudiante)
                asistencias = datos_estudiante['Asistencia'].sum()
                ausencias = total_clases - asistencias
                porcentaje_asistencia = (asistencias / total_clases * 100) if total_clases > 0 else 0
                
                cursos_estudiante = datos_estudiante['Curso'].unique()
                resumen_cursos = []
                
                for curso in cursos_estudiante:
                    datos_curso = datos_estudiante[datos_estudiante['Curso'] == curso]
                    total_curso = len(datos_curso)
                    asistencias_curso = datos_curso['Asistencia'].sum()
                    porcentaje_curso = (asistencias_curso / total_curso * 100) if total_curso > 0 else 0
                    resumen_cursos.append(f"  • {curso}: {asistencias_curso}/{total_curso} clases ({porcentaje_curso:.1f}%)")
                
                subject = f"Resumen de Asistencia - {estudiante} - Preuniversitario CIMMA"
                
                body = email_template.format(
                    nombre_apoderado=nombre_apoderado,
                    estudiante=estudiante,
                    total_clases=total_clases,
                    asistencias=asistencias,
                    ausencias=ausencias,
                    porcentaje_asistencia=porcentaje_asistencia,
                    resumen_cursos="\n".join(resumen_cursos),
                    fecha_inicio=fecha_inicio.strftime('%d/%m/%Y'),
                    fecha_fin=fecha_fin.strftime('%d/%m/%Y')
                )
                
                with st.spinner(f"Enviando a {estudiante}..."):
                    exito = send_email(correo_destino, subject, body)
                
                if exito:
                    emails_enviados += 1
                    st.success(f"✅ **{i+1}/{len(estudiantes_con_email)}:** Email enviado a {estudiante}")
                else:
                    st.error(f"❌ **{i+1}/{len(estudiantes_con_email)}:** Falló envío a {estudiante}")
                
                resultados.append({
                    'estudiante': estudiante,
                    'exito': exito
                })
                
                progress_bar.progress((i + 1) / len(estudiantes_con_email))
            
            progress_placeholder.empty()
            status_placeholder.empty()
            progress_bar.empty()
            
            st.markdown("---")
            st.subheader("📊 RESULTADO FINAL DEL ENVÍO")
            
            exitosos = sum(1 for r in resultados if r['exito'])
            fallidos = len(resultados) - exitosos
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric("📧 Total Programados", len(resultados))
            with col2:
                st.metric("✅ Envíos Exitosos", exitosos)
            with col3:
                st.metric("❌ Envíos Fallidos", fallidos)
            
            if exitosos == len(resultados):
                st.balloons()
                st.success(f"🎉 **¡ÉXITO TOTAL!** Todos los {exitosos} emails fueron enviados")
                st.session_state.email_status = f"🎉 ¡ÉXITO! {exitosos} emails enviados"
            elif exitosos > 0:
                st.warning(f"⚠️ **ENVÍO PARCIALMENTE EXITOSO:** {exitosos} de {len(resultados)} emails enviados")
                st.session_state.email_status = f"⚠️ Envío parcial: {exitosos}/{len(resultados)} emails"
            else:
                st.error("❌ **FALLO TOTAL:** No se pudo enviar ningún email")
                st.session_state.email_status = "❌ Falló el envío de emails"
            
            return exitosos > 0
            
    except Exception as e:
        progress_placeholder.error(f"❌ ERROR CRÍTICO en el proceso: {str(e)}")
        st.session_state.email_status = f"❌ Error crítico: {str(e)}"
        return False

# ==============================
# PANEL ADMINISTRATIVO MEJORADO
# ==============================

def admin_panel_mejorado():
    if 'login_time' in st.session_state and 'timeout_duration' in st.session_state:
        if time.time() - st.session_state['login_time'] > st.session_state['timeout_duration']:
            st.error("❌ Sesión expirada por límite de tiempo.")
            st.session_state.clear()
            st.rerun()
            return
    
    st.markdown('<h2 class="section-header">📊 Panel Administrativo - Análisis de Asistencia</h2>', unsafe_allow_html=True)
    
    st.markdown(
        f'<div style="background: #F0F4FF; padding: 1rem; border-radius: 8px; margin: 1rem 0;">'
        f'<p style="margin: 0; color: #1A3B8B; font-size: 25px; font-weight: bold;">👋 Bienvenido/a, {st.session_state["user_name"]}</p>'
        f'</div>', 
        unsafe_allow_html=True
    )

    # Configuración de temporizador
    st.subheader("⏳ Configuración de Temporizador de Sesión")
    options_min = [30, 60, 90, 120, 150, 180, 210, 240, 270, 300]
    current_duration = int(st.session_state['timeout_duration'] / 60) if 'timeout_duration' in st.session_state else 30
    selected_min = st.selectbox("Selecciona duración de sesión (minutos)", options_min, 
                               index=options_min.index(current_duration) if current_duration in options_min else 0)
    
    col1, col2 = st.columns(2)
    with col1:
        if boton_moderno("Aplicar duración", "primario", "⚙️", "apply_duration"):
            st.session_state['timeout_duration'] = selected_min * 60
            st.session_state['login_time'] = time.time()
            st.success(f"✅ Duración aplicada: {selected_min} minutos")
            st.rerun()
    with col2:
        if boton_moderno("Mantener sesión abierta", "secundario", "🔄", "keep_alive"):
            st.session_state['login_time'] = time.time()
            st.success("✅ Sesión mantenida abierta")
            st.rerun()
    
    st.divider()
    
    # ==============================
    # GESTIÓN DE FECHAS COMPLETADAS (ADMIN)
    # ==============================
    
    st.markdown('<h2 class="section-header">📅 Gestión de Fechas Completadas</h2>', unsafe_allow_html=True)

    with st.expander("👁️ Visión Completa de Todas las Fechas", expanded=True):
        cursos = load_courses()
        
        if not cursos:
            st.error("❌ No se encontraron cursos")
            return
        
        curso_seleccionado_admin = st.selectbox(
            "Selecciona un curso para gestionar fechas:",
            list(cursos.keys()),
            key="admin_curso_select"
        )
        
        if curso_seleccionado_admin:
            data_curso = cursos[curso_seleccionado_admin]
            fechas_totales = data_curso["fechas"]
            
            # Obtener estadísticas de fechas
            stats = sistema_fechas.obtener_estadisticas_fechas(curso_seleccionado_admin, fechas_totales)
            
            # Mostrar estadísticas
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("📅 Total Fechas", stats["total"])
            with col2:
                st.metric("✅ Completadas", stats["completadas"])
            with col3:
                st.metric("⏳ Pendientes", stats["pendientes"])
            with col4:
                st.metric("📊 Progreso", f"{stats['porcentaje_completado']:.1f}%")
            
            # Tabla de fechas completadas
            st.subheader("📋 Fechas Completadas")
            if stats["fechas_completadas"]:
                st.markdown("**Haz clic sobre 🔄 para habilitar fecha en menú del profesor**")
                
                for i, fecha in enumerate(stats["fechas_completadas"]):
                    with st.container():
                        col1, col2 = st.columns([4, 2])
                        with col1:
                            st.write(f"**{i+1}.** ✅ {fecha}")
                        with col2:
                            if st.button("🔄 Reactivar Fecha", 
                                    key=f"reactivar_{curso_seleccionado_admin}_{fecha}",
                                    use_container_width=True,
                                    help="Haz clic para reactivar esta fecha y permitir nuevo registro"):
                                if sistema_fechas.reactivar_fecha(curso_seleccionado_admin, fecha):
                                    st.success(f"✅ Fecha '{fecha}' reactivada - Ahora disponible para registro")
                                    st.rerun()
                        
                        if i < len(stats["fechas_completadas"]) - 1:
                            st.markdown("---")
            else:
                st.info("ℹ️ No hay fechas completadas para este curso")

            # Marcado manual de fechas como completadas
            st.subheader("✅ Marcado Manual de Fechas")
            fechas_pendientes = [f for f in fechas_totales if f not in stats["fechas_completadas"]]
            if fechas_pendientes:
                fecha_manual = st.selectbox(
                    "Selecciona fecha para marcar como completada:",
                    fechas_pendientes,
                    key="fecha_manual_select_admin"
                )
                
                if fecha_manual and st.button("✅ Marcar como Completada", use_container_width=True, key="marcar_completada_admin"):
                    if sistema_fechas.marcar_fecha_completada(curso_seleccionado_admin, fecha_manual):
                        st.success(f"✅ Fecha {fecha_manual} marcada como completada")
                        st.rerun()
            else:
                st.info("🎉 ¡Todas las fechas ya están completadas!")
    
    st.divider()
    
    # ==============================
    # CARGA Y FILTRADO DE DATOS
    # ==============================
    
    with st.spinner("🔄 Cargando datos de asistencia..."):
        df = load_all_asistencia()
    
    if df.empty:
        st.error("❌ No se pudieron cargar los datos de asistencia.")
        return
    
    # Barra lateral - Filtros
    st.sidebar.header("📊 Información de Datos")
    st.sidebar.write(f"**Total de registros:** {len(df):,}")
    
    if not df.empty:
        st.sidebar.write(f"**Cursos encontrados:** {len(df['Curso'].unique())}")
        st.sidebar.write(f"**Estudiantes únicos:** {len(df['Estudiante'].unique())}")
    
    st.sidebar.header("🔍 Filtros de Datos")
    
    # Determinar rango de fechas
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
    
    # Selector de curso
    cursos = ["Todos"] + sorted(df['Curso'].unique().tolist())
    curso_seleccionado = st.sidebar.selectbox(
        "Seleccionar Curso",
        cursos,
        index=cursos.index(st.session_state.curso_seleccionado) if st.session_state.curso_seleccionado in cursos else 0,
        key="curso_select_admin"
    )
    st.session_state.curso_seleccionado = curso_seleccionado
    
    # Selector de estudiante
    if curso_seleccionado != "Todos":
        estudiantes_curso = df[df['Curso'] == curso_seleccionado]['Estudiante'].unique()
        estudiantes = ["Todos"] + sorted(estudiantes_curso.tolist())
    else:
        estudiantes = ["Todos"] + sorted(df['Estudiante'].unique().tolist())
    
    estudiante_seleccionado = st.sidebar.selectbox(
        "Seleccionar Estudiante",
        estudiantes,
        index=estudiantes.index(st.session_state.estudiante_seleccionado) if st.session_state.estudiante_seleccionado in estudiantes else 0,
        key="estudiante_select_admin"
    )
    st.session_state.estudiante_seleccionado = estudiante_seleccionado
    
    # Selectores de fecha
    col1, col2 = st.sidebar.columns(2)
    with col1:
        fecha_inicio = st.date_input(
            "Desde",
            value=st.session_state.fecha_inicio,
            min_value=fecha_min,
            max_value=fecha_max,
            key="fecha_inicio_admin"
        )
        st.session_state.fecha_inicio = fecha_inicio
    
    with col2:
        fecha_fin = st.date_input(
            "Hasta",
            value=st.session_state.fecha_fin,
            min_value=fecha_min,
            max_value=fecha_max,
            key="fecha_fin_admin"
        )
        st.session_state.fecha_fin = fecha_fin
    
    # Botón limpiar filtros
    if boton_moderno("🧹 Limpiar Filtros", "secundario", "🧹", "clear_filters_admin"):
        st.session_state.curso_seleccionado = "Todos"
        st.session_state.estudiante_seleccionado = "Todos"
        st.session_state.fecha_inicio = fecha_min
        st.session_state.fecha_fin = fecha_max
        st.rerun()
    
    # Aplicación de filtros
    datos_filtrados = df.copy()
    filtros_aplicados = []
    
    if st.session_state.curso_seleccionado != "Todos":
        datos_filtrados = datos_filtrados[datos_filtrados['Curso'] == st.session_state.curso_seleccionado]
        filtros_aplicados.append(f"📚 Curso: {st.session_state.curso_seleccionado}")
    
    if st.session_state.estudiante_seleccionado != "Todos":
        datos_filtrados = datos_filtrados[datos_filtrados['Estudiante'] == st.session_state.estudiante_seleccionado]
        filtros_aplicados.append(f"👤 Estudiante: {st.session_state.estudiante_seleccionado}")
    
    if 'Fecha' in datos_filtrados.columns and datos_filtrados['Fecha'].notna().any():
        datos_filtrados = datos_filtrados[
            (datos_filtrados['Fecha'].dt.date >= st.session_state.fecha_inicio) &
            (datos_filtrados['Fecha'].dt.date <= st.session_state.fecha_fin)
        ]
        filtros_aplicados.append(f"📅 Período: {st.session_state.fecha_inicio.strftime('%d/%m/%Y')} - {st.session_state.fecha_fin.strftime('%d/%m/%Y')}")
    
    # Mostrar datos filtrados
    if datos_filtrados.empty:
        st.error("🚫 No se encontraron datos con los filtros seleccionados")
        return
    
    st.success(f"✅ Encontrados {len(datos_filtrados):,} registros")
    if filtros_aplicados:
        st.info(" | ".join(filtros_aplicados))
    
    # Tabs para diferentes vistas
    tab1, tab2 = st.tabs(["📊 Datos", "📧 Envío Emails"])
    
    with tab1:
        # Mostrar datos en tabla
        st.dataframe(datos_filtrados, use_container_width=True, height=400)
    
    with tab2:
        # Sección de envío de emails
        st.markdown("---")
        st.markdown('<h2 class="section-header">📧 Envío de Notificaciones a Apoderados</h2>', unsafe_allow_html=True)
        
        with st.expander("📊 ENVÍO DE RESUMENES DE ASISTENCIA", expanded=True):
            st.info("**📋 Esta función enviará un resumen de asistencia a TODOS los apoderados** cuyos estudiantes aparezcan en los datos actualmente filtrados.")
            
            email_template = st.text_area(
                "**✏️ Plantilla de Email:**",
                value="""Hola {nombre_apoderado},

Este es un resumen automático de asistencia para el/la estudiante {estudiante}.

📊 RESUMEN GENERAL:
• Total de clases registradas: {total_clases}
• Asistencias: {asistencias}
• Ausencias: {ausencias}
• Porcentaje de asistencia: {porcentaje_asistencia:.1f}%

📚 DETALLE POR CURSO:
{resumen_cursos}

📅 Período analizado: {fecha_inicio} - {fecha_fin}

Para consultas específicas, por favor contacte a la administración.

Saludos cordiales,
Preuniversitario CIMMA 2026""",
                height=300,
                key="email_template_admin"
            )
            
            if boton_moderno("🚀 EJECUTAR ENVÍO DE RESUMENES", "exito", "📧", "execute_email_send_admin"):
                enviar_resumen_asistencia(datos_filtrados, email_template)

# ==============================
# APP PRINCIPAL MEJORADA (PROFESOR)
# ==============================

def main_app_mejorada():
    if 'login_time' in st.session_state and 'timeout_duration' in st.session_state:
        if time.time() - st.session_state['login_time'] > st.session_state['timeout_duration']:
            st.error("❌ Sesión expirada por límite de tiempo (5 minutos).")
            st.session_state.clear()
            st.rerun()
            return
    
    st.markdown('<h2 class="section-header">📱 Registro de Asistencia en Tiempo Real</h2>', unsafe_allow_html=True)
    
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
    
    # Selector de curso moderno
    curso_seleccionado = st.selectbox("🎓 Selecciona tu curso", list(cursos_filtrados.keys()), key="curso_select_profesor")
    data = cursos_filtrados[curso_seleccionado]
    
    # Información del curso
    col1, col2, col3 = st.columns(3)
    with col1:
        st.info(f"**👨‍🏫 Profesor:** {data['profesor']}")
    with col2:
        st.info(f"**📅 Día:** {data['dia']}")
    with col3:
        st.info(f"**⏰ Horario:** {data['horario']}")
    
    # ==============================
    # ESTADÍSTICAS DE FECHAS (PROFESOR)
    # ==============================
    
    st.markdown('<h3 class="section-header">📊 Estadísticas de Fechas</h3>', unsafe_allow_html=True)
    
    # Obtener estadísticas de fechas
    stats = sistema_fechas.obtener_estadisticas_fechas(curso_seleccionado, data["fechas"])
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("📅 Total Fechas", stats["total"])
    with col2:
        st.metric("✅ Completadas", stats["completadas"])
    with col3:
        st.metric("⏳ Pendientes", stats["pendientes"])
    with col4:
        st.metric("📊 Progreso", f"{stats['porcentaje_completado']:.1f}%")
    
    # Barra de progreso
    st.progress(stats["porcentaje_completado"] / 100)
    
    # Selección de realización de clase
    st.markdown('<h3 class="section-header">✅ Estado de la Clase</h3>', unsafe_allow_html=True)
    clase_realizada = st.radio(
        "¿Se realizó la clase?",
        ("Sí", "No"),
        index=0,
        horizontal=True,
        key="clase_realizada_profesor"
    )
    
    if clase_realizada == "No":
        motivo = st.text_area(
            "📝 Motivo de la no realización",
            placeholder="Ej: Feriado nacional, suspensión por evento escolar, emergencia, etc.",
            key="motivo_suspension_profesor"
        )
        
        # Mostrar solo fechas pendientes para suspensión
        fechas_pendientes = [f for f in data["fechas"] if f not in stats["fechas_completadas"]]
        
        if not fechas_pendientes:
            st.warning("ℹ️ Todas las fechas ya están completadas. Para registrar una suspensión, contacta a un administrador.")
            return
            
        fecha_seleccionada = st.selectbox("🗓️ Fecha afectada", fechas_pendientes, key="fecha_suspension_profesor")
        
        if boton_moderno("💾 Registrar suspensión", "peligro", "⏸️", "register_suspension_profesor"):
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
                    sheet.append_row(["Curso", "Fecha", "Estudiante", "Asistencia", "Hora Registro", "Información"])
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
                
                # Marcar fecha como completada (suspensión)
                sistema_fechas.marcar_fecha_completada(curso_seleccionado, fecha_seleccionada)
                
                st.success(f"✅ Suspensión registrada para la fecha **{fecha_seleccionada}**.")
                st.rerun()
                
            except Exception as e:
                st.error(f"❌ Error al registrar suspensión: {e}")
        return
    
    # ==============================
    # REGISTRO DE ASISTENCIA NORMAL
    # ==============================
    
    # Si la clase se realizó, mostrar solo fechas pendientes
    fechas_pendientes = [f for f in data["fechas"] if f not in stats["fechas_completadas"]]
    
    if not fechas_pendientes:
        st.warning("🎉 ¡Todas las fechas ya están completadas!")
        st.info("💡 Si necesitas registrar asistencia en una fecha ya completada, contacta a un administrador para reactivarla.")
        return
    
    fecha_seleccionada = st.selectbox("🗓️ Selecciona la fecha", fechas_pendientes, key="fecha_asistencia_profesor")
    
    # Verificar duplicados
    if fecha_seleccionada in stats["fechas_completadas"]:
        st.error("🚫 Esta fecha ya fue completada anteriormente.")
        st.info("💡 Si necesitas registrar asistencia en esta fecha, contacta a un administrador para reactivarla.")
        return
    
    st.markdown('<h3 class="section-header">👥 Registro de Asistencia de Estudiantes</h3>', unsafe_allow_html=True)
    
    estado_key = f"asistencia_estado_{curso_seleccionado}"
    if estado_key not in st.session_state:
        st.session_state[estado_key] = {est: True for est in data["estudiantes"]}
    asistencia_estado = st.session_state[estado_key]
    
    # Grid de botones de asistencia
    st.markdown("**Haz clic en cada estudiante para cambiar su estado de asistencia:**")
    
    for est in data["estudiantes"]:
        key = f"btn_{curso_seleccionado}_{est}"
        estado_actual = asistencia_estado[est]
        if estado_actual:
            if boton_moderno(f"✅ {est} — ASISTIÓ", "exito", "✅", key):
                asistencia_estado[est] = False
                st.rerun()
        else:
            if boton_moderno(f"❌ {est} — AUSENTE", "peligro", "❌", key):
                asistencia_estado[est] = True
                st.rerun()
    
    asistencia = asistencia_estado
    
    st.warning("📧 Al guardar, se enviará un reporte automático a los apoderados.")
    st.markdown("---")
    
    # Botón de guardar
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if boton_moderno("💾 Guardar Asistencia", "exito", "💾", "guardar_asistencia_profesor"):
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
                
                # Marcar fecha como completada
                sistema_fechas.marcar_fecha_completada(curso_seleccionado, fecha_seleccionada)
                
                st.success(f"✅ ¡Asistencia guardada para **{curso_seleccionado}**!")
                
                # Envío de emails
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
                    
                st.rerun()
                
            except Exception as e:
                st.error(f"❌ Error al guardar o enviar notificaciones: {e}")

# ==============================
# MENÚ LATERAL Y AUTENTICACIÓN
# ==============================

def main():
    st.set_page_config(
        page_title="Preuniversitario CIMMA : Asistencia Cursos 2026",
        page_icon="🎓",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # Aplicar tema moderno
    aplicar_tema_moderno()
    crear_header_moderno()
    
    with st.sidebar:
        st.image("https://raw.githubusercontent.com/juanrojas-40/asistencia-2026/main/LOGO.jpg", use_container_width=True)
        st.markdown('<div class="card">', unsafe_allow_html=True)
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
            st.session_state["login_time"] = time.time()
            st.session_state["timeout_duration"] = 5 * 60  # 5 minutos por defecto
        
        if st.session_state["user_type"] is None and not st.session_state["awaiting_2fa"]:
            user_type = st.radio("Selecciona tu rol", ["Profesor", "Administrador"], key="role_select")
            if user_type == "Profesor":
                profesores = st.secrets.get("profesores", {})
                if profesores:
                    nombre = st.selectbox("Nombre", list(profesores.keys()), key="prof_select")
                    clave = st.text_input("Clave", type="password", key="prof_pass")
                    if boton_moderno("Ingresar como Profesor", "primario", "👨‍🏫", "prof_login"):
                        if profesores.get(nombre) == clave:
                            st.session_state["user_type"] = "profesor"
                            st.session_state["user_name"] = nombre
                            st.session_state['login_time'] = time.time()
                            st.session_state['timeout_duration'] = 5 * 60  # 5 minutos
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
                    if boton_moderno("Ingresar como Admin", "primario", "👨‍💼", "admin_login"):
                        if admins.get(nombre) == clave:
                            code = generate_2fa_code()
                            email = admin_emails.get(nombre, "profereport@gmail.com")
                            subject = "Código de Verificación - Preuniversitario CIMMA"
                            body = f"""Estimado/a {nombre},

Su código de verificación para acceder al sistema es: 

{code}

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
            if boton_moderno("Verificar código", "primario", "🔒", "verify_2fa"):
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
                    st.session_state['login_time'] = time.time()
                    st.session_state['timeout_duration'] = 30 * 60  # 30 minutos
                    st.rerun()
                else:
                    st.session_state["2fa_attempts"] += 1
                    st.error(f"❌ Código incorrecto. Intentos restantes: {3 - st.session_state['2fa_attempts']}")
        else:
            st.success(f"👤 {st.session_state['user_name']}")
            
            # Panel de control de límites solo para admins
            if st.session_state["user_type"] == "admin":
                panel_control_limites()
                panel_monitoreo_cache()
            
            if boton_moderno("Cerrar sesión", "peligro", "🚪", "logout"):
                st.session_state.clear()
                st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
    
    # Mostrar contenido principal según el tipo de usuario
    if st.session_state["user_type"] is None:
        st.markdown("""
        <div style="text-align: center; padding: 4rem 2rem;">
            <h1 style="color: #1A3B8F; font-size: 3rem; margin-bottom: 1rem;">🎓 Preuniversitario CIMMA</h1>
            <h2 style="color: #6B7280; font-size: 1.5rem; margin-bottom: 2rem;">Sistema de Gestión de Asistencia 2026</h2>
            <div class="card" style="max-width: 600px; margin: 0 auto;">
                <h3 style="color: #1A3B8F;">👋 ¡Bienvenido!</h3>
                <div style="background: #F0F4FF; padding: 1rem; border-radius: 8px; margin: 1rem 0;">
                    <p style="margin: 0; color: #1A3B8F;">Por favor, inicia sesión desde el menú lateral izquierdo para acceder al sistema.</p>
                </div>  
            </div>
        </div>
        """, unsafe_allow_html=True)
        return
    
    if st.session_state["user_type"] == "admin":
        admin_panel_mejorado()
    else:
        main_app_mejorada()

if __name__ == "__main__":
    main()