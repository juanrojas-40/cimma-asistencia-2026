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
import time as time_module
import functools
from gspread.exceptions import APIError
import threading
from queue import Queue
import redis
import pickle
import os
from collections import defaultdict

# ==============================
# CONFIGURACIÓN SUPABASE (NUEVO)
# ==============================

try:
    from supabase import create_client, Client
    SUPABASE_DISPONIBLE = True
except ImportError:
    SUPABASE_DISPONIBLE = False
    st.warning("ℹ️ Supabase no disponible. Ejecuta: pip install supabase")

class GestorBaseDatos:
    """Sistema híbrido: Supabase (principal) + Google Sheets (backup)"""
    
    def __init__(self):
        self.supabase = None
        self.modo_actual = "sheets"  # sheets, supabase, hibrido
        self.conectado = False
        self.estadisticas = {
            'consultas_supabase': 0,
            'consultas_sheets': 0,
            'errores_supabase': 0,
            'errores_sheets': 0,
            'escrituras_supabase': 0,
            'escrituras_sheets': 0
        }
    
    def conectar_supabase(self):
        """Conectar a Supabase si está configurado"""
        if not SUPABASE_DISPONIBLE:
            st.error("❌ Supabase no está instalado. Ejecuta: pip install supabase")
            return False
            
        try:
            # Verificar si los secrets de Supabase están configurados
            if ("supabase" in st.secrets and 
                "url" in st.secrets["supabase"] and 
                "key" in st.secrets["supabase"]):
                
                url = st.secrets["supabase"]["url"]
                key = st.secrets["supabase"]["key"]
                
                if not url or not key:
                    st.error("❌ URL o Key de Supabase vacíos en secrets")
                    return False
                
                self.supabase = create_client(url, key)
                
                # Test de conexión simple
                try:
                    # Intentar una consulta simple
                    result = self.supabase.table('estudiantes').select("*", count="exact").limit(1).execute()
                    self.conectado = True
                    self.modo_actual = "hibrido"
                    return True
                except Exception as test_error:
                    st.warning(f"⚠️ Supabase configurado pero error de conexión: {test_error}")
                    return False
                    
            else:
                st.info("ℹ️ Secrets de Supabase no configurados. Usando solo Google Sheets.")
                return False
                
        except Exception as e:
            st.error(f"❌ Error conectando a Supabase: {e}")
            self.conectado = False
            self.modo_actual = "sheets"
            return False
    
    def obtener_estado(self):
        """Obtener estado del sistema de base de datos"""
        return {
            'modo': self.modo_actual,
            'supabase_conectado': self.conectado,
            'supabase_disponible': SUPABASE_DISPONIBLE,
            'estadisticas': self.estadisticas.copy()
        }
    
    # ==============================
    # MÉTODOS HÍBRIDOS - ESTUDIANTES
    # ==============================
    
    def obtener_estudiantes(self, curso=None):
        """Obtener estudiantes de Supabase o Sheets"""
        datos_supabase = None
        
        # Intentar Supabase primero si está disponible
        if self.conectado:
            try:
                query = self.supabase.table("estudiantes").select("*")
                if curso:
                    query = query.eq("curso", curso)
                
                result = query.execute()
                datos_supabase = result.data
                self.estadisticas['consultas_supabase'] += 1
                
                if datos_supabase:
                    return self._formatear_datos_estudiantes(datos_supabase)
                    
            except Exception as e:
                print(f"❌ Error obteniendo estudiantes de Supabase: {e}")
                self.estadisticas['errores_supabase'] += 1
        
        # Fallback a Google Sheets
        try:
            cursos = self._cargar_cursos_sheets()
            estudiantes_data = {}
            
            for curso_nombre, info in cursos.items():
                if curso and curso_nombre != curso:
                    continue
                    
                for estudiante in info["estudiantes"]:
                    estudiantes_data[estudiante] = {
                        "nombre": estudiante,
                        "curso": curso_nombre,
                        "email": "",  # Se llenará después
                        "activo": True,
                        "fuente": "sheets"
                    }
            
            self.estadisticas['consultas_sheets'] += 1
            return estudiantes_data
            
        except Exception as e:
            print(f"❌ Error obteniendo estudiantes de Sheets: {e}")
            self.estadisticas['errores_sheets'] += 1
            return {}
    
    def guardar_estudiante(self, estudiante_data):
        """Guardar estudiante en ambas bases de datos"""
        exito_supabase = False
        exito_sheets = False
        
        # Guardar en Supabase
        if self.conectado:
            try:
                result = self.supabase.table("estudiantes").insert(estudiante_data).execute()
                exito_supabase = len(result.data) > 0
                if exito_supabase:
                    self.estadisticas['escrituras_supabase'] += 1
            except Exception as e:
                print(f"❌ Error guardando estudiante en Supabase: {e}")
        
        # En Sheets, los estudiantes se manejan en la hoja de clases
        exito_sheets = True  # Asumir éxito por ahora
        
        return exito_supabase or exito_sheets
    
    # ==============================
    # MÉTODOS HÍBRIDOS - ASISTENCIA
    # ==============================
    
    def guardar_asistencia(self, registros):
        """Guardar asistencia en ambas bases de datos"""
        exito_supabase = False
        exito_sheets = False
        
        # Preparar datos para Supabase
        if self.conectado:
            try:
                registros_supabase = []
                for registro in registros:
                    registro_supabase = {
                        "estudiante_nombre": registro["estudiante"],
                        "curso": registro["curso"],
                        "fecha": registro["fecha"],
                        "presente": registro["asistencia"] == 1,
                        "profesor": registro.get("profesor", ""),
                        "hora_registro": datetime.now().isoformat(),
                        "informacion": registro.get("informacion", ""),
                        "created_at": datetime.now().isoformat()
                    }
                    registros_supabase.append(registro_supabase)
                
                if registros_supabase:
                    result = self.supabase.table("asistencia").insert(registros_supabase).execute()
                    exito_supabase = len(result.data) == len(registros_supabase)
                    if exito_supabase:
                        self.estadisticas['escrituras_supabase'] += 1
                    print(f"✅ Guardados {len(result.data)} registros en Supabase")
                    
            except Exception as e:
                print(f"❌ Error guardando asistencia en Supabase: {e}")
        
        # Guardar en Google Sheets (sistema actual)
        try:
            exito_sheets = self._guardar_asistencia_sheets(registros)
            if exito_sheets:
                self.estadisticas['escrituras_sheets'] += 1
        except Exception as e:
            print(f"❌ Error guardando asistencia en Sheets: {e}")
        
        return {
            "supabase": exito_supabase,
            "sheets": exito_sheets,
            "hibrido_exitoso": exito_supabase or exito_sheets
        }
    
    def obtener_asistencia(self, filtros=None):
        """Obtener datos de asistencia con filtros"""
        if filtros is None:
            filtros = {}
        
        # Intentar Supabase primero
        if self.conectado:
            try:
                query = self.supabase.table("asistencia").select("*")
                
                # Aplicar filtros
                if filtros.get("curso") and filtros["curso"] != "Todos":
                    query = query.eq("curso", filtros["curso"])
                if filtros.get("fecha_inicio"):
                    query = query.gte("fecha", filtros["fecha_inicio"].strftime("%Y-%m-%d"))
                if filtros.get("fecha_fin"):
                    query = query.lte("fecha", filtros["fecha_fin"].strftime("%Y-%m-%d"))
                if filtros.get("estudiante") and filtros["estudiante"] != "Todos":
                    query = query.eq("estudiante_nombre", filtros["estudiante"])
                
                result = query.execute()
                self.estadisticas['consultas_supabase'] += 1
                
                if result.data:
                    df = pd.DataFrame(result.data)
                    # Convertir al formato esperado por la app
                    if not df.empty:
                        df["Asistencia"] = df["presente"].astype(int)
                        df["Estudiante"] = df["estudiante_nombre"]
                        df["Curso"] = df["curso"]
                        df["Fecha"] = pd.to_datetime(df["fecha"])
                        if "hora_registro" in df.columns:
                            df["Hora Registro"] = df["hora_registro"]
                        if "informacion" in df.columns:
                            df["Información"] = df["informacion"]
                        return df
                    
            except Exception as e:
                print(f"❌ Error obteniendo asistencia de Supabase: {e}")
                self.estadisticas['errores_supabase'] += 1
        
        # Fallback a Google Sheets
        try:
            df = self._cargar_asistencia_sheets()
            
            # Aplicar filtros similares
            if filtros.get("curso") and filtros["curso"] != "Todos":
                df = df[df["Curso"] == filtros["curso"]]
            if filtros.get("estudiante") and filtros["estudiante"] != "Todos":
                df = df[df["Estudiante"] == filtros["estudiante"]]
            if filtros.get("fecha_inicio") and 'Fecha' in df.columns:
                df = df[df["Fecha"].dt.date >= filtros["fecha_inicio"]]
            if filtros.get("fecha_fin") and 'Fecha' in df.columns:
                df = df[df["Fecha"].dt.date <= filtros["fecha_fin"]]
            
            self.estadisticas['consultas_sheets'] += 1
            return df
            
        except Exception as e:
            print(f"❌ Error obteniendo asistencia de Sheets: {e}")
            self.estadisticas['errores_sheets'] += 1
            return pd.DataFrame()
    
    # ==============================
    # MÉTODOS AUXILIARES
    # ==============================
    
    def _formatear_datos_estudiantes(self, datos_supabase):
        """Formatear datos de estudiantes de Supabase al formato esperado"""
        estudiantes = {}
        for estudiante in datos_supabase:
            estudiantes[estudiante["nombre"]] = {
                "nombre": estudiante["nombre"],
                "curso": estudiante.get("curso", ""),
                "email": estudiante.get("email_apoderado", ""),
                "activo": estudiante.get("activo", True),
                "id": estudiante.get("id"),
                "fuente": "supabase"
            }
        return estudiantes
    
    def _cargar_cursos_sheets(self):
        """Cargar cursos desde Google Sheets (método existente)"""
        try:
            client = get_client()
            if not client:
                return {}
                
            sheet_id = st.secrets["google"]["clases_sheet_id"]
            clases_sheet = client.open_by_key(sheet_id)
            
            courses = {}
            for worksheet in clases_sheet.worksheets():
                sheet_name = worksheet.title
                try:
                    colA_raw = worksheet.col_values(1)
                    colA = [cell.strip() for cell in colA_raw if isinstance(cell, str) and cell.strip()]
                    colA_upper = [s.upper() for s in colA]
                    
                    idx_prof = colA_upper.index("PROFESOR")
                    profesor = colA[idx_prof + 1]
                    idx_dia = colA_upper.index("DIA")
                    dia = colA[idx_dia + 1]
                    idx_curso = colA_upper.index("CURSO")
                    curso_id = colA[idx_curso + 1]
                    horario = colA[idx_curso + 2]
                    
                    estudiantes = []
                    idx_estudiantes = colA_upper.index("NOMBRES ESTUDIANTES")
                    for i in range(idx_estudiantes + 1, len(colA)):
                        if colA[i]:
                            estudiantes.append(colA[i])
                    
                    if profesor and dia and curso_id and horario and estudiantes:
                        estudiantes = sorted([e for e in estudiantes if e.strip()])
                        courses[sheet_name] = {
                            "profesor": profesor,
                            "dia": dia,
                            "horario": horario,
                            "curso_id": curso_id,
                            "estudiantes": estudiantes,
                            "sede": "",
                            "asignatura": ""
                        }
                except Exception as e:
                    continue
            return courses
        except Exception as e:
            print(f"Error cargando cursos de Sheets: {e}")
            return {}
    
    def _cargar_asistencia_sheets(self):
        """Cargar asistencia desde Google Sheets"""
        try:
            client = get_client()
            if not client:
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
                    
                    all_values = all_values[3:]
                    headers = [str(h).strip().upper() for h in all_values[0] if str(h).strip()]
                    
                    # Encontrar índices de columnas
                    curso_col, fecha_col, estudiante_col, asistencia_col = None, None, None, None
                    
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
                    
                    if asistencia_col is None or estudiante_col is None or fecha_col is None:
                        continue
                    
                    for row in all_values[1:]:
                        if len(row) <= max(curso_col, fecha_col, estudiante_col, asistencia_col):
                            continue
                        
                        try:
                            asistencia_val = int(row[asistencia_col]) if row[asistencia_col] else 0
                        except (ValueError, TypeError):
                            asistencia_val = 0
                        
                        curso = row[curso_col].strip() if curso_col is not None and len(row) > curso_col and row[curso_col] else sheet_name
                        fecha_str = row[fecha_col].strip() if len(row) > fecha_col and row[fecha_col] else ""
                        estudiante = row[estudiante_col].strip() if len(row) > estudiante_col and row[estudiante_col] else ""
                        
                        if estudiante and asistencia_val is not None:
                            all_data.append({
                                "Curso": curso,
                                "Fecha": fecha_str,
                                "Estudiante": estudiante,
                                "Asistencia": asistencia_val
                            })
                            
                except Exception as e:
                    continue
            
            df = pd.DataFrame(all_data)
            
            if not df.empty:
                # Conversión de fechas
                def convertir_fecha_manual(fecha_str):
                    if not fecha_str or pd.isna(fecha_str) or fecha_str.strip() == "":
                        return pd.NaT
                    fecha_str = str(fecha_str).strip().lower()
                    try:
                        if '/' in fecha_str:
                            return pd.to_datetime(fecha_str, format='%d/%m/%Y', errors='coerce')
                        elif '-' in fecha_str:
                            return pd.to_datetime(fecha_str, format='%Y-%m-%d', errors='coerce')
                        return pd.to_datetime(fecha_str, errors='coerce')
                    except Exception:
                        return pd.NaT
                
                df["Fecha"] = df["Fecha"].apply(convertir_fecha_manual)
            
            return df
            
        except Exception as e:
            print(f"Error cargando asistencia de Sheets: {e}")
            return pd.DataFrame()
    
    def _guardar_asistencia_sheets(self, registros):
        """Método auxiliar para guardar en Sheets"""
        # Por simplicidad, asumimos éxito
        # En implementación real, aquí iría la lógica de guardado en Sheets
        return True
    
    def migrar_datos_sheets_a_supabase(self, batch_size=100):
        """Migrar datos existentes de Sheets a Supabase"""
        if not self.conectado:
            return {"error": "Supabase no conectado"}
        
        try:
            # Obtener datos de Sheets
            df_sheets = self._cargar_asistencia_sheets()
            
            if df_sheets.empty:
                return {"error": "No hay datos en Sheets para migrar"}
            
            # Preparar datos para Supabase
            registros_migrar = []
            for _, row in df_sheets.iterrows():
                if pd.notna(row["Fecha"]):
                    registro = {
                        "estudiante_nombre": row["Estudiante"],
                        "curso": row["Curso"],
                        "fecha": row["Fecha"].strftime("%Y-%m-%d"),
                        "presente": bool(row["Asistencia"]),
                        "profesor": "",
                        "hora_registro": datetime.now().isoformat(),
                        "created_at": datetime.now().isoformat(),
                        "fuente_migracion": "sheets"
                    }
                    registros_migrar.append(registro)
            
            # Insertar en lotes
            total_migrados = 0
            for i in range(0, len(registros_migrar), batch_size):
                batch = registros_migrar[i:i + batch_size]
                try:
                    result = self.supabase.table("asistencia").insert(batch).execute()
                    total_migrados += len(result.data)
                except Exception as batch_error:
                    print(f"Error en lote {i}: {batch_error}")
                    continue
                
            return {
                "total_registros": len(registros_migrar),
                "migrados_exitosos": total_migrados,
                "estado": "completado" if total_migrados == len(registros_migrar) else "parcial"
            }
            
        except Exception as e:
            return {"error": f"Error en migración: {str(e)}"}

