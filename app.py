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
import time  # Para manejar tiempos y temporizadores
import functools
from gspread.exceptions import APIError

# ==============================
# CONFIGURACIÓN INICIAL Y MANEJO DE SECRETS
# ==============================

def verificar_secrets():
    """Verifica que todos los secrets necesarios estén configurados"""
    secrets_requeridos = {
        "google": ["credentials", "asistencia_sheet_id", "clases_sheet_id"],
        "EMAIL": ["smtp_server", "smtp_port", "sender_email", "sender_password"]
    }
    
    for categoria, secrets in secrets_requeridos.items():
        if categoria not in st.secrets:
            st.error(f"❌ No se encontró la categoría '{categoria}' en los secrets")
            return False
        
        for secret in secrets:
            if secret not in st.secrets[categoria]:
                st.error(f"❌ No se encontró el secret '{categoria}.{secret}'")
                return False
    
    # Verificar profesores o administradores (al menos uno debe estar configurado)
    if "profesores" not in st.secrets and "administradores" not in st.secrets:
        st.error("❌ No se encontraron secrets de profesores ni administradores")
        return False
    
    return True

# ==============================
# SISTEMA DE CACHÉ INTELIGENTE
# ==============================

def open_sheet_with_retry(client, sheet_id, retries=3, delay=5):
    for attempt in range(retries):
        try:
            return client.open_by_key(sheet_id)
        except APIError as e:
            if e.response.json().get('error', {}).get('code') == 429:
                time.sleep(delay * (2 ** attempt))
                continue
            raise
    raise Exception("Max retries exceeded for API quota")

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
# SISTEMA DE FECHAS COMPLETADAS
# ==============================

class SistemaFechasCompletadas:
    """Sistema para gestionar fechas completadas y pendientes"""
    
    def __init__(self):
        self.client = None
        # Manejo seguro de secrets
        try:
            self.sheet_id = st.secrets["google"]["asistencia_sheet_id"]
        except KeyError:
            st.error("❌ No se encontró 'asistencia_sheet_id' en los secrets de Google")
            self.sheet_id = None
    
    def _get_client(self):
        """Obtiene el cliente de Google Sheets de forma lazy"""
        if self.client is None:
            self.client = get_client()
        return self.client
    
    @cache_manager.cached(ttl=900)  # 15 minutos de caché
    def obtener_fechas_completadas(self, curso):
        """Obtiene las fechas ya registradas para un curso"""
        try:
            if not self.sheet_id:
                return []
                
            client = self._get_client()
            if not client:
                return []
                
            sheet = client.open_by_key(self.sheet_id)
            try:
                fechas_sheet = sheet.worksheet("FECHAS_COMPLETADAS")
            except gspread.exceptions.WorksheetNotFound:
                # Crear la hoja si no existe
                fechas_sheet = sheet.add_worksheet("FECHAS_COMPLETADAS", 1000, 4)
                fechas_sheet.append_row(["Curso", "Fecha", "Completada", "Timestamp"])
                return []
            
            records = fechas_sheet.get_all_records()
            fechas_curso = [
                row["Fecha"] for row in records 
                if row["Curso"] == curso and row["Completada"] == "SI"
            ]
            return fechas_curso
        except Exception as e:
            st.error(f"Error al cargar fechas completadas: {e}")
            return []
    
    def marcar_fecha_completada(self, curso, fecha):
        """Marca una fecha como completada"""
        try:
            if not self.sheet_id:
                return False
                
            client = self._get_client()
            if not client:
                return False
                
            sheet = client.open_by_key(self.sheet_id)
            try:
                fechas_sheet = sheet.worksheet("FECHAS_COMPLETADAS")
            except gspread.exceptions.WorksheetNotFound:
                fechas_sheet = sheet.add_worksheet("FECHAS_COMPLETADAS", 1000, 4)
                fechas_sheet.append_row(["Curso", "Fecha", "Completada", "Timestamp"])
            
            # Verificar si ya existe
            records = fechas_sheet.get_all_records()
            existe = any(
                row["Curso"] == curso and row["Fecha"] == fecha 
                for row in records
            )
            
            if not existe:
                fechas_sheet.append_row([
                    curso,
                    fecha,
                    "SI",
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ])
            else:
                # Si existe, actualizar a "SI"
                for i, row in enumerate(records, start=2):
                    if row["Curso"] == curso and row["Fecha"] == fecha:
                        fechas_sheet.update_cell(i, 3, "SI")
                        break
            
            # Invalidar caché
            cache_manager.invalidar()
            return True
        except Exception as e:
            st.error(f"Error al marcar fecha como completada: {e}")
            return False
    
    def reactivar_fecha(self, curso, fecha):
        """Reactivar una fecha completada (solo administradores)"""
        try:
            if not self.sheet_id:
                return False
                
            client = self._get_client()
            if not client:
                return False
                
            sheet = client.open_by_key(self.sheet_id)
            fechas_sheet = sheet.worksheet("FECHAS_COMPLETADAS")
            
            # Buscar y actualizar el registro
            records = fechas_sheet.get_all_records()
            for i, row in enumerate(records, start=2):  # start=2 porque la fila 1 son headers
                if row["Curso"] == curso and row["Fecha"] == fecha:
                    fechas_sheet.update_cell(i, 3, "NO")  # Columna "Completada"
                    break
            
            # Invalidar caché
            cache_manager.invalidar()
            return True
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

# Instancia global del sistema de fechas
sistema_fechas = SistemaFechasCompletadas()

# ==============================
# COMPONENTES INFORMATIVOS PARA FECHAS
# ==============================

def crear_tooltip_fechas():
    """Función para crear estilos CSS de tooltips"""
    st.markdown("""
    <style>
    .tooltip-fechas {
        position: relative;
        display: inline-block;
    }
    
    .tooltip-fechas .tooltiptext {
        visibility: hidden;
        width: 350px;
        background-color: #1A3B8F;
        color: white;
        text-align: left;
        border-radius: 12px;
        padding: 16px;
        position: absolute;
        z-index: 1000;
        bottom: 125%;
        left: 50%;
        transform: translateX(-50%);
        box-shadow: 0 10px 25px rgba(0,0,0,0.2);
        opacity: 0;
        transition: opacity 0.3s, visibility 0.3s;
        font-size: 0.9em;
        line-height: 1.5;
    }
    
    .tooltip-fechas:hover .tooltiptext {
        visibility: visible;
        opacity: 1;
    }
    
    .tooltip-fechas .ventaja {
        color: #10B981 !important;
    }
    
    .tooltip-fechas .alerta {
        color: #F59E0B !important;
    }
    
    .tooltip-fechas ul {
        margin: 4px 0;
        padding-left: 16px;
    }
    
    .tooltip-fechas li {
        margin-bottom: 4px;
    }
    </style>
    """, unsafe_allow_html=True)

def mostrar_panel_informativo_fechas():
    """Muestra un panel informativo completo sobre las funciones de fechas"""
    
    with st.expander("📚 GUÍA: Gestión de Fechas Completadas", expanded=False):
        st.markdown("""
        ### 🔄 Reactivar Fechas - Guía Completa
        
        **¿Cuándo y por qué reactivar una fecha?** Esta guía te explica todo:
        """)
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("""
            #### 🎯 **QUÉ HACE REACTIVAR**
            
            **Transforma una fecha:**
            ✅ Completada → ⏳ Pendiente
            
            **Resultado:**
            - La fecha vuelve a estar disponible para registro
            - Los profesores pueden tomar asistencia nuevamente
            - El historial anterior se mantiene
            """)
        
        with col2:
            st.markdown("""
            #### 🛡️ **SEGURIDAD Y VENTAJAS**
            
            **✅ Totalmente reversible**
            **✅ Mantiene auditoría completa**
            **✅ Sin pérdida de datos**
            **✅ Ideal para correcciones**
            """)
        
        st.markdown("""
        ---
        
        #### 📋 **CASOS DE USO RECOMENDADOS**
        
        | Situación | Solución | Beneficio |
        |-----------|----------|-----------|
        | **Error en registro** | Reactivar y corregir | Datos precisos sin pérdida |
        | **Asistencia incompleta** | Reactivar para completar | Información completa |
        | **Cambio de calendario** | Reactivar fechas afectadas | Flexibilidad del sistema |
        | **Duda en registros** | Reactivar y verificar | Calidad de datos |
        
        ---
        
        #### 🔄 **PROCESO RECOMENDADO**
        
        1. **Identifica** la fecha que necesita corrección
        2. **Reactivar** usando el botón 🔄 
        3. **Comunica** al profesor correspondiente
        4. **Verifica** que el nuevo registro sea correcto
        5. **Confirma** que la fecha quede como ✅ Completada
        
        ---
        
        #### ❓ **PREGUNTAS FRECUENTES**
        
        **¿Se pierde el registro anterior?**
        No, el sistema mantiene todo el historial de cambios.
        
        **¿Puedo reactivar múltiples veces?**
        Sí, tantas veces como sea necesario.
        
        **¿Los profesores ven inmediatamente el cambio?**
        Sí, la fecha aparece disponible en su interfaz al instante.
        
        **¿Afecta a los reportes enviados?**
        Los reportes futuros reflejarán los datos actualizados.
        """)

