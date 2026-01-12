# app/api/v1/hotspot_reconnect.py - VERSIÓN FINAL
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
import time
import asyncio
from typing import Dict, Any, Optional

from app.core.database import get_db
from app.core.auth import require_api_key  # ← USAR ESTA
from app.core.mikrotik_api import MikrotikAPI

# Schema inline para evitar imports adicionales
from pydantic import BaseModel, Field

router = APIRouter(tags=["Hotspot - Reconexión Automática"])

# ========== SCHEMAS ==========
class AutoReconnectRequest(BaseModel):
    username: str = Field(..., description="Usuario hotspot guardado en localStorage")
    password: str = Field("", description="Contraseña (puede estar vacía para usuarios PIN)")
    stored_mac: Optional[str] = Field(None, description="MAC anterior guardada en localStorage")
    current_mac: str = Field(..., description="Nueva MAC actual del dispositivo")
    current_ip: Optional[str] = Field(None, description="IP actual del dispositivo")
    current_ssid: Optional[str] = Field(None, description="SSID actual de conexión")

class AutoReconnectResponse(BaseModel):
    success: bool
    estado: str
    auto_conexion: str
    datos_sesion: Optional[dict] = None
    nueva_mac: Optional[str] = None
    tiempo_acumulado: Optional[str] = None
    tiempo_restante: Optional[str] = None
    primera_sesion: Optional[str] = None
    mensaje: Optional[str] = None
    error_detalle: Optional[str] = None
    timestamp: str