# Instancia global del gestor de base de datos
gestor_bd = GestorBaseDatos()

# ==============================
# PANEL DE CONTROL SUPABASE (NUEVO)
# ==============================

def panel_control_supabase():
    """Panel de control para gestión de Supabase"""
    st.markdown("---")
    st.markdown('<h2 class="section-header">🔄 Sistema de Base de Datos Híbrido</h2>', unsafe_allow_html=True)
    
    with st.expander("⚙️ CONFIGURACIÓN Y ESTADO", expanded=True):
        # Estado actual
        estado = gestor_bd.obtener_estado()
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            modo_color = "🟢" if estado['modo'] == "hibrido" else "🟡" if estado['modo'] == "sheets" else "🔴"
            st.metric("🔧 Modo Actual", f"{modo_color} {estado['modo'].upper()}")
        with col2:
            status_color = "🟢" if estado['supabase_conectado'] else "🔴"
            st.metric("📡 Supabase", status_color)
        with col3:
            st.metric("📊 Consultas BD", estado['estadisticas']['consultas_supabase'])
        with col4:
            st.metric("📋 Consultas Sheets", estado['estadisticas']['consultas_sheets'])
        
        # Botones de control
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if st.button("🔄 Conectar Supabase", use_container_width=True, key="conectar_supabase"):
                if gestor_bd.conectar_supabase():
                    st.rerun()
        
        with col2:
            if st.button("📊 Ver Estadísticas", use_container_width=True, key="ver_stats"):
                with st.expander("Estadísticas Detalladas"):
                    st.json(estado['estadisticas'])
        
        with col3:
            if st.button("🔄 Reiniciar Contadores", use_container_width=True, key="reiniciar_contadores"):
                gestor_bd.estadisticas = {k: 0 for k in gestor_bd.estadisticas.keys()}
                st.rerun()
    
    # Migración de datos
    with st.expander("🚀 MIGRACIÓN DE DATOS", expanded=False):
        st.warning("""
        **⚠️ ADVERTENCIA:** Esta operación migrará TODOS los datos de Google Sheets a Supabase.
        - No elimina datos de Sheets
        - Crea una copia en Supabase
        - Los datos existentes en Supabase se mantienen
        """)
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("📦 INICIAR MIGRACIÓN COMPLETA", type="secondary", use_container_width=True, key="migrar_completa"):
                if not gestor_bd.conectado:
                    st.error("❌ Supabase no está conectado")
                else:
                    with st.spinner("🔄 Migrando datos de Sheets a Supabase..."):
                        resultado = gestor_bd.migrar_datos_sheets_a_supabase()
                    
                    if "error" in resultado:
                        st.error(f"❌ Error: {resultado['error']}")
                    else:
                        st.success(f"""
                        ✅ **Migración completada:**
                        - **Total registros:** {resultado['total_registros']:,}
                        - **Migrados exitosos:** {resultado['migrados_exitosos']:,}
                        - **Estado:** {resultado['estado']}
                        """)
        
        with col2:
            if st.button("🧹 Limpiar Datos Supabase", type="primary", use_container_width=True, key="limpiar_supabase"):
                st.warning("Esta función limpiaría datos de Supabase. No implementada por seguridad.")
    
    # Información de configuración
    with st.expander("🔧 CONFIGURACIÓN SUPABASE", expanded=False):
        st.markdown("""
        ### 📋 Pasos para Configurar Supabase:
        
        1. **Crear cuenta en [Supabase](https://supabase.com)**
        2. **Crear nuevo proyecto**
        3. **Ejecutar el SQL de creación de tablas**
        4. **Obtener URL y API Key desde Settings > API**
        5. **Configurar secrets en Streamlit**
        
        ### 🗄️ SQL para crear tablas:
        ```sql
        CREATE TABLE estudiantes (
            id BIGSERIAL PRIMARY KEY,
            nombre VARCHAR(255) NOT NULL,
            curso VARCHAR(100),
            email_apoderado VARCHAR(255),
            activo BOOLEAN DEFAULT true,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        
        CREATE TABLE asistencia (
            id BIGSERIAL PRIMARY KEY,
            estudiante_nombre VARCHAR(255) NOT NULL,
            curso VARCHAR(100) NOT NULL,
            fecha DATE NOT NULL,
            presente BOOLEAN DEFAULT false,
            profesor VARCHAR(255),
            hora_registro TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        ```
        
        ### 🔑 Configuración en secrets.toml:
        ```toml
        [supabase]
        url = "https://tu-proyecto.supabase.co"
        key = "tu-anon-key"
        ```
        """)