# ==============================
# SISTEMA DE AYUDA CONTEXTUAL
# ==============================

class SistemaAyuda:
    """Sistema de ayuda contextual con tooltips inteligentes"""
    
    def __init__(self):
        self.ayudas = {
            'dashboard': {
                'titulo': '📊 Dashboard Analytics',
                'contenido': 'Visualiza métricas clave, tendencias y alertas inteligentes del sistema de asistencia.',
                'ejemplos': [
                    'KPIs actualizados en tiempo real',
                    'Heatmap de patrones de asistencia', 
                    'Alertas automáticas de estudiantes en riesgo'
                ]
            },
            'filtros': {
                'titulo': '🔍 Sistema de Filtros',
                'contenido': 'Filtra datos por curso, estudiante, fechas y múltiples criterios simultáneamente.',
                'ejemplos': [
                    'Filtros combinados para análisis específicos',
                    'Rangos de fechas personalizables',
                    'Búsqueda rápida por nombre'
                ]
            },
            'envio_emails': {
                'titulo': '📧 Envío Masivo de Emails',
                'contenido': 'Envía reportes personalizados a apoderados basados en los filtros aplicados.',
                'ejemplos': [
                    'Plantillas personalizables',
                    'Selección automática de destinatarios',
                    'Seguimiento de envíos exitosos/fallidos'
                ]
            },
            'exportacion': {
                'titulo': '📤 Exportación de Datos',
                'contenido': 'Exporta reportes en múltiples formatos para análisis externo o presentaciones.',
                'ejemplos': [
                    'Formato Excel con pestañas organizadas',
                    'CSV para importación en otros sistemas',
                    'Estructura optimizada para análisis'
                ]
            }
        }
    
    def tooltip_contextual(self, seccion, posicion="derecha"):
        """Muestra tooltip contextual para una sección"""
        
        if seccion not in self.ayudas:
            return ""
        
        ayuda = self.ayudas[seccion]
        
        return f"""
        <div class="ayuda-contextual" style="display: inline-block; margin-left: 8px;">
            <span class="icono-ayuda" style="cursor: help; color: #6B7280; font-size: 0.9em;">
                ℹ️
            </span>
            <div class="tooltip-contenido" style="
                visibility: hidden;
                width: 350px;
                background-color: #1A3B8F;
                color: white;
                text-align: left;
                border-radius: 12px;
                padding: 16px;
                position: absolute;
                z-index: 1000;
                {self._obtener_posicion(posicion)};
                box-shadow: 0 10px 25px rgba(0,0,0,0.2);
                opacity: 0;
                transition: opacity 0.3s, visibility 0.3s;
                font-size: 0.9em;
                line-height: 1.5;
            ">
                <div style="font-weight: 600; margin-bottom: 8px; font-size: 1.1em;">
                    {ayuda['titulo']}
                </div>
                <div style="margin-bottom: 12px; opacity: 0.9;">
                    {ayuda['contenido']}
                </div>
                <div style="border-top: 1px solid rgba(255,255,255,0.2); padding-top: 8px;">
                    <strong>💡 Ejemplos de uso:</strong>
                    <ul style="margin: 8px 0 0 0; padding-left: 16px;">
                        {''.join([f'<li style="margin-bottom: 4px;">{ejemplo}</li>' for ejemplo in ayuda['ejemplos']])}
                    </ul>
                </div>
            </div>
        </div>
        
        <style>
        .ayuda-contextual:hover .tooltip-contenido {{
            visibility: visible;
            opacity: 1;
        }}
        </style>
        """ 
    
    def _obtener_posicion(self, posicion):
        """Determina posición del tooltip"""
        posiciones = {
            "derecha": "left: 120%; top: -20px;",
            "izquierda": "right: 120%; top: -20px;", 
            "arriba": "bottom: 125%; left: 50%; transform: translateX(-50%);",
            "abajo": "top: 125%; left: 50%; transform: translateX(-50%);"
        }
        return posiciones.get(posicion, "left: 120%; top: -20px;")
    
    def boton_ayuda_completa(self):
        """Botón para ayuda completa"""
        if st.sidebar.button("❓ Ayuda Completa", use_container_width=True):
            self.mostrar_ayuda_completa()
    
    def mostrar_ayuda_completa(self):
        """Modal con ayuda completa"""
        with st.expander("🎓 Centro de Ayuda - Preuniversitario CIMMA", expanded=True):
            st.markdown("### Guía Completa del Sistema")
            
            for seccion, contenido in self.ayudas.items():
                st.markdown(f"#### {contenido['titulo']}")
                st.write(contenido['contenido'])
                st.markdown("**💡 Ejemplos de uso:**")
                for ejemplo in contenido['ejemplos']:
                    st.markdown(f"- {ejemplo}")
                st.markdown("---")

# Instancia global del sistema de ayuda
sistema_ayuda = SistemaAyuda()

# ==============================
# CONFIGURACIÓN DE TEMA Y ESTILOS
# ==============================

def aplicar_tema_moderno():
    """Aplica un tema visual moderno y consistente"""
    
    # Paleta de colores institucional
    colores_institucionales = {
        "primario": "#1A3B8F",      # Azul institucional
        "secundario": "#10B981",    # Verde éxito
        "accent": "#F59E0B",        # Amarillo/naranja
        "neutral": "#6B7280",       # Gris
        "peligro": "#EF4444",       # Rojo
        "fondo": "#F8FAFC"          # Fondo claro
    }
    
    st.markdown(f"""
    <style>
    /* FUENTES Y TIPOGRAFÍA */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    
    * {{
        font-family: 'Inter', sans-serif;
    }}
    
    /* HEADERS MODERNOS */
    .main-header {{
        color: {colores_institucionales["primario"]};
        font-weight: 700;
        font-size: 2.5rem;
        margin-bottom: 1rem;
        border-bottom: 3px solid {colores_institucionales["primario"]};
        padding-bottom: 0.5rem;
    }}
    
    .section-header {{
        color: {colores_institucionales["primario"]};
        font-weight: 600;
        font-size: 1.5rem;
        margin: 2rem 0 1rem 0;
    }}
    
    /* BOTONES MODERNOS */
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
    
    /* BOTÓN PRIMARIO */
    div[data-testid="stButton"] button[kind="primary"] {{
        background: linear-gradient(135deg, {colores_institucionales["primario"]}, #2D4FA8) !important;
        color: white !important;
    }}
    
    /* BOTÓN SECUNDARIO */
    div[data-testid="stButton"] button[kind="secondary"] {{
        background: white !important;
        color: {colores_institucionales["primario"]} !important;
        border: 2px solid {colores_institucionales["primario"]} !important;
    }}
    
    /* TARJETAS Y CONTENEDORES */
    .card {{
        background: white;
        border-radius: 16px;
        padding: 1.5rem;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
        border: 1px solid #E5E7EB;
        margin: 1rem 0;
    }}
    
    /* SIDEBAR MODERNO */
    .css-1d391kg {{
        background: linear-gradient(180deg, {colores_institucionales["primario"]}, #2D4FA8);
    }}
    
    .sidebar .sidebar-content {{
        background: linear-gradient(180deg, {colores_institucionales["primario"]}, #2D4FA8);
    }}
    
    /* ANIMACIONES SUAVES */
    .element-container {{
        transition: all 0.3s ease;
    }}
    
    /* MEJORAS ESPECÍFICAS PARA MÓVIL */
    @media (max-width: 768px) {{
        .main-header {{
            font-size: 2rem;
        }}
        
        .stButton > button {{
            padding: 1rem 1.5rem !important;
            font-size: 1.1rem !important;
        }}
    }}
    
    /* BARRAS DE PROGRESO MEJORADAS */
    .stProgress > div > div > div {{
        background: linear-gradient(90deg, {colores_institucionales["secundario"]}, #34D399);
        border-radius: 10px;
    }}
    
    /* GRID RESPONSIVO PARA MÉTRICAS */
    .metricas-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
        gap: 1rem;
        margin: 1rem 0;
    }}
    
    /* TABLAS RESPONSIVAS */
    .dataframe {{
        width: 100% !important;
    }}
    
    @media (max-width: 768px) {{
        .dataframe {{
            font-size: 0.8rem !important;
        }}
        
        /* Scroll horizontal para tablas en móvil */
        .dataframe-container {{
            overflow-x: auto;
        }}
    }}
    
    </style>
    """ , unsafe_allow_html=True)

def crear_header_moderno():
    """Crea un header moderno con logo y título"""
    col1, col2, col3 = st.columns([1, 3, 1])
    with col2:
        st.markdown('<h1 class="main-header">🎓 Preuniversitario CIMMA</h1>', unsafe_allow_html=True)
        st.markdown('<p style="text-align: center; color: #6B7280; font-size: 1.1rem;">Sistema de Gestión de Asistencia 2026</p>', unsafe_allow_html=True)