# ========== FUNCIÓN SÍNCRONA PARA MIKROTIK ==========
def process_reconnection_sync(
    host: str,
    port: int,
    user: str,
    password: str,
    hotspot_username: str,
    hotspot_password: str,
    nueva_mac: str,
    current_ip: str = None
) -> Dict[str, Any]:
    """Procesamiento síncrono de reconexión en MikroTik"""
    api = None
    try:
        api = MikrotikAPI(host, port, user, password, timeout=10)
        api.open()
        
        print(f"✅ Conexión a MikroTik establecida: {host}:{port}")
        
        # Respuesta base
        response = {
            "success": False,
            "estado": "error",
            "auto_conexion": "no_conectado",
            "datos_sesion": None,
            "tiempo_acumulado": None,
            "tiempo_restante": None,
            "primera_sesion": None,
            "mensaje": None,
            "error_detalle": None
        }
        
        # 1. BUSCAR USUARIO EN MIKROTIK
        print(f"🔍 Buscando usuario: {hotspot_username}")
        all_users = list(api.connection(cmd="/ip/hotspot/user/print"))
        
        usuario_encontrado = None
        for u in all_users:
            if u.get('name') == hotspot_username:
                usuario_encontrado = u
                print(f"✅ Usuario encontrado")
                print(f"   • Perfil: {u.get('profile')}")
                print(f"   • Estado: {'activo' if u.get('disabled') == 'no' else 'inactivo'}")
                print(f"   • MAC: {u.get('mac-address')}")
                break
        
        # 2. SI USUARIO NO EXISTE → EXPIRADO
        if not usuario_encontrado:
            print(f"❌ Usuario no encontrado en MikroTik")
            response.update({
                "estado": "expirado",
                "mensaje": "Usuario no encontrado (probablemente expiró)",
                "error_detalle": "user_not_found"
            })
            return response
        
        # 3. USUARIO EXISTE → ESTADO "ACTIVO"
        response["estado"] = "activo"
        
        # 4. EXTRAER DATOS DEL USUARIO
        datos_usuario = dict(usuario_encontrado)
        response["datos_sesion"] = datos_usuario
        response["tiempo_acumulado"] = datos_usuario.get("uptime")
        
        # Extraer primera sesión de comment si existe
        comment = datos_usuario.get("comment", "")
        if "Primera:" in comment:
            primera_parte = comment.split("Primera:")[1].strip().split()[0]
            response["primera_sesion"] = primera_parte
        elif "|" in comment:
            partes = comment.split("|")
            if len(partes) > 1:
                response["primera_sesion"] = partes[1].strip()
        
        # 5. VERIFICAR SI USUARIO ESTÁ ACTIVO
        if datos_usuario.get("disabled") == "yes":
            print(f"⚠️ Usuario deshabilitado en MikroTik")
            response.update({
                "auto_conexion": "no_conectado",
                "mensaje": "Usuario deshabilitado",
                "error_detalle": "user_disabled"
            })
            return response
        
        # 6. BUSCAR Y ELIMINAR SESIÓN ACTIVA ANTERIOR
        print(f"🔍 Buscando sesiones activas...")
        active_sessions = list(api.connection(cmd="/ip/hotspot/active/print"))
        
        sesion_anterior_id = None
        for session in active_sessions:
            if session.get("user") == hotspot_username:
                sesion_anterior_id = session.get(".id")
                print(f"⚠️ Sesión anterior encontrada: ID={sesion_anterior_id}")
                break
        
        if sesion_anterior_id:
            print(f"🗑️ Eliminando sesión anterior...")
            try:
                api.connection(cmd="/ip/hotspot/active/remove", numbers=sesion_anterior_id)
                print(f"✅ Sesión anterior eliminada")
                
                # Eliminar cookie si existe
                cookies = list(api.connection(cmd="/ip/hotspot/cookie/print"))
                for cookie in cookies:
                    if cookie.get("user") == hotspot_username:
                        api.connection(cmd="/ip/hotspot/cookie/remove", numbers=cookie.get(".id"))
                        print(f"✅ Cookie eliminada")
                        break
                        
            except Exception as e:
                print(f"⚠️ Error eliminando sesión: {e}")
        
        # 7. ACTUALIZAR MAC DEL USUARIO SI ES DIFERENTE
        mac_actual = datos_usuario.get("mac-address")
        if mac_actual and mac_actual.lower() != nueva_mac.lower():
            print(f"🔄 Actualizando MAC: {mac_actual} → {nueva_mac}")
            try:
                user_id = datos_usuario.get(".id")
                api.connection(
                    cmd="/ip/hotspot/user/set",
                    numbers=user_id,
                    **{"mac-address": nueva_mac}
                )
                print(f"✅ MAC actualizada")
            except Exception as e:
                print(f"⚠️ Error actualizando MAC: {e}")
        
        # 8. INTENTAR AUTENTICAR CON NUEVA MAC
        print(f"🔐 Intentando autenticar con MAC: {nueva_mac}")
        
        auth_params = {
            "user": hotspot_username,
            "mac-address": nueva_mac,
            "ip": current_ip if current_ip else "auto"
        }
        
        # Solo agregar password si no está vacío (para PIN)
        if hotspot_password:
            auth_params["password"] = hotspot_password
        
        try:
            # Intentar autenticación
            auth_result = api.connection(cmd="/ip/hotspot/active/login", **auth_params)
            list(auth_result)  # Consumir el generador
            
            print(f"✅✅✅ Autenticación exitosa")
            
            response.update({
                "success": True,
                "auto_conexion": "conectado",
                "mensaje": "Autenticación exitosa"
            })
            
            # 9. VERIFICAR QUE LA SESIÓN SE CREÓ
            time.sleep(0.5)
            active_sessions = list(api.connection(cmd="/ip/hotspot/active/print"))
            
            for session in active_sessions:
                if session.get("user") == hotspot_username:
                    print(f"✅✅✅ Sesión verificada en activas")
                    print(f"   • IP: {session.get('address')}")
                    print(f"   • Uptime: {session.get('uptime')}")
                    break
                    
        except Exception as auth_error:
            print(f"❌ Error en autenticación: {auth_error}")
            
            # Determinar tipo de error
            error_str = str(auth_error).lower()
            
            if "already logged in" in error_str:
                error_detalle = "already_logged_in"
                mensaje = "El usuario ya tiene una sesión activa"
            elif "invalid" in error_str or "wrong" in error_str:
                error_detalle = "invalid_credentials"
                mensaje = "Credenciales inválidas"
            elif "limit" in error_str:
                error_detalle = "limit_reached"
                mensaje = "Límite alcanzado"
            else:
                error_detalle = "auth_failed"
                mensaje = "Error de autenticación"
            
            response.update({
                "auto_conexion": "no_conectado",
                "mensaje": mensaje,
                "error_detalle": error_detalle
            })
        
        return response
        
    except Exception as e:
        print(f"💥 Error de conexión a MikroTik: {type(e).__name__}: {str(e)}")
        
        # Determinar tipo de error
        error_str = str(e).lower()
        
        if "timeout" in error_str or "connection" in error_str:
            error_detalle = "router_no_conectado"
            mensaje = "No se pudo conectar al router"
        elif "login" in error_str or "password" in error_str:
            error_detalle = "router_auth_failed"
            mensaje = "Error de autenticación con el router"
        else:
            error_detalle = "mikrotik_error"
            mensaje = f"Error de MikroTik: {str(e)}"
        
        return {
            "success": False,
            "estado": "error",
            "auto_conexion": "no_conectado",
            "datos_sesion": None,
            "tiempo_acumulado": None,
            "tiempo_restante": None,
            "primera_sesion": None,
            "mensaje": mensaje,
            "error_detalle": error_detalle
        }
        
    finally:
        if api:
            try:
                api.close()
                print(f"🔌 Conexión cerrada")
            except:
                pass