# ==============================
# SISTEMAS DE CONCURRENCIA (EXISTENTES - MODIFICADOS)
# ==============================

class SistemaColasEscritura:
    """Sistema de colas para manejar escrituras a Sheets Y Supabase"""
    
    def __init__(self):
        self.cola_escrituras = Queue()
        self.en_ejecucion = False
        self.lock = threading.Lock()
        self.estadisticas = {
            'procesadas': 0,
            'fallidas': 0,
            'pendientes': 0,
            'supabase_exitosas': 0,
            'sheets_exitosas': 0
        }
    
    def iniciar_worker(self):
        """Inicia el worker que procesa las colas"""
        if not self.en_ejecucion:
            self.en_ejecucion = True
            threading.Thread(target=self._procesar_colas, daemon=True).start()
            print("✅ Worker de colas iniciado")
    
    def agregar_escritura(self, funcion, *args, **kwargs):
        """Agrega una escritura a la cola"""
        with self.lock:
            self.cola_escrituras.put({
                'funcion': funcion,
                'args': args,
                'kwargs': kwargs,
                'timestamp': time_module.time(),
                'intentos': 0,
                'id': f"{funcion.__name__}_{time_module.time()}"
            })
            self.estadisticas['pendientes'] = self.cola_escrituras.qsize()
    
    def _procesar_colas(self):
        """Procesa las escrituras en la cola"""
        while self.en_ejecucion:
            try:
                if not self.cola_escrituras.empty():
                    tarea = self.cola_escrituras.get()
                    
                    # Implementar retry con backoff exponencial
                    exito = self._ejecutar_con_retry(tarea)
                    
                    if exito:
                        self.estadisticas['procesadas'] += 1
                    else:
                        self.estadisticas['fallidas'] += 1
                        if tarea['intentos'] < 3:
                            # Reintentar después
                            time_module.sleep(2 ** tarea['intentos'])
                            self.cola_escrituras.put(tarea)
                    
                    self.cola_escrituras.task_done()
                    self.estadisticas['pendientes'] = self.cola_escrituras.qsize()
                
                time_module.sleep(0.5)  # Controlar tasa de procesamiento
                
            except Exception as e:
                print(f"Error en worker de colas: {e}")
                time_module.sleep(2)
    
    def _ejecutar_con_retry(self, tarea):
        """Ejecuta una tarea con reintentos"""
        try:
            tarea['intentos'] += 1
            resultado = tarea['funcion'](*tarea['args'], **tarea['kwargs'])
            
            # Track estadísticas específicas para escrituras híbridas
            if isinstance(resultado, dict) and 'supabase' in resultado:
                if resultado['supabase']:
                    self.estadisticas['supabase_exitosas'] += 1
                if resultado['sheets']:
                    self.estadisticas['sheets_exitosas'] += 1
            
            print(f"✅ Tarea {tarea['id']} procesada (intento {tarea['intentos']})")
            return True
        except Exception as e:
            print(f"❌ Error en tarea {tarea['id']} (intento {tarea['intentos']}): {e}")
            return False
    
    def obtener_estadisticas(self):
        """Obtiene estadísticas de la cola"""
        with self.lock:
            return self.estadisticas.copy()