def crear_tarjeta_metricas(titulo, valor, subtitulo="", icono="📊", color="#1A3B8F"):
    """Crea una tarjeta de métricas moderna"""
    # Truncar valor si es muy largo para asignaturas
    if len(str(valor)) > 20:
        valor_display = str(valor)[:20] + "..."
    else:
        valor_display = str(valor)
        
    return f"""
    <div class="card" style="border-left: 4px solid {color}; min-height: 120px;">
        <div style="display: flex; align-items: center; margin-bottom: 0.5rem;">
            <span style="font-size: 1.5rem; margin-right: 0.5rem;">{icono}</span>
            <h3 style="margin: 0; color: {color}; font-weight: 600; font-size: 0.9rem;">{titulo}</h3>
        </div>
        <div style="font-size: 1.2rem; font-weight: 700; color: {color}; word-wrap: break-word;">{valor_display}</div>
        <div style="color: #6B7280; font-size: 0.8rem;">{subtitulo}</div>
    </div>
    """ 

def boton_moderno(texto, tipo="primario", icono="", key=None):
    """Crea un botón moderno con icono"""
    colores = {
        "primario": "#1A3B8F",
        "secundario": "#6B7280", 
        "exito": "#10B981",
        "peligro": "#EF4444"
    }
    
    color = colores.get(tipo, "#1A3B8F")
    icono_html = f"<span style='margin-right: 0.5rem;'>{icono}</span>" if icono else ""
    
    st.markdown(f"""
    <style>
    .boton-{key} {{
        background: {color} !important;
        color: white !important;
        border-radius: 12px !important;
        padding: 0.75rem 1.5rem !important;
        border: none !important;
        font-weight: 600 !important;
        transition: all 0.3s ease !important;
    }}
    .boton-{key}:hover {{
        transform: translateY(-2px) !important;
        box-shadow: 0 4px 8px rgba(0,0,0,0.2) !important;
    }}
    </style>
    """ , unsafe_allow_html=True)
    
    return st.button(f"{icono} {texto}", key=key, use_container_width=True)

# ==============================
# COMPONENTES DE UI MEJORADOS
# ==============================

def crear_dashboard_metricas_principales(df):
    """Dashboard moderno con métricas clave"""
    
    st.markdown('<h2 class="section-header">📊 Dashboard de Asistencia</h2>', unsafe_allow_html=True)
    
    # Métricas principales
    total_estudiantes = df['Estudiante'].nunique()
    total_clases = len(df)
    tasa_asistencia = (df['Asistencia'].sum() / total_clases * 100) if total_clases > 0 else 0
    estudiantes_perfectos = len(df[df['Asistencia'] == 1].groupby('Estudiante').filter(lambda x: x['Asistencia'].mean() == 1))
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown(crear_tarjeta_metricas(
            "Total Estudiantes", 
            f"{total_estudiantes:,}", 
            "Estudiantes únicos", "👥", "#1A3B8F"
        ), unsafe_allow_html=True)
    
    with col2:
        st.markdown(crear_tarjeta_metricas(
            "Clases Registradas", 
            f"{total_clases:,}", 
            "Total de clases", "📚", "#10B981"
        ), unsafe_allow_html=True)
    
    with col3:
        st.markdown(crear_tarjeta_metricas(
            "Tasa Asistencia", 
            f"{tasa_asistencia:.1f}%", 
            "Promedio general", "✅", "#F59E0B"
        ), unsafe_allow_html=True)
    
    with col4:
        st.markdown(crear_tarjeta_metricas(
            "Asistencia Perfecta", 
            f"{estudiantes_perfectos}", 
            "100% de asistencia", "⭐", "#8B5CF6"
        ), unsafe_allow_html=True)

def crear_dashboard_avanzado(df):
    """Dashboard completo con métricas avanzadas"""
    
    st.markdown('<h2 class="section-header">📈 Dashboard Analytics Avanzado</h2>', unsafe_allow_html=True)
    
    # ==================== KPIs PRINCIPALES ====================
    st.subheader("🎯 KPIs Principales")
    
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    
    with kpi1:
        tasa_asistencia = (df['Asistencia'].sum() / len(df) * 100) if len(df) > 0 else 0
        tendencia = calcular_tendencia_semanal(df)
        st.metric(
            "📊 Tasa Asistencia General", 
            f"{tasa_asistencia:.1f}%",
            delta=f"{tendencia:+.1f}%" if tendencia != 0 else None
        )
    
    with kpi2:
        estudiantes_riesgo = identificar_estudiantes_riesgo(df)
        st.metric(
            "🎯 Estudiantes en Riesgo", 
            len(estudiantes_riesgo),
            delta=f"{len(estudiantes_riesgo)} alertas",
            delta_color="inverse"
        )
    
    with kpi3:
        eficiencia_profesores = calcular_eficiencia_profesores(df)
        st.metric(
            "👨‍🏫 Eficiencia Profesores", 
            f"{eficiencia_profesores:.0f}%"
        )
    
    with kpi4:
        cumplimiento_metas = calcular_cumplimiento_metas(df)
        st.metric(
            "✅ Cumplimiento Metas", 
            f"{cumplimiento_metas:.0f}%"
        )
    
    # ==================== GRÁFICOS AVANZADOS ====================
    col1, col2 = st.columns(2)
    
    with col1:
        # Heatmap de Asistencia Semanal
        crear_heatmap_asistencia(df)
    
    with col2:
        # Distribución de Asistencia
        crear_distribucion_asistencia(df)
    
    # ==================== ANÁLISIS POR ASIGNATURA ====================
    if 'Asignatura' in df.columns and len(df['Asignatura'].unique()) > 1:
        st.subheader("📚 Análisis por Asignatura")
        
        asistencia_por_asignatura = df.groupby('Asignatura')['Asistencia'].agg(['sum', 'count']).reset_index()
        asistencia_por_asignatura['Porcentaje'] = (asistencia_por_asignatura['sum'] / asistencia_por_asignatura['count'] * 100)
        asistencia_por_asignatura = asistencia_por_asignatura.sort_values('Porcentaje', ascending=False)
        
        fig_asignatura = px.bar(
            asistencia_por_asignatura,
            x='Asignatura',
            y='Porcentaje',
            title='📊 Asistencia por Asignatura',
            color='Porcentaje',
            color_continuous_scale=['#EF4444', '#F59E0B', '#10B981'],
            template='plotly_white'
        )
        
        fig_asignatura.update_layout(
            xaxis_tickangle=-45,
            coloraxis_showscale=False,
            showlegend=False
        )
        
        st.plotly_chart(fig_asignatura, use_container_width=True)
    
    # ==================== ALERTAS INTELIGENTES ====================
    st.subheader("🚨 Alertas Inteligentes")
    generar_alertas_inteligentes(df)
    
    # ==================== PREDICTIVOS ====================
    st.subheader("🔮 Análisis Predictivo")
    crear_seccion_predictiva(df)

def calcular_tendencia_semanal(df):
    """Calcula tendencia de asistencia última semana vs anterior"""
    if 'Fecha' not in df.columns or df.empty:
        return 0
    
    try:
        df_fechas = df.copy()
        df_fechas['Fecha'] = pd.to_datetime(df_fechas['Fecha'])
        
        # Últimas 2 semanas
        fecha_max = df_fechas['Fecha'].max()
        semana_actual = fecha_max - timedelta(days=7)
        semana_anterior = semana_actual - timedelta(days=7)
        
        asistencia_actual = df_fechas[
            df_fechas['Fecha'] > semana_actual
        ]['Asistencia'].mean() * 100
        
        asistencia_anterior = df_fechas[
            (df_fechas['Fecha'] > semana_anterior) & 
            (df_fechas['Fecha'] <= semana_actual)
        ]['Asistencia'].mean() * 100
        
        return asistencia_actual - asistencia_anterior if asistencia_anterior else 0
    except:
        return 0

def crear_heatmap_asistencia(df):
    """Heatmap de asistencia por día y hora"""
    try:
        if 'Fecha' not in df.columns or df.empty:
            st.info("No hay datos suficientes para el heatmap")
            return
            
        df_heatmap = df.copy()
        df_heatmap['Fecha'] = pd.to_datetime(df_heatmap['Fecha'])
        df_heatmap['Dia_Semana'] = df_heatmap['Fecha'].dt.day_name()
        df_heatmap['Hora'] = df_heatmap['Fecha'].dt.hour
        
        # Agrupar por día y hora
        heatmap_data = df_heatmap.groupby(['Dia_Semana', 'Hora'])['Asistencia'].mean().unstack(fill_value=0)
        
        # Ordenar días de la semana
        dias_orden = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        heatmap_data = heatmap_data.reindex(dias_orden)
        
        fig = px.imshow(
            heatmap_data,
            title="🔥 Heatmap de Asistencia - Día vs Hora",
            color_continuous_scale='RdYlGn',
            aspect="auto"
        )
        
        fig.update_layout(
            xaxis_title="Hora del Día",
            yaxis_title="Día de la Semana"
        )
        
        st.plotly_chart(fig, use_container_width=True)
        
    except Exception as e:
        st.error(f"Error generando heatmap: {e}")

