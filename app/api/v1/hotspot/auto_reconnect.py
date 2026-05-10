# app/api/v1/hotspot_reconnect.py - VERSIÓN CORREGIDA FINAL (DETECCIÓN AUTOMÁTICA)
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
import asyncio
from typing import Dict, Any, Optional
import re
import traceback
from pydantic import BaseModel, Field

from app.core.database import get_db
from app.core.auth import require_api_key
from app.core.mikrotik_api import MikrotikAPI
from app.hotspot.auto_conexion_pago_tarjeta import ejecutar_auto_conexion
from librouteros.query import Key

router = APIRouter(tags=["Hotspot - Reconexión Automática"])

MAC_REGEX = re.compile(r'^([0-9A-Fa-f]{2}[:\-]){5}([0-9A-Fa-f]{2})$')

def es_mac(valor: str) -> bool:
    if not valor: return False
    cleaned = valor.strip()
    if MAC_REGEX.match(cleaned): return True
    normalized = cleaned.upper().replace("-", ":").replace(".", ":")
    groups = re.findall(r'[0-9A-F]{2}', normalized)
    if len(groups) == 6 and normalized.count(':') >= 5: return True
    return False

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

def obtener_info_usuario_api(api: MikrotikAPI, hotspot_username: str):
    """Obtiene info de usuario usando una conexión ya abierta"""
    try:
        query = (api.connection.path('/ip/hotspot/user')
                .select('.id', 'name', 'password', 'profile', 'disabled', 'comment', 'limit-uptime', 'uptime','mac-address')
                .where(Key('name') == hotspot_username))
        users_found = list(query)
        if not users_found: return {"existe": False}
        usuario = users_found[0]
        raw_password = usuario.get('password', '')
        user_password = str(raw_password) if raw_password is not None else ""
        return {
            "existe": True,
            "tipo_usuario": "pin" if user_password.strip() == "" else "usuario_password",
            "password": user_password,
            "datos_usuario": dict(usuario),
            "disabled": usuario.get('disabled') == 'yes'
        }
    except Exception as e:
        print(f"💥 Error obteniendo info via API: {e}")
        return {"existe": False, "error": str(e)}

def obtener_info_usuario_sync(host, port, user, password, hotspot_username):
    """Versión legacy para compatibilidad si se usa fuera de un contexto con API abierta"""
    with MikrotikAPI(host, port, user, password, timeout=10) as api:
        return obtener_info_usuario_api(api, hotspot_username)