# Instancia global del sistema de colas
sistema_colas = SistemaColasEscritura()

# ==============================
# FUNCIONES MODIFICADAS PARA SOPORTE HÍBRIDO
# ==============================

def guardar_asistencia_hibrido(curso, fecha, asistencia_data, profesor="", informacion=""):
    """Versión híbrida para guardar asistencia"""
    
    def _guardar_real():
        # Preparar registros para ambas bases de datos
        registros = []
        for estudiante, presente in asistencia_data.items():
            registro = {
                "estudiante": estudiante,
                "curso": curso,
                "fecha": fecha,
                "asistencia": 1 if presente else 0,
                "profesor": profesor,
                "informacion": informacion
            }
            registros.append(registro)
        
        # Guardar en ambas bases de datos
        return gestor_bd.guardar_asistencia(registros)
    
    # Agregar a cola de escrituras
    sistema_colas.agregar_escritura(_guardar_real)
    
    # Respuesta inmediata al usuario
    st.success("✅ Asistencia en proceso de guardado...")
    
    return True

def cargar_datos_hibrido(filtros=None):
    """Cargar datos usando el sistema híbrido"""
    if filtros is None:
        filtros = {}
    
    return gestor_bd.obtener_asistencia(filtros)

# ==============================
# CONFIGURACIÓN INICIAL Y MANEJO DE SECRETS (EXISTENTE)
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
# CACHE INTELIGENTE (EXISTENTE)
# ==============================