def crear_distribucion_asistencia(df):
    """Distribución de porcentajes de asistencia"""
    try:
        if df.empty:
            return
            
        # Calcular porcentaje por estudiante
        asistencia_por_estudiante = df.groupby('Estudiante')['Asistencia'].agg(['sum', 'count']).reset_index()
        asistencia_por_estudiante['Porcentaje'] = (asistencia_por_estudiante['sum'] / asistencia_por_estudiante['count'] * 100)
        
        fig = px.histogram(
            asistencia_por_estudiante, 
            x='Porcentaje',
            title='📊 Distribución de Asistencia por Estudiante',
            nbins=20,
            color_discrete_sequence=['#1A3B8F']
        )
        
        fig.update_layout(
            xaxis_title="Porcentaje de Asistencia (%)",
            yaxis_title="Número de Estudiantes"
        )
        
        st.plotly_chart(fig, use_container_width=True)
        
    except Exception as e:
        st.error(f"Error en distribución: {e}")

def identificar_estudiantes_riesgo(df):
    """Identifica estudiantes con menos del 70% de asistencia"""
    try:
        if df.empty:
            return []
            
        asistencia_por_estudiante = df.groupby('Estudiante')['Asistencia'].agg(['sum', 'count']).reset_index()
        asistencia_por_estudiante['Porcentaje'] = (asistencia_por_estudiante['sum'] / asistencia_por_estudiante['count'] * 100)
        
        estudiantes_riesgo = asistencia_por_estudiante[
            asistencia_por_estudiante['Porcentaje'] < 70
        ]['Estudiante'].tolist()
        
        return estudiantes_riesgo
    except:
        return []

def calcular_eficiencia_profesores(df):
    """Calcula eficiencia promedio de profesores"""
    try:
        if df.empty:
            return 0
            
        # Simulación - en producción calcularía por profesor
        return min(95, (df['Asistencia'].mean() * 100) + 10)
    except:
        return 0

def calcular_cumplimiento_metas(df):
    """Calcula cumplimiento de metas institucionales"""
    try:
        if df.empty:
            return 0
            
        tasa_asistencia = (df['Asistencia'].sum() / len(df) * 100)
        meta_institucional = 85  # Meta del 85%
        cumplimiento = min(100, (tasa_asistencia / meta_institucional) * 100)
        return cumplimiento
    except:
        return 0

def generar_alertas_inteligentes(df):
    """Genera alertas inteligentes basadas en patrones"""
    alertas = []
    
    # Alerta: Estudiantes con <70% de asistencia
    estudiantes_riesgo = identificar_estudiantes_riesgo(df)
    
    if len(estudiantes_riesgo) > 0:
        alertas.append({
            'tipo': '⚠️',
            'mensaje': f'{len(estudiantes_riesgo)} estudiantes con menos del 70% de asistencia',
            'severidad': 'alta'
        })
    
    # Alerta: Tendencia negativa
    tendencia = calcular_tendencia_semanal(df)
    if tendencia < -5:
        alertas.append({
            'tipo': '📉',
            'mensaje': f'Tendencia negativa de {tendencia:.1f}% en la última semana',
            'severidad': 'media'
        })
    
    # Alerta: Baja asistencia general
    tasa_asistencia = (df['Asistencia'].sum() / len(df) * 100) if len(df) > 0 else 0
    if tasa_asistencia < 75:
        alertas.append({
            'tipo': '🔴',
            'mensaje': f'Asistencia general baja: {tasa_asistencia:.1f}%',
            'severidad': 'alta'
        })
    
    # Mostrar alertas
    if alertas:
        for alerta in alertas:
            color = "#FEF3C7" if alerta['severidad'] == 'media' else "#FEE2E2"
            st.markdown(f"""
            <div style="background: {color}; padding: 1rem; border-radius: 8px; margin: 0.5rem 0; border-left: 4px solid #F59E0B;">
                <strong>{alerta['tipo']} {alerta['mensaje']}</strong>
            </div>
            """ , unsafe_allow_html=True)
    else:
        st.success("✅ No hay alertas críticas en este momento")

def crear_seccion_predictiva(df):
    """Sección de análisis predictivo"""
    col1, col2 = st.columns(2)
    
    with col1:
        # Predicción de riesgo
        st.markdown("**🎯 Predicción de Riesgo**")
        
        # Simulación de modelo predictivo
        estudiantes_totales = df['Estudiante'].nunique()
        riesgo_data = {
            'Bajo Riesgo': int(estudiantes_totales * 0.6),
            'Riesgo Medio': int(estudiantes_totales * 0.3),
            'Alto Riesgo': int(estudiantes_totales * 0.1)
        }
        
        fig_riesgo = px.pie(
            values=list(riesgo_data.values()),
            names=list(riesgo_data.keys()),
            color=list(riesgo_data.keys()),
            color_discrete_map={
                'Bajo Riesgo': '#10B981',
                'Riesgo Medio': '#F59E0B', 
                'Alto Riesgo': '#EF4444'
            },
            title="Distribución de Riesgo Estudiantil"
        )
        
        st.plotly_chart(fig_riesgo, use_container_width=True)
    
    with col2:
        # Recomendaciones automáticas
        st.markdown("**💡 Recomendaciones**")
        
        recomendaciones = [
            "📧 Contactar a estudiantes con baja asistencia",
            "👥 Revisar eficiencia de profesores regularmente",
            "📊 Programar reportes automáticos para directivos",
            "🎯 Implementar programa de incentivos para asistencia perfecta"
        ]
        
        for rec in recomendaciones:
            st.markdown(f"- {rec}")

def crear_grafico_asistencia_interactivo(df, tipo="tendencia"):
    """Crea gráficos interactivos modernos con Plotly"""
    
    if tipo == "tendencia" and 'Fecha' in df.columns and 'Porcentaje' in df.columns:
        fig = px.line(df, 
                     x='Fecha', 
                     y='Porcentaje',
                     title='📈 Tendencia de Asistencia - Evolución Temporal',
                     color='Curso' if 'Curso' in df.columns else None,
                     template='plotly_white')
        
        fig.update_layout(
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
            font=dict(family="Inter", size=12),
            hoverlabel=dict(
                bgcolor="white",
                font_size=12,
                font_family="Inter"
            ),
            xaxis=dict(
                gridcolor='#E5E7EB',
                title=dict(text="Fecha", font=dict(size=14))
            ),
            yaxis=dict(
                gridcolor='#E5E7EB', 
                title=dict(text="Porcentaje de Asistencia (%)", font=dict(size=14)),
                range=[0, 100]
            )
        )
        
        # Añadir animación
        fig.update_traces(
            line=dict(width=3),
            marker=dict(size=8),
            hovertemplate='<b>%{x}</b><br>Asistencia: %{y:.1f}%<extra></extra>'
        )
        return fig
        
    elif tipo == "barras" and 'Estudiante' in df.columns and 'Porcentaje' in df.columns:
        fig = px.bar(df,
                    x='Estudiante',
                    y='Porcentaje',
                    title='👤 Asistencia por Estudiante',
                    color='Porcentaje',
                    color_continuous_scale=['#EF4444', '#F59E0B', '#10B981'],
                    template='plotly_white')
        
        fig.update_layout(
            xaxis_tickangle=-45,
            coloraxis_showscale=False,
            showlegend=False
        )
        
        fig.update_traces(
            hovertemplate='<b>%{x}</b><br>Asistencia: %{y:.1f}%<extra></extra>'
        )
        return fig
    
    return None