@router.post("/hotspot/auto-reconnect", response_model=AutoReconnectResponse)
async def auto_reconnect(request: AutoReconnectRequest, auth_data=Depends(require_api_key), db: AsyncSession = Depends(get_db)):
    from urllib.parse import unquote
    
    # Decodificar por si vienen de URL
    request.username = unquote(request.username)
    request.current_mac = unquote(request.current_mac)
    
    print(f"\n🔄 RECONEXIÓN: {request.username} | MAC: {request.current_mac}")
    empresa, router_mikrotik, _ = auth_data
    response_base = {
        "success": False, "estado": "error", "auto_conexion": "no_conectado",
        "datos_sesion": None, "nueva_mac": request.current_mac, "mensaje": None,
        "error_detalle": None, "timestamp": datetime.utcnow().isoformat()
    }

    api = None
    try:
        if not getattr(empresa, "activa", True): return {**response_base, "estado": "empresa_inactiva"}
        if not getattr(router_mikrotik, "activo", True): return {**response_base, "estado": "router_inactivo"}
        if es_mac(request.username): return {**response_base, "estado": "expirado"}

        # --- UNA SOLA CONEXIÓN PARA TODO ---
        api = MikrotikAPI(router_mikrotik.host, router_mikrotik.puerto, router_mikrotik.usuario, router_mikrotik.password_encrypted, timeout=15)
        api.open()

        # 1. Obtener Usuario Base
        base_username = re.sub(r'_RANDMAC\d+$', '', request.username)
        info_usuario = obtener_info_usuario_api(api, base_username)

        if not info_usuario.get("existe"):
            return {**response_base, "estado": "expirado", "mensaje": "Usuario no encontrado"}

        datos_usuario = info_usuario["datos_usuario"]
        comment_original = (datos_usuario.get("comment") or "").upper()
        username_login = datos_usuario.get("name") or base_username

        # 2. Lógica RANDMAC (usando la misma conexión)
        if all(x in comment_original for x in ("MODE=", "TL=", "TA=")):
            try:
                mac_normalized = request.current_mac.upper().strip().replace("-", ":").replace(".", ":")
                
                # Buscar clones por comentario
                siblings = list(api.connection.path("/ip/hotspot/user").select(".id", "name", "mac-address").where(Key("comment") == datos_usuario.get("comment", "")))
                found_match = None
                max_ext = 0
                base_prefix = f"{base_username}_RANDMAC"

                for s in siblings:
                    name = s.get("name", "").strip()
                    s_mac = (s.get("mac-address") or "").upper().replace("-", ":").replace(".", ":")
                    if name == base_username or name.startswith(base_prefix):
                        if s_mac == mac_normalized:
                            found_match = name
                            break
                        if name.startswith(base_prefix):
                            try: max_ext = max(max_ext, int(name[len(base_prefix):]))
                            except: pass

                if found_match:
                    username_login = found_match
                else:
                    # Crear nuevo clon
                    next_ext = max_ext + 1
                    if next_ext <= 15:
                        copy_name = f"{base_username}_RANDMAC{next_ext}"
                        try:
                            api.connection.path("/ip/hotspot/user").add(name=copy_name, password=info_usuario["password"] or "", 
                                profile=datos_usuario.get("profile", "default"), comment=datos_usuario.get("comment", ""),
                                **{"mac-address": mac_normalized, "disabled": "no"})
                            username_login = copy_name
                        except:
                            api.connection.path("/ip/hotspot/user").add(name=copy_name, password=info_usuario["password"] or "", 
                                profile=datos_usuario.get("profile", "default"), comment=datos_usuario.get("comment", ""), disabled="no")
                            nuevo = list(api.connection.path("/ip/hotspot/user").select(".id").where(Key("name") == copy_name))
                            if nuevo: api.connection.path("/ip/hotspot/user").update(**{".id": nuevo[0][".id"], "mac-address": mac_normalized})
                            username_login = copy_name

                # 3. SEMBRAR COOKIE MANUAL (usando la misma conexión)
                try:
                    viejas = list(api.connection.path("/ip/hotspot/cookie").select(".id").where(Key("mac-address") == mac_normalized))
                    for v in viejas: api.connection.path("/ip/hotspot/cookie").remove(**{".id": v[".id"]})
                    api.connection.path("/ip/hotspot/cookie").add(user=username_login, **{"mac-address": mac_normalized, "ip-address": request.current_ip, "expires": "3d 00:00:00"})
                    print(f"   🍪 Cookie manual sembrada para {username_login}")
                except: pass
            except Exception as e: print(f"💥 Error RANDMAC optimizado: {e}")

        # 4. DETECTAR VERSIÓN (reutilizando conexión)
        major_version = 6
        try:
            res = api.connection(cmd="/system/resource/print")
            version_str = next(iter(res)).get("version", "6.48").strip()
            major_version = int(version_str.split(".")[0])
        except: pass

        # 5. EJECUTAR CONEXIÓN (reutilizando conexión y versión)
        resultado = await ejecutar_auto_conexion(
            router_host=router_mikrotik.host, router_port=router_mikrotik.puerto,
            router_user=router_mikrotik.usuario, router_password=router_mikrotik.password_encrypted,
            username=username_login, password="" if info_usuario["tipo_usuario"] == "pin" else info_usuario["password"],
            mac_address=request.current_mac, ip_address=request.current_ip,
            api_instance=api, major_version=major_version
        )

        response_base.update(
            success=resultado.get("success", False),
            estado="activo",
            auto_conexion="conectado" if resultado.get("conectado") else "no_conectado",
            mensaje=resultado.get("mensaje"),
            datos_sesion=resultado.get("session_info", datos_usuario)
        )
        return response_base

    except Exception as e:
        traceback.print_exc()
        return {**response_base, "mensaje": "Error interno de reconexión", "error_detalle": str(e)}
    finally:
        if api: api.close()

# ========== PERFIL INFO ENDPOINT ==========
class UserProfileRequest(BaseModel):
    username: str
    password: Optional[str] = None

@router.post("/hotspot/user/profile-info")
async def get_user_hotspot_profile(request: UserProfileRequest, auth_data = Depends(require_api_key)):
    empresa, router_mikrotik, _ = auth_data
    return {"success": True, "estado": "ok", "username": request.username, "timestamp": datetime.utcnow().isoformat()}