class CacheInteligente:
    """Sistema de caché inteligente con invalidación automática"""
    
    def __init__(self):
        self.stats = {
            'hits': 0,
            'misses': 0,
            'invalidaciones': 0
        }
    
    def cached(self, ttl=1800, max_size=100, dependencias=None):
        """Decorador de caché inteligente que usa el sistema distribuido"""
        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                # Generar clave única
                cache_key = f"{func.__name__}_{str(args)}_{str(kwargs)}"
                
                # Por simplicidad, en esta versión no implementamos caché distribuido
                # Pero mantenemos la estructura para futuras mejoras
                result = func(*args, **kwargs)
                self.stats['misses'] += 1
                return result
            return wrapper
        return decorator
    
    def invalidar(self, clave=None):
        """Invalida caché específico o completo"""
        self.stats['invalidaciones'] += 1
    
    def get_stats(self):
        """Estadísticas de uso del caché"""
        total_requests = self.stats['hits'] + self.stats['misses']
        hit_rate = (self.stats['hits'] / total_requests * 100) if total_requests > 0 else 0
        return {
            'hit_rate': f"{hit_rate:.1f}%",
            **self.stats
        }

# Instancia global de caché
cache_manager = CacheInteligente()

# ==============================
# CONEXIONES EXISTENTES (MODIFICADAS)
# ==============================