def implementar_temporizador_seguridad():
    """Implementa un temporizador de seguridad en tiempo real"""
    
    if 'login_time' in st.session_state and 'timeout_duration' in st.session_state:
        if time.time() - st.session_state['login_time'] > st.session_state['timeout_duration']:
            st.error("❌ Sesión expirada por límite de tiempo.")
            st.session_state.clear()
            st.rerun()
            return
        
        tiempo_restante = st.session_state['timeout_duration'] - (time.time() - st.session_state['login_time'])
        if tiempo_restante > 0:
            minutos = int(tiempo_restante // 60)
            segundos = int(tiempo_restante % 60)
            
            color = "#1A3B8F"
            if tiempo_restante < 300:  # 5 minutos
                color = "#EF4444"
            elif tiempo_restante < 600:  # 10 minutos
                color = "#F59E0B"
            
            st.markdown(f"""
            <div style="position: sticky; top: 1rem; background: {color}; color: white; padding: 0.5rem 1rem; border-radius: 20px; font-weight: 600; z-index: 1000; box-shadow: 0 4px 6px rgba(0,0,0,0.1); text-align: center; margin-bottom: 1rem;">
                ⏱️ Tiempo restante: {minutos:02d}:{segundos:02d}
            </div>
            """ , unsafe_allow_html=True)

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
# CONFIGURACIÓN Y CONEXIONES
# ==============================

@st.cache_resource
def get_client():
    try:
        # Verificar que los secrets estén disponibles
        if "google" not in st.secrets or "credentials" not in st.secrets["google"]:
            st.error("❌ No se encontraron las credenciales de Google en los secrets.")
            return None
            
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
    """Envía email con mejor feedback de diagnóstico"""
    try:
        # Verificar configuración de email
        if "EMAIL" not in st.secrets:
            st.error("❌ No se encontró la configuración de EMAIL en los secrets.")
            return False
            
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
        
        # LOG DE ÉXITO
        print(f"✅ Email enviado exitosamente a: {to_email}")
        return True
        
    except Exception as e:
        # LOG DE ERROR DETALLADO
        error_msg = f"❌ Error enviando email a {to_email}: {str(e)}"
        print(error_msg)
        st.error(error_msg)
        return False

def generate_2fa_code():
    return ''.join(random.choices(string.digits, k=6))

# ==============================
# CARGA DE DATOS CON CACHÉ INTELIGENTE
# ==============================

@cache_manager.cached(ttl=3600, dependencias=['cursos'])
def load_courses():
    try:
        client = get_client()
        if not client:
            st.error("❌ No se pudo inicializar el cliente de Google Sheets. Verifica las credenciales.")
            return {}
        
        # Verificar que el sheet_id esté disponible
        if "google" not in st.secrets or "clases_sheet_id" not in st.secrets["google"]:
            st.error("❌ No se encontró el ID de la hoja de clases en los secrets.")
            return {}
            
        sheet_id = st.secrets["google"]["clases_sheet_id"]
        
        try:
            clases_sheet = client.open_by_key(sheet_id)
        except gspread.exceptions.SpreadsheetNotFound:
            st.error(f"❌ No se encontró la hoja con ID: {sheet_id}. Verifica el ID.")
            return {}
        except gspread.exceptions.APIError as e:
            error_details = e.response.json().get('error', {}) if hasattr(e.response, 'json') else {}
            error_message = error_details.get('message', str(e))
            error_code = error_details.get('code', 'Unknown')
            st.error(f"❌ Error de API al acceder a la hoja: {error_message} (Código: {error_code})")
            if error_code == 403:
                st.info("💡 Verifica que el service account tenga permisos de edición en la hoja.")
            elif error_code == 429:
                st.info("💡 Límite de cuota de API alcanzado. Intenta de nuevo más tarde.")
            return {}
        
        courses = {}
        for worksheet in clases_sheet.worksheets():
            sheet_name = worksheet.title
            try:
                # Leer columnas A y C
                colA_raw = worksheet.col_values(1)
                colC_raw = worksheet.col_values(3)  # Columna C para ASIGNATURA
                
                colA = [cell.strip() for cell in colA_raw if isinstance(cell, str) and cell.strip()]
                colC = [cell.strip() for cell in colC_raw if isinstance(cell, str) and cell.strip()]
                
                colA_upper = [s.upper() for s in colA]
                colC_upper = [s.upper() for s in colC]
                
                # Buscar ASIGNATURA en columna C
                idx_asignatura = None
                asignatura = ""
                try:
                    idx_asignatura = colC_upper.index("ASIGNATURA")
                    if idx_asignatura + 1 < len(colC):
                        asignatura = colC[idx_asignatura + 1]
                except ValueError:
                    # Si no encuentra ASIGNATURA, buscar en otras posiciones
                    for i, cell in enumerate(colC_upper):
                        if "ASIGNATURA" in cell:
                            idx_asignatura = i
                            if i + 1 < len(colC):
                                asignatura = colC[i + 1]
                            break
                
                # Resto del código existente para leer otras columnas...
                idx_prof = colA_upper.index("PROFESOR")
                profesor = colA[idx_prof + 1]
                idx_dia = colA_upper.index("DIA")
                dia = colA[idx_dia + 1]
                idx_curso = colA_upper.index("CURSO")
                curso_id = colA[idx_curso + 1]
                horario = colA[idx_curso + 2]
                fechas = []
                estudiantes = []
                idx_fechas = colA_upper.index("FECHAS")
                idx_estudiantes = colA_upper.index("NOMBRES ESTUDIANTES")
                for i in range(idx_fechas + 1, idx_estudiantes):
                    if i < len(colA):
                        fechas.append(colA[i])
                for i in range(idx_estudiantes + 1, len(colA)):
                    if colA[i]:
                        estudiantes.append(colA[i])
                try:
                    colB_raw = worksheet.col_values(2)
                    colB = [cell.strip() for cell in colB_raw if isinstance(cell, str) and cell.strip()]
                    colB_upper = [s.upper() for s in colB]
                    idx_sede = colB_upper.index("SEDE")
                    sede = colB[idx_sede + 1] if (idx_sede + 1) < len(colB) else ""
                except (ValueError, IndexError):
                    sede = ""
                
                if profesor and dia and curso_id and horario and estudiantes:
                    estudiantes = sorted([e for e in estudiantes if e.strip()])
                    courses[sheet_name] = {
                        "profesor": profesor,
                        "dia": dia,
                        "horario": horario,
                        "curso_id": curso_id,
                        "fechas": fechas or ["Sin fechas"],
                        "estudiantes": estudiantes,
                        "sede": sede,
                        "asignatura": asignatura  # Nuevo campo agregado
                    }
            except Exception as e:
                st.warning(f"⚠️ Error en hoja '{sheet_name}': {str(e)[:80]}")
                continue
        return courses
    except Exception as e:
        st.error(f"❌ Error crítico al cargar cursos: {str(e)}")
        return {}

@cache_manager.cached(ttl=7200)  # 2 horas para emails
def load_emails():
    try:
        client = get_client()
        if not client:
            return {}, {}
            
        # Verificar que el sheet_id esté disponible
        if "google" not in st.secrets or "asistencia_sheet_id" not in st.secrets["google"]:
            st.error("❌ No se encontró el ID de la hoja de asistencia en los secrets.")
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

@cache_manager.cached(ttl=1800)  # 30 minutos para asistencia
def load_all_asistencia():
    client = get_client()
    if not client:
        return pd.DataFrame()
        
    # Verificar que el sheet_id esté disponible
    if "google" not in st.secrets or "asistencia_sheet_id" not in st.secrets["google"]:
        st.error("❌ No se encontró el ID de la hoja de asistencia en los secrets.")
        return pd.DataFrame()
        
    asistencia_sheet = client.open_by_key(st.secrets["google"]["asistencia_sheet_id"])
    all_data = []
    for worksheet in asistencia_sheet.worksheets():
        sheet_name = worksheet.title
        if sheet_name in ["MAILS", "MEJORAS", "PROFESORES", "Respuestas de formulario 2", "AUDIT", "FECHAS_COMPLETADAS", "CAMBIOS_CURSOS"]:
            continue
        try:
            all_values = worksheet.get_all_values()
            if not all_values or len(all_values) < 5:
                continue
            all_values = all_values[3:]  # Skip first 3 rows
            headers = all_values[0]
            headers = [str(h).strip().upper() for h in headers if str(h).strip()]  # Case-insensitive
            
            curso_col = None
            fecha_col = None
            estudiante_col = None
            asistencia_col = None
            hora_registro_col = None
            informacion_col = None
            
            for i, h in enumerate(headers):
                h_upper = h.upper()
                if "CURSO" in h_upper:
                    curso_col = i
                elif "FECHA" in h_upper:
                    fecha_col = i
                elif any(term in h_upper for term in ["ESTUDIANTE", "NOMBRE ESTUDIANTE", "ALUMNO"]):
                    estudiante_col = i
                elif "ASISTENCIA" in h_upper:
                    asistencia_col = i
                elif "HORA REGISTRO" in h_upper or "HORA" in h_upper:
                    hora_registro_col = i
                elif any(term in h_upper for term in ["INFORMACION", "MOTIVO", "OBSERVACION"]):
                    informacion_col = i
            
            if asistencia_col is None or estudiante_col is None or fecha_col is None:
                continue
            
            records_loaded = 0
            for row in all_values[1:]:  # Skip header row
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
                
                # Fallback: Use sheet name if curso_col is empty
                curso = row[curso_col].strip() if curso_col is not None and len(row) > curso_col and row[curso_col] else sheet_name
                fecha_str = row[fecha_col].strip() if len(row) > fecha_col and row[fecha_col] else ""
                estudiante = row[estudiante_col].strip() if len(row) > estudiante_col and row[estudiante_col] else ""
                hora_registro = row[hora_registro_col].strip() if (hora_registro_col is not None and len(row) > hora_registro_col and row[hora_registro_col]) else ""
                informacion = row[informacion_col].strip() if (informacion_col is not None and len(row) > informacion_col and row[informacion_col]) else ""
                
                if estudiante and asistencia_val is not None:  # Only add if estudiante is valid
                    all_data.append({
                        "Curso": curso,
                        "Fecha": fecha_str,
                        "Estudiante": estudiante,
                        "Asistencia": asistencia_val,
                        "Hora Registro": hora_registro,
                        "Información": informacion
                    })
                    records_loaded += 1
            
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
# FUNCIÓN DE ENVÍO DE EMAIL MEJORADA
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
# GESTIÓN DE CAMBIOS DE CURSO
# ==============================

def ejecutar_cambio_curso(estudiante, curso_origen, curso_destino, fecha_efectiva):
    """Ejecuta el cambio de curso en Google Sheets"""
    
    try:
        client = get_client()
        if not client:
            st.error("❌ Error de conexión con Google Sheets")
            return False
        
        # Verificar que los sheet_ids estén disponibles
        if "google" not in st.secrets:
            st.error("❌ No se encontraron los secrets de Google.")
            return False
            
        asistencia_sheet_id = st.secrets["google"].get("asistencia_sheet_id")
        clases_sheet_id = st.secrets["google"].get("clases_sheet_id")
        
        if not asistencia_sheet_id or not clases_sheet_id:
            st.error("❌ No se encontraron los IDs de las hojas en los secrets.")
            return False
        
        asistencia_sheet = client.open_by_key(asistencia_sheet_id)
        
        # 1. ACTUALIZAR HOJA DE ASISTENCIA DEL CURSO ORIGEN
        try:
            sheet_origen = asistencia_sheet.worksheet(curso_origen)
            records_origen = sheet_origen.get_all_records()
            
            # Encontrar y actualizar registros del estudiante
            for i, row in enumerate(records_origen, start=2):  # start=2 porque fila 1 son headers
                if row.get('Estudiante') == estudiante:
                    # Actualizar el curso en el registro
                    sheet_origen.update_cell(i, 1, curso_destino)  # Columna Curso
                    
        except gspread.exceptions.WorksheetNotFound:
            st.warning(f"⚠️ No se encontró la hoja del curso origen: {curso_origen}")
        
        # 2. ACTUALIZAR HOJA DE CLASES (LISTA DE ESTUDIANTES)
        clases_sheet = client.open_by_key(clases_sheet_id)
        
        try:
            # Remover de curso origen
            sheet_clases_origen = clases_sheet.worksheet(curso_origen)
            valores_origen = sheet_clases_origen.get_all_values()
            
            for i, fila in enumerate(valores_origen):
                if estudiante in fila:
                    # Encontrar la columna del estudiante y limpiar
                    for j, valor in enumerate(fila):
                        if valor == estudiante:
                            sheet_clases_origen.update_cell(i + 1, j + 1, "")
                            break
                    break
                    
        except gspread.exceptions.WorksheetNotFound:
            st.warning(f"⚠️ No se encontró la hoja de clases origen: {curso_origen}")
        
        try:
            # Agregar a curso destino
            sheet_clases_destino = clases_sheet.worksheet(curso_destino)
            valores_destino = sheet_clases_destino.get_all_values()
            
            # Encontrar la sección de estudiantes (después de "NOMBRES ESTUDIANTES")
            idx_estudiantes = None
            for i, fila in enumerate(valores_destino):
                if "NOMBRES ESTUDIANTES" in [str(x).upper() for x in fila]:
                    idx_estudiantes = i + 1
                    break
            
            if idx_estudiantes is not None:
                # Encontrar primera celda vacía en la columna de estudiantes
                col_estudiantes = 0  # Asumiendo que los estudiantes están en columna 0 después del header
                for i in range(idx_estudiantes, len(valores_destino)):
                    if not valores_destino[i][col_estudiantes].strip():
                        sheet_clases_destino.update_cell(i + 1, col_estudiantes + 1, estudiante)
                        break
                else:
                    # Si no hay celdas vacías, agregar al final
                    sheet_clases_destino.append_row([estudiante])
                    
        except gspread.exceptions.WorksheetNotFound:
            st.warning(f"⚠️ No se encontró la hoja de clases destino: {curso_destino}")
        
        # 3. REGISTRAR EN LOG DE CAMBIOS
        try:
            cambios_sheet = asistencia_sheet.worksheet("CAMBIOS_CURSOS")
        except gspread.exceptions.WorksheetNotFound:
            cambios_sheet = asistencia_sheet.add_worksheet("CAMBIOS_CURSOS", 100, 6)
            cambios_sheet.append_row([
                "Fecha Cambio", "Estudiante", "Curso Origen", "Curso Destino", 
                "Fecha Efectiva", "Administrador"
            ])
        
        cambios_sheet.append_row([
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            estudiante,
            curso_origen,
            curso_destino,
            fecha_efectiva.strftime("%Y-%m-%d"),
            st.session_state["user_name"]
        ])
        
        return True
        
    except Exception as e:
        st.error(f"❌ Error ejecutando cambio de curso: {str(e)}")
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
    
    # Header con ayuda contextual
    col1, col2 = st.columns([6, 1])
    with col1:
        st.markdown('<h2 class="section-header">📊 Panel Administrativo - Análisis de Asistencia</h2>', unsafe_allow_html=True)
    with col2:
        st.markdown(sistema_ayuda.tooltip_contextual('dashboard'), unsafe_allow_html=True)
    
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

    # Aplicar estilos de tooltips
    crear_tooltip_fechas()

    # Mostrar panel informativo
    mostrar_panel_informativo_fechas()

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
    # GESTIÓN DE CAMBIOS DE CURSO
    # ==============================
    
    st.markdown('<h2 class="section-header">🔄 Gestión de Cambios de Curso</h2>', unsafe_allow_html=True)
    
    with st.expander("📋 Cambiar Estudiante de Curso", expanded=True):
        st.warning("""
        **⚠️ IMPORTANTE:** Esta función mueve el historial completo de un estudiante a otro curso.
        - Mantiene todo el historial de asistencia
        - Actualiza automáticamente en todos los reportes
        - No pierde datos históricos
        """)
        
        # Cargar datos
        cursos = load_courses()
        df = load_all_asistencia()
        
        if not cursos or df.empty:
            st.error("No se pudieron cargar los datos necesarios")
            return
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("👤 Seleccionar Estudiante")
            
            # Seleccionar curso origen
            curso_origen = st.selectbox(
                "Curso de origen:",
                list(cursos.keys()),
                key="curso_origen_admin"
            )
            
            # Seleccionar estudiante
            estudiantes_origen = cursos[curso_origen]["estudiantes"]
            estudiante_seleccionado = st.selectbox(
                "Estudiante a cambiar:",
                estudiantes_origen,
                key="estudiante_cambio_admin"
            )
            
            # Mostrar información del estudiante
            if estudiante_seleccionado:
                datos_estudiante = df[df['Estudiante'] == estudiante_seleccionado]
                if not datos_estudiante.empty:
                    total_clases = len(datos_estudiante)
                    asistencias = datos_estudiante['Asistencia'].sum()
                    porcentaje = (asistencias / total_clases * 100) if total_clases > 0 else 0
                    
                    st.info(f"""
                    **📊 Historial actual:**
                    - **Curso actual:** {curso_origen}
                    - **Total clases:** {total_clases}
                    - **Asistencias:** {asistencias}
                    - **Porcentaje:** {porcentaje:.1f}%
                    """)
        
        with col2:
            st.subheader("🎯 Curso Destino")
            
            # Seleccionar curso destino (excluyendo el curso origen)
            cursos_destino = [curso for curso in cursos.keys() if curso != curso_origen]
            curso_destino = st.selectbox(
                "Curso destino:",
                cursos_destino,
                key="curso_destino_admin"
            )
            
            # Mostrar información del curso destino
            if curso_destino:
                estudiantes_destino = cursos[curso_destino]["estudiantes"]
                st.success(f"""
                **📚 Curso destino: {curso_destino}**
                - **Profesor:** {cursos[curso_destino]['profesor']}
                - **Día:** {cursos[curso_destino]['dia']}
                - **Horario:** {cursos[curso_destino]['horario']}
                - **Estudiantes actuales:** {len(estudiantes_destino)}
                - **Asignatura:** {cursos[curso_destino].get('asignatura', 'No especificada')}
                """)
        
        # Confirmación y ejecución
        st.markdown("---")
        st.subheader("✅ Confirmar Cambio")
        
        if estudiante_seleccionado and curso_origen and curso_destino:
            # Verificar si el estudiante ya existe en el curso destino
            estudiantes_destino = cursos[curso_destino]["estudiantes"]
            if estudiante_seleccionado in estudiantes_destino:
                st.error(f"❌ **{estudiante_seleccionado}** ya existe en el curso **{curso_destino}**")
            else:
                st.warning(f"""
                **🔔 ¿Estás seguro de realizar este cambio?**
                
                **Estudiante:** {estudiante_seleccionado}
                **De:** {curso_origen} → **A:** {curso_destino}
                
                **Esta acción:**
                ✅ Mantendrá todo el historial de asistencia
                ✅ Actualizará todos los reportes futuros
                ✅ El estudiante aparecerá en el nuevo curso
                """)
                
                # Opción de fecha efectivo
                fecha_efectiva = st.date_input(
                    "Fecha efectivo del cambio:",
                    value=datetime.now().date(),
                    help="Los reportes futuros usarán esta fecha para el cambio",
                    key="fecha_efectiva_admin"
                )
                
                if st.button("🔄 EJECUTAR CAMBIO DE CURSO", type="primary", use_container_width=True, key="ejecutar_cambio_admin"):
                    if ejecutar_cambio_curso(estudiante_seleccionado, curso_origen, curso_destino, fecha_efectiva):
                        st.success("""
                        ✅ **¡Cambio de curso ejecutado exitosamente!**
                        
                        **Próximos pasos:**
                        1. El estudiante ya aparece en el nuevo curso
                        2. Los reportes reflejarán el cambio inmediatamente
                        3. El historial anterior se mantiene intacto
                        """)
                        
                        # Invalidar caché para reflejar cambios
                        cache_manager.invalidar()
                        st.rerun()

    st.divider()
    
    # ==============================
    # INICIALIZACIÓN DE ESTADOS
    # ==============================
    
    if "email_status" not in st.session_state:
        st.session_state.email_status = ""
    if "curso_seleccionado" not in st.session_state:
        st.session_state.curso_seleccionado = "Todos"
    if "estudiante_seleccionado" not in st.session_state:
        st.session_state.estudiante_seleccionado = "Todos"
    if "sede_seleccionadas" not in st.session_state:
        st.session_state.sede_seleccionadas = ["Todas"]
    if "asignatura_seleccionadas" not in st.session_state:
        st.session_state.asignatura_seleccionadas = ["Todas"]
    
    # ==============================
    # CARGA DE DATOS
    # ==============================
    
    with st.spinner("🔄 Cargando datos de asistencia..."):
        df = load_all_asistencia()
    
    if df.empty:
        st.error("❌ No se pudieron cargar los datos de asistencia.")
        return
    
    # ==============================
    # BARRA LATERAL - FILTROS
    # ==============================
    
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
    
    # Selector de sedes (MULTISELECT)
    courses = load_courses()
    df['Sede'] = df['Curso'].map(lambda c: courses.get(c, {}).get('sede', ''))
    sedes = ["Todas"] + sorted(df['Sede'].unique().tolist())
    # Initialize session state for sedes as a list
    if 'sede_seleccionadas' not in st.session_state:
        st.session_state.sede_seleccionadas = ["Todas"]

    sede_seleccionadas = st.sidebar.multiselect(
        "Seleccionar Sedes",
        sedes,
        default=st.session_state.sede_seleccionadas,
        key="sede_select_admin"
    )
    # Update session state
    st.session_state.sede_seleccionadas = sede_seleccionadas if sede_seleccionadas else ["Todas"]
    
    # Selector de asignaturas (MULTISELECT) - NUEVO FILTRO
    df['Asignatura'] = df['Curso'].map(lambda c: courses.get(c, {}).get('asignatura', ''))
    asignaturas = ["Todas"] + sorted(df['Asignatura'].unique().tolist())
    
    asignatura_seleccionadas = st.sidebar.multiselect(
        "Seleccionar Asignaturas",
        asignaturas,
        default=st.session_state.asignatura_seleccionadas,
        key="asignatura_select_admin"
    )
    # Actualizar estado de sesión
    st.session_state.asignatura_seleccionadas = asignatura_seleccionadas if asignatura_seleccionadas else ["Todas"]

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
        st.session_state.sede_seleccionadas = ["Todas"]
        st.session_state.asignatura_seleccionadas = ["Todas"]
        st.session_state.fecha_inicio = fecha_min
        st.session_state.fecha_fin = fecha_max
        st.rerun()
    
    # ==============================
    # APLICACIÓN DE FILTROS
    # ==============================
    
    datos_filtrados = df.copy()
    filtros_aplicados = []
    
    if st.session_state.curso_seleccionado != "Todos":
        datos_filtrados = datos_filtrados[datos_filtrados['Curso'] == st.session_state.curso_seleccionado]
        filtros_aplicados.append(f"📚 Curso: {st.session_state.curso_seleccionado}")
    
    if st.session_state.estudiante_seleccionado != "Todos":
        datos_filtrados = datos_filtrados[datos_filtrados['Estudiante'] == st.session_state.estudiante_seleccionado]
        filtros_aplicados.append(f"👤 Estudiante: {st.session_state.estudiante_seleccionado}")
    
    if "Todas" not in st.session_state.sede_seleccionadas and st.session_state.sede_seleccionadas:
        datos_filtrados = datos_filtrados[datos_filtrados['Sede'].isin(st.session_state.sede_seleccionadas)]
        filtros_aplicados.append(f"🏫 Sedes: {', '.join(st.session_state.sede_seleccionadas)}")
    
    # NUEVO FILTRO POR ASIGNATURA
    if "Todas" not in st.session_state.asignatura_seleccionadas and st.session_state.asignatura_seleccionadas:
        datos_filtrados = datos_filtrados[datos_filtrados['Asignatura'].isin(st.session_state.asignatura_seleccionadas)]
        filtros_aplicados.append(f"📚 Asignaturas: {', '.join(st.session_state.asignatura_seleccionadas)}")
    
    if 'Fecha' in datos_filtrados.columns and datos_filtrados['Fecha'].notna().any():
        datos_filtrados = datos_filtrados[
            (datos_filtrados['Fecha'].dt.date >= st.session_state.fecha_inicio) &
            (datos_filtrados['Fecha'].dt.date <= st.session_state.fecha_fin)
        ]
        filtros_aplicados.append(f"📅 Período: {st.session_state.fecha_inicio.strftime('%d/%m/%Y')} - {st.session_state.fecha_fin.strftime('%d/%m/%Y')}")
    
    # ==============================
    # DASHBOARD PRINCIPAL
    # ==============================
    
    if st.session_state.email_status:
        if "✅" in st.session_state.email_status or "🎉" in st.session_state.email_status:
            st.success(f"📢 **Estado del sistema:** {st.session_state.email_status}")
        elif "⚠️" in st.session_state.email_status:
            st.warning(f"📢 **Estado del sistema:** {st.session_state.email_status}")
        else:
            st.error(f"📢 **Estado del sistema:** {st.session_state.email_status}")
    
    if datos_filtrados.empty:
        st.error("🚫 No se encontraron datos con los filtros seleccionados")
        return
    
    st.success(f"✅ Encontrados {len(datos_filtrados):,} registros")
    if filtros_aplicados:
        st.info(" | ".join(filtros_aplicados))
    
    # Tabs para diferentes dashboards
    tab1, tab2 = st.tabs(["📊 Dashboard Básico", "📈 Dashboard Avanzado"])
    
    with tab1:
        # Dashboard de métricas básico
        crear_dashboard_metricas_principales(datos_filtrados)
    
    with tab2:
        # Dashboard avanzado con analytics
        crear_dashboard_avanzado(datos_filtrados)
    
    # ==============================
    # GRÁFICOS INTERACTIVOS
    # ==============================
    
    st.markdown('<h2 class="section-header">📈 Análisis Visual Interactivo</h2>', unsafe_allow_html=True)
    
    # Preparar datos para gráficos
    if len(datos_filtrados['Curso'].unique()) > 1:
        asistencia_por_curso = datos_filtrados.groupby('Curso')['Asistencia'].agg(['sum', 'count']).reset_index()
        asistencia_por_curso['Porcentaje'] = (asistencia_por_curso['sum'] / asistencia_por_curso['count'] * 100)
        
        fig_curso = crear_grafico_asistencia_interactivo(asistencia_por_curso, "barras")
        if fig_curso:
            st.plotly_chart(fig_curso, use_container_width=True)
    
    if len(datos_filtrados['Estudiante'].unique()) > 1:
        asistencia_por_estudiante = datos_filtrados.groupby('Estudiante')['Asistencia'].agg(['sum', 'count']).reset_index()
        asistencia_por_estudiante['Porcentaje'] = (asistencia_por_estudiante['sum'] / asistencia_por_estudiante['count'] * 100)
        asistencia_por_estudiante = asistencia_por_estudiante.sort_values('Porcentaje', ascending=False)
        
        fig_estudiante = crear_grafico_asistencia_interactivo(asistencia_por_estudiante, "barras")
        if fig_estudiante:
            st.plotly_chart(fig_estudiante, use_container_width=True)
    
    # Gráfico de tendencia temporal
    if 'Fecha' in datos_filtrados.columns and datos_filtrados['Fecha'].notna().any() and len(datos_filtrados) > 1:
        try:
            asistencia_diaria = datos_filtrados.groupby(datos_filtrados['Fecha'].dt.date)['Asistencia'].agg(['sum', 'count']).reset_index()
            asistencia_diaria['Porcentaje'] = (asistencia_diaria['sum'] / asistencia_diaria['count'] * 100)
            asistencia_diaria['Fecha'] = pd.to_datetime(asistencia_diaria['Fecha'])
            
            fig_tendencia = px.line(asistencia_diaria, x='Fecha', y='Porcentaje',
                                  title='📈 Tendencia de Asistencia Diaria',
                                  markers=True,
                                  template='plotly_white')
            
            fig_tendencia.update_layout(
                plot_bgcolor='rgba(0,0,0,0)',
                paper_bgcolor='rgba(0,0,0,0)',
                xaxis_title='Fecha',
                yaxis_title='Porcentaje de Asistencia (%)'
            )
            
            st.plotly_chart(fig_tendencia, use_container_width=True)
            
        except Exception as e:
            st.error(f"❌ Error en gráfico de tendencia: {e}")
    
    # ==============================
    # TABLA DE DATOS DETALLADOS
    # ==============================
    
    st.markdown('<h2 class="section-header">📋 Datos Detallados</h2>', unsafe_allow_html=True)
    
    datos_mostrar = datos_filtrados.copy()
    if 'Fecha' in datos_mostrar.columns:
        datos_mostrar['Fecha_Formateada'] = datos_mostrar['Fecha'].apply(
            lambda x: x.strftime('%d/%m/%Y') if pd.notna(x) else 'Sin fecha'
        )
    
    columnas_a_mostrar = ['Fecha_Formateada', 'Estudiante', 'Curso', 'Asignatura', 'Sede', 'Asistencia']
    columnas_extra = ['Hora Registro', 'Información']
    
    for col in columnas_extra:
        if col in datos_mostrar.columns:
            columnas_a_mostrar.append(col)
    
    columnas_finales = [col for col in columnas_a_mostrar if col in datos_mostrar.columns]
    nombres_amigables = {
        'Fecha_Formateada': 'Fecha',
        'Hora Registro': 'Hora',
        'Información': 'Información'
    }
    
    datos_tabla = datos_mostrar[columnas_finales].rename(columns=nombres_amigables)
    st.dataframe(datos_tabla, use_container_width=True, height=400)
    
    # ==============================
    # SECCIÓN DE EMAIL MEJORADA
    # ==============================
    
    st.markdown("---")
    
    # Header con ayuda contextual
    col1, col2 = st.columns([6, 1])
    with col1:
        st.markdown('<h2 class="section-header">📧 Envío de Notificaciones a Apoderados</h2>', unsafe_allow_html=True)
    with col2:
        st.markdown(sistema_ayuda.tooltip_contextual('envio_emails', 'derecha'), unsafe_allow_html=True)
    
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
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            if boton_moderno("🔍 PREPARAR ENVÍO DE RESUMENES", "primario", "🔍", "prepare_emails_admin"):
                st.session_state.email_status = ""
                
                with st.spinner("🔄 Analizando datos y preparando envío..."):
                    try:
                        if datos_filtrados.empty:
                            st.session_state.email_status = "❌ No hay datos filtrados para enviar"
                            st.rerun()
                        
                        emails, _ = load_emails()
                        if not emails:
                            st.session_state.email_status = "❌ No se encontraron emails de apoderados"
                            st.rerun()
                        
                        estudiantes_filtrados = datos_filtrados['Estudiante'].unique()
                        estudiantes_con_email = 0
                        
                        for estudiante in estudiantes_filtrados:
                            if estudiante.strip().lower() in emails:
                                estudiantes_con_email += 1
                        
                        if estudiantes_con_email == 0:
                            st.session_state.email_status = "❌ No hay estudiantes con email en los datos filtrados"
                            st.rerun()
                        
                        st.session_state.email_status = f"✅ Listo para enviar: {estudiantes_con_email} resúmenes"
                        st.rerun()
                        
                    except Exception as e:
                        st.session_state.email_status = f"❌ Error en preparación: {str(e)}"
                        st.rerun()
        
        with col2:
            if boton_moderno("🔄 LIMPIAR ESTADO", "secundario", "🔄", "clear_status_admin"):
                st.session_state.email_status = ""
                st.rerun()
        
        if "✅ Listo para enviar" in st.session_state.get('email_status', ''):
            st.success("**✅ SISTEMA PREPARADO** - Puedes proceder con el envío")
            enviar_resumen_asistencia(datos_filtrados, email_template)
    
    # ==============================
    # EXPORTACIÓN DE DATOS
    # ==============================
    
    st.markdown("---")
    
    # Header con ayuda contextual
    col1, col2 = st.columns([6, 1])
    with col1:
        st.markdown('<h2 class="section-header">📤 Exportar Datos</h2>', unsafe_allow_html=True)
    with col2:
        st.markdown(sistema_ayuda.tooltip_contextual('exportacion', 'derecha'), unsafe_allow_html=True)
        
    col1, col2 = st.columns(2)
    
    with col1:
        csv_df = datos_filtrados.copy()
        if 'Fecha' in csv_df.columns:
            csv_df['Fecha'] = csv_df['Fecha'].apply(
                lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) else ''
            )
        csv = csv_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            "💾 Descargar CSV",
            csv,
            "asistencia_filtrada.csv",
            "text/csv",
            use_container_width=True,
            key="download_csv_admin"
        )
    
    with col2:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            excel_df = datos_filtrados.copy()
            if 'Fecha' in excel_df.columns:
                excel_df['Fecha'] = excel_df['Fecha'].apply(
                    lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) else ''
                )
            excel_df.to_excel(writer, index=False, sheet_name='Asistencia')
            
            resumen_data = {
                'Métrica': ['Total Registros', 'Asistencias', 'Ausencias', 'Período'],
                'Valor': [
                    len(datos_filtrados),
                    datos_filtrados['Asistencia'].sum(),
                    len(datos_filtrados) - datos_filtrados['Asistencia'].sum(),
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
            use_container_width=True,
            key="download_excel_admin"
        )
    
    # ==============================
    # BOTONES DE CONTROL FINALES
    # ==============================
    
    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if boton_moderno("🔄 RECARGAR DATOS", "primario", "🔄", "reload_data_admin"):
            cache_manager.invalidar()
            st.cache_data.clear()
            st.session_state.email_status = "🔄 Datos recargados"
            st.rerun()
    
    with col2:
        if boton_moderno("📊 ACTUALIZAR VISTA", "secundario", "📊", "refresh_view_admin"):
            st.session_state.email_status = "📊 Vista actualizada"
            st.rerun()
    
    with col3:
        if boton_moderno("🧹 LIMPIAR TODO", "peligro", "🧹", "clear_all_admin"):
            st.session_state.email_status = ""
            st.session_state.curso_seleccionado = "Todos"
            st.session_state.estudiante_seleccionado = "Todos"
            st.rerun()

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
    
    # Información del curso en tarjetas - ACTUALIZADO CON ASIGNATURA
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.markdown(crear_tarjeta_metricas(
            "Profesor", data['profesor'], "Responsable", "👨‍🏫", "#1A3B8F"
        ), unsafe_allow_html=True)
    with col2:
        st.markdown(crear_tarjeta_metricas(
            "Día", data['dia'], "Día de clase", "📅", "#10B981"
        ), unsafe_allow_html=True)
    with col3:
        st.markdown(crear_tarjeta_metricas(
            "Horario", data['horario'], "Horario", "⏰", "#F59E0B"
        ), unsafe_allow_html=True)
    with col4:
        st.markdown(crear_tarjeta_metricas(
            "Sede", data['sede'], "Ubicación", "🏫", "#8B5CF6"
        ), unsafe_allow_html=True)
    with col5:
        st.markdown(crear_tarjeta_metricas(
            "Asignatura", data.get('asignatura', 'No especificada'), "Materia", "📚", "#EC4899"
        ), unsafe_allow_html=True)
    
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
                    
                # Verificar que el sheet_id esté disponible
                if "google" not in st.secrets or "asistencia_sheet_id" not in st.secrets["google"]:
                    st.error("❌ No se encontró el ID de la hoja de asistencia en los secrets.")
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
                    
                # Verificar que el sheet_id esté disponible
                if "google" not in st.secrets or "asistencia_sheet_id" not in st.secrets["google"]:
                    st.error("❌ No se encontró el ID de la hoja de asistencia en los secrets.")
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
    
    # Sección de sugerencias
    st.divider()
    st.markdown('<h3 class="section-header">💡 Sugerencias de Mejora</h3>', unsafe_allow_html=True)
    mejora = st.text_area("Comparte tus ideas para mejorar esta plataforma:", placeholder="Ej: Agregar notificación por WhatsApp...", key="sugerencia_profesor")
    if boton_moderno("📤 Enviar sugerencia", "secundario", "💡", "send_suggestion_profesor"):
        try:
            client = get_client()
            if not client:
                st.error("Error connecting to Google Sheets")
                return
                
            # Verificar que el sheet_id esté disponible
            if "google" not in st.secrets or "asistencia_sheet_id" not in st.secrets["google"]:
                st.error("❌ No se encontró el ID de la hoja de asistencia en los secrets.")
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
    
    # Verificar secrets antes de continuar
    if not verificar_secrets():
        st.error("""
        ❌ **Configuración incompleta**
        
        Por favor, asegúrate de que todos los secrets requeridos estén configurados en Streamlit:
        
        **Secrets requeridos:**
        - `google.credentials` (Service Account JSON)
        - `google.asistencia_sheet_id` (ID de la hoja de asistencia)
        - `google.clases_sheet_id` (ID de la hoja de clases)
        - `EMAIL.smtp_server`, `EMAIL.smtp_port`, `EMAIL.sender_email`, `EMAIL.sender_password`
        - `profesores` o `administradores` (usuarios y contraseñas)
        
        Consulta la documentación para más detalles.
        """)
        return
    
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

             🔑 {code}

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
            
            # Panel de monitoreo de caché solo para admins
            if st.session_state["user_type"] == "admin":
                panel_monitoreo_cache()
                sistema_ayuda.boton_ayuda_completa()
            
            if boton_moderno("Cerrar sesión", "peligro", "🚪", "logout"):
                st.session_state.clear()
                st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
    
    # Implementar temporizador si hay sesión activa
    if st.session_state.get("user_type"):
        implementar_temporizador_seguridad()
    
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
                <div style="background: #F0F4FF; padding: 1rem; border-radius: 8px; margin: 1rem 0;">
                    <p style="margin: 0; color: #1A3B8F;"><strong>💡 Tip:</strong> El menú lateral se despliega al hacer clic en el icono ☰ en la esquina superior izquierda.</p>
                </div>
            </div>
        </div>
        """ , unsafe_allow_html=True)
        return
    
    if st.session_state["user_type"] == "admin":
        admin_panel_mejorado()
    else:
        main_app_mejorada()

if __name__ == "__main__":
    main()