# ========== ENDPOINT PRINCIPAL ==========
@router.post("/hotspot/auto-reconnect", 
    summary="Reconexión automática para dispositivos con MAC aleatoria",
    description="""Sistema de reconexión automática cuando dispositivos cambian de MAC al cambiar entre SSIDs.""",
    response_model=AutoReconnectResponse
)
async def auto_reconnect(
    request: AutoReconnectRequest,
    auth_data = Depends(require_api_key),  # ← AQUÍ USA require_api_key
    db: AsyncSession = Depends(get_db)
):
    """
    Reconectar automáticamente un usuario cuando cambia su MAC
    """
    print("\n" + "="*70)
    print("🔄 INICIANDO RECONEXIÓN AUTOMÁTICA")
    print("="*70)
    
    # require_api_key retorna: (empresa, router, auth_info)
    empresa, router_mikrotik, auth_info = auth_data
    
    print(f"🏢 Empresa: {empresa.nombre} ({empresa.id})")
    print(f"🌐 Router: {router_mikrotik.host}:{router_mikrotik.puerto}")
    print(f"👤 Usuario: {request.username}")
    print(f"🔑 Tipo: {'PIN' if not request.password else 'Usuario/Contraseña'}")
    print(f"📶 MAC nueva: {request.current_mac}")
    print(f"🌐 IP: {request.current_ip or 'No especificada'}")
    
    # Respuesta base
    response_base = {
        "success": False,
        "estado": "error",
        "auto_conexion": "no_conectado",
        "datos_sesion": None,
        "nueva_mac": request.current_mac,
        "tiempo_acumulado": None,
        "tiempo_restante": None,
        "primera_sesion": None,
        "mensaje": None,
        "error_detalle": None,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    try:
        # Procesar reconexión usando executor para operaciones síncronas
        mikrotik_data = await asyncio.get_event_loop().run_in_executor(
            None,
            process_reconnection_sync,
            router_mikrotik.host,
            router_mikrotik.puerto,
            router_mikrotik.usuario,
            router_mikrotik.password_encrypted,
            request.username,
            request.password,
            request.current_mac,
            request.current_ip
        )
        
        # Actualizar respuesta con datos de MikroTik
        response_base.update({
            "success": mikrotik_data.get("success", False),
            "estado": mikrotik_data.get("estado", "error"),
            "auto_conexion": mikrotik_data.get("auto_conexion", "no_conectado"),
            "datos_sesion": mikrotik_data.get("datos_sesion"),
            "tiempo_acumulado": mikrotik_data.get("tiempo_acumulado"),
            "tiempo_restante": mikrotik_data.get("tiempo_restante"),
            "primera_sesion": mikrotik_data.get("primera_sesion"),
            "mensaje": mikrotik_data.get("mensaje"),
            "error_detalle": mikrotik_data.get("error_detalle")
        })
        
        # Logs finales
        if response_base["estado"] == "activo":
            if response_base["auto_conexion"] == "conectado":
                print(f"✅✅✅ RECONEXIÓN EXITOSA")
            else:
                print(f"⚠️ USUARIO ACTIVO PERO NO CONECTÓ")
                print(f"   • Error: {response_base['error_detalle']}")
        elif response_base["estado"] == "expirado":
            print(f"❌ USUARIO EXPIRADO/NO EXISTE")
        else:
            print(f"💥 ERROR TÉCNICO")
            print(f"   • Detalle: {response_base['error_detalle']}")
        
        print("\n" + "="*70)
        print("🏁 PROCESO COMPLETADO")
        print("="*70)
        
        return response_base
        
    except HTTPException as http_exc:
        # Re-lanzar excepciones HTTP
        raise http_exc
        
    except Exception as e:
        print(f"\n💥 ERROR INESPERADO: {type(e).__name__}: {str(e)}")
        
        response_base.update({
            "mensaje": "Error interno del servidor",
            "error_detalle": "server_error"
        })
        
        return response_base