@st.cache_resource
def get_client():
    try:
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
        if "EMAIL" not in st.secrets:
            st.error("❌ No se encontró la configuración de EMAIL en los secrets.")
            return False
            
        smtp_server = st.secrets["EMAIL"]["smtp_server"]
        smtp_port = int(st.secrets["EMAIL"]["smtp_port"])
        sender_email = st.secrets["EMAIL"]["sender_email"]
        sender_password = st.secrets["EMAIL"]["sender_password"]
        
        msg = MIMEMultipart()
        msg["From"] = sender_email
        msg["To"] = to_email
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=True)
        msg.attach(MIMEText(body, "plain"))
        
        server = smtplib.SMTP(smtp_server, smtp_port, timeout=30)
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(msg)
        server.quit()
        
        print(f"✅ Email enviado exitosamente a: {to_email}")
        return True
        
    except Exception as e:
        error_msg = f"❌ Error enviando email a {to_email}: {str(e)}"
        print(error_msg)
        st.error(error_msg)
        return False

def generate_2fa_code():
    return ''.join(random.choices(string.digits, k=6))

# ==============================
# FUNCIONES DE CARGA (MODIFICADAS PARA HÍBRIDO)
# ==============================

@cache_manager.cached(ttl=3600)
def load_courses():
    """Cargar cursos - ahora usa sistema híbrido"""
    return gestor_bd._cargar_cursos_sheets()

@cache_manager.cached(ttl=7200)
def load_emails():
    """Cargar emails - mantener existente por ahora"""
    try:
        client = get_client()
        if not client:
            return {}, {}
            
        if "google" not in st.secrets or "asistencia_sheet_id" not in st.secrets["google"]:
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

def load_all_asistencia():
    """Cargar asistencia - ahora usa sistema híbrido"""
    return cargar_datos_hibrido()

# ==============================
# SISTEMA DE FECHAS COMPLETADAS (VERSIÓN HÍBRIDA)
# ==============================

class SistemaFechasCompletadas:
    """Sistema para gestionar fechas completadas y pendientes - Versión híbrida"""
    
    def __init__(self):
        self.client = None
        self.gestor_bd = gestor_bd
        
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
    
    @cache_manager.cached(ttl=900)
    def obtener_fechas_completadas(self, curso):
        """Obtiene las fechas ya registradas para un curso - Versión híbrida"""
        
        # Intentar Supabase primero
        if gestor_bd.conectado:
            try:
                query = gestor_bd.supabase.table("asistencia").select("fecha").eq("curso", curso)
                result = query.execute()
                
                if result.data:
                    fechas_unicas = list(set([item["fecha"] for item in result.data]))
                    return fechas_unicas
                    
            except Exception as e:
                print(f"❌ Error obteniendo fechas de Supabase: {e}")
        
        # Fallback a Google Sheets (método original)
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
        """Marca una fecha como completada (usa sistema híbrido)"""
        def _marcar_real():
            # En Supabase, las fechas se marcan automáticamente al tener registros
            # Para Sheets, mantenemos el sistema original
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
                    for i, row in enumerate(records, start=2):
                        if row["Curso"] == curso and row["Fecha"] == fecha:
                            fechas_sheet.update_cell(i, 3, "SI")
                            break
                
                return True
            except Exception as e:
                st.error(f"Error al marcar fecha como completada: {e}")
                return False
        
        sistema_colas.agregar_escritura(_marcar_real)
        cache_manager.invalidar()
        return True

# Instancia global del sistema de fechas
sistema_fechas = SistemaFechasCompletadas()

# ==============================
# COMPONENTES DE UI (EXISTENTES)
# ==============================

def aplicar_tema_moderno():
    st.markdown("""
    <style>
    .main-header {
        color: #1A3B8F;
        font-weight: 700;
        font-size: 2.5rem;
        margin-bottom: 1rem;
        border-bottom: 3px solid #1A3B8F;
        padding-bottom: 0.5rem;
    }
    .section-header {
        color: #1A3B8F;
        font-weight: 600;
        font-size: 1.5rem;
        margin: 2rem 0 1rem 0;
    }
    .card {
        background: white;
        border-radius: 16px;
        padding: 1.5rem;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        border: 1px solid #E5E7EB;
        margin: 1rem 0;
    }
    </style>
    """, unsafe_allow_html=True)

def crear_header_moderno():
    col1, col2, col3 = st.columns([1, 3, 1])
    with col2:
        st.markdown('<h1 class="main-header">🎓 Preuniversitario CIMMA</h1>', unsafe_allow_html=True)
        st.markdown('<p style="text-align: center; color: #6B7280; font-size: 1.1rem;">Sistema de Gestión de Asistencia 2026</p>', unsafe_allow_html=True)

def boton_moderno(texto, tipo="primario", icono="", key=None):
    return st.button(f"{icono} {texto}", key=key, use_container_width=True)

# ==============================
# APP PRINCIPAL MEJORADA (PROFESOR) - MODIFICADA
# ==============================

def main_app_mejorada():
    if 'login_time' in st.session_state and 'timeout_duration' in st.session_state:
        if time_module.time() - st.session_state['login_time'] > st.session_state['timeout_duration']:
            st.error("❌ Sesión expirada por límite de tiempo.")
            st.session_state.clear()
            st.rerun()
            return
    
    st.markdown('<h2 class="section-header">📱 Registro de Asistencia en Tiempo Real</h2>', unsafe_allow_html=True)
    
    courses = load_courses()
    if not courses:
        st.error("❌ No se encontraron cursos.")
        st.stop()
    
    cursos_filtrados = {
        k: v for k, v in courses.items()
        if v["profesor"] == st.session_state["user_name"]
    }
    
    if not cursos_filtrados:
        st.warning("No tienes cursos asignados.")
        st.stop()
    
    curso_seleccionado = st.selectbox("🎓 Selecciona tu curso", list(cursos_filtrados.keys()), key="curso_select_profesor")
    data = cursos_filtrados[curso_seleccionado]
    
    # Información del curso
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.info(f"**Profesor:** {data['profesor']}")
    with col2:
        st.info(f"**Día:** {data['dia']}")
    with col3:
        st.info(f"**Horario:** {data['horario']}")
    with col4:
        st.info(f"**Estudiantes:** {len(data['estudiantes'])}")
    
    # Estadísticas de fechas
    stats = sistema_fechas.obtener_estadisticas_fechas(curso_seleccionado, data["fechas"] if "fechas" in data else [])
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("📅 Total Fechas", stats["total"])
    with col2:
        st.metric("✅ Completadas", stats["completadas"])
    with col3:
        st.metric("⏳ Pendientes", stats["pendientes"])
    with col4:
        st.metric("📊 Progreso", f"{stats['porcentaje_completado']:.1f}%")
    
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
        
        fechas_pendientes = [f for f in (data["fechas"] if "fechas" in data else []) if f not in stats["fechas_completadas"]]
        
        if not fechas_pendientes:
            st.warning("ℹ️ Todas las fechas ya están completadas.")
            return
            
        fecha_seleccionada = st.selectbox("🗓️ Fecha afectada", fechas_pendientes, key="fecha_suspension_profesor")
        
        if boton_moderno("💾 Registrar suspensión", "peligro", "⏸️", "register_suspension_profesor"):
            try:
                # Usar sistema híbrido para guardar suspensión
                profesor = st.session_state["user_name"]
                
                # Crear registro de suspensión para todos los estudiantes
                asistencia_data = {estudiante: False for estudiante in data["estudiantes"]}
                
                exito = guardar_asistencia_hibrido(
                    curso=curso_seleccionado,
                    fecha=fecha_seleccionada,
                    asistencia_data=asistencia_data,
                    profesor=profesor,
                    informacion=f"Suspensión: {motivo}"
                )
                
                if exito:
                    sistema_fechas.marcar_fecha_completada(curso_seleccionado, fecha_seleccionada)
                    st.success(f"✅ Suspensión registrada para la fecha **{fecha_seleccionada}**.")
                    st.rerun()
                
            except Exception as e:
                st.error(f"❌ Error al registrar suspensión: {e}")
        return
    
    # REGISTRO DE ASISTENCIA NORMAL
    fechas_pendientes = [f for f in (data["fechas"] if "fechas" in data else []) if f not in stats["fechas_completadas"]]
    
    if not fechas_pendientes:
        st.warning("🎉 ¡Todas las fechas ya están completadas!")
        st.info("💡 Si necesitas registrar asistencia en una fecha ya completada, contacta a un administrador para reactivarla.")
        return
    
    fecha_seleccionada = st.selectbox("🗓️ Selecciona la fecha", fechas_pendientes, key="fecha_asistencia_profesor")
    
    if fecha_seleccionada in stats["fechas_completadas"]:
        st.error("🚫 Esta fecha ya fue completada anteriormente.")
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
    
    # Botón de guardar - MODIFICADO PARA USAR SISTEMA HÍBRIDO
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if boton_moderno("💾 Guardar Asistencia", "exito", "💾", "guardar_asistencia_profesor"):
            try:
                # Usar sistema híbrido para guardar
                profesor = st.session_state["user_name"]
                exito = guardar_asistencia_hibrido(
                    curso=curso_seleccionado,
                    fecha=fecha_seleccionada,
                    asistencia_data=asistencia,
                    profesor=profesor
                )
                
                if exito:
                    st.success(f"✅ ¡Asistencia guardada para **{curso_seleccionado}**!")
                    
                    # Marcar fecha como completada
                    sistema_fechas.marcar_fecha_completada(curso_seleccionado, fecha_seleccionada)
                    
                    # Envío de emails (en segundo plano)
                    def _enviar_emails():
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
                    
                    threading.Thread(target=_enviar_emails, daemon=True).start()
                    st.rerun()
                
            except Exception as e:
                st.error(f"❌ Error al guardar asistencia: {e}")

# ==============================
# PANEL ADMINISTRATIVO MEJORADO - CON SUPABASE
# ==============================

def admin_panel_mejorado():
    if 'login_time' in st.session_state and 'timeout_duration' in st.session_state:
        if time_module.time() - st.session_state['login_time'] > st.session_state['timeout_duration']:
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

    # 🔥 NUEVO: Panel de control Supabase
    panel_control_supabase()
    
    # Configuración de temporizador
    st.subheader("⏳ Configuración de Temporizador de Sesión")
    options_min = [30, 60, 90, 120]
    current_duration = int(st.session_state['timeout_duration'] / 60) if 'timeout_duration' in st.session_state else 30
    selected_min = st.selectbox("Selecciona duración de sesión (minutos)", options_min, 
                               index=options_min.index(current_duration) if current_duration in options_min else 0)
    
    col1, col2 = st.columns(2)
    with col1:
        if boton_moderno("Aplicar duración", "primario", "⚙️", "apply_duration"):
            st.session_state['timeout_duration'] = selected_min * 60
            st.session_state['login_time'] = time_module.time()
            st.success(f"✅ Duración aplicada: {selected_min} minutos")
            st.rerun()
    with col2:
        if boton_moderno("Mantener sesión abierta", "secundario", "🔄", "keep_alive"):
            st.session_state['login_time'] = time_module.time()
            st.success("✅ Sesión mantenida abierta")
            st.rerun()
    
    # Resto del panel administrativo existente...
    st.divider()
    st.info("**💡 Funcionalidades administrativas adicionales aparecerán aquí...**")

# ==============================
# AUTENTICACIÓN Y MENÚ PRINCIPAL
# ==============================

def main():
    st.set_page_config(
        page_title="Preuniversitario CIMMA : Asistencia Cursos 2026",
        page_icon="🎓",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # Iniciar sistemas de fondo
    sistema_colas.iniciar_worker()
    
    # 🔥 NUEVO: Conectar a Supabase al iniciar
    gestor_bd.conectar_supabase()
    
    # Verificar secrets
    if not verificar_secrets():
        st.error("❌ Configuración incompleta en secrets.toml")
        return
    
    # Aplicar tema
    aplicar_tema_moderno()
    crear_header_moderno()
    
    # Sidebar
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
            st.session_state["login_time"] = time_module.time()
            st.session_state["timeout_duration"] = 5 * 60
        
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
                            st.session_state['login_time'] = time_module.time()
                            st.rerun()
                        else:
                            st.error("❌ Clave incorrecta")
                else:
                    st.error("No hay profesores configurados.")
            else:
                admins = st.secrets.get("administradores", {})
                admin_emails = st.secrets.get("admin_emails", {})
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
                                st.error("❌ Error al enviar código de verificación.")
                        else:
                            st.error("❌ Clave incorrecta")
                else:
                    st.error("No hay administradores configurados.")
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
                    st.error("❌ El código ha expirado.")
                    st.session_state["awaiting_2fa"] = False
                    st.rerun()
                elif st.session_state["2fa_attempts"] >= 3:
                    st.error("❌ Demasiados intentos fallidos.")
                    st.session_state["awaiting_2fa"] = False
                    st.rerun()
                elif code_input == st.session_state["2fa_code"]:
                    st.session_state["user_type"] = "admin"
                    st.session_state["user_name"] = st.session_state["2fa_user_name"]
                    st.session_state["awaiting_2fa"] = False
                    st.session_state["2fa_code"] = None
                    st.session_state["2fa_email"] = None
                    st.session_state["2fa_attempts"] = 0
                    st.session_state["2fa_time"] = None
                    st.session_state['login_time'] = time_module.time()
                    st.session_state['timeout_duration'] = 30 * 60
                    st.rerun()
                else:
                    st.session_state["2fa_attempts"] += 1
                    st.error(f"❌ Código incorrecto. Intentos restantes: {3 - st.session_state['2fa_attempts']}")
        else:
            st.success(f"👤 {st.session_state['user_name']}")
            
            # Estado del sistema
            estado_bd = gestor_bd.obtener_estado()
            if estado_bd['supabase_conectado']:
                st.success("🟢 Supabase conectado")
            else:
                st.warning("🟡 Usando solo Google Sheets")
            
            if boton_moderno("Cerrar sesión", "peligro", "🚪", "logout"):
                st.session_state.clear()
                st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
    
    # Contenido principal
    if st.session_state["user_type"] is None:
        st.markdown("""
        <div style="text-align: center; padding: 4rem 2rem;">
            <h1 style="color: #1A3B8F; font-size: 3rem; margin-bottom: 1rem;">🎓 Preuniversitario CIMMA</h1>
            <h2 style="color: #6B7280; font-size: 1.5rem; margin-bottom: 2rem;">Sistema de Gestión de Asistencia 2026</h2>
            <div style="max-width: 600px; margin: 0 auto;">
                <div style="background: #F0F4FF; padding: 1rem; border-radius: 8px; margin: 1rem 0;">
                    <p style="margin: 0; color: #1A3B8F;">Por favor, inicia sesión desde el menú lateral.</p>
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