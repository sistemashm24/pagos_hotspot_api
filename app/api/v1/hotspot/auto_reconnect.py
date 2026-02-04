# app/api/v1/hotspot_reconnect.py - VERSIÓN CORREGIDA
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
import asyncio
from typing import Dict, Any, Optional

from app.core.database import get_db
from app.core.auth import require_api_key
from app.core.mikrotik_api import MikrotikAPI

# Schema inline para evitar imports adicionales
from pydantic import BaseModel, Field

# Importar la función de auto-conexión que ya funciona
from app.hotspot.auto_conexion_pago_tarjeta import ejecutar_auto_conexion

from librouteros.query import Key

import traceback

router = APIRouter(tags=["Hotspot - Reconexión Automática"])

import re

MAC_REGEX = re.compile(
    r'^([0-9A-Fa-f]{2}[:\-]){5}([0-9A-Fa-f]{2})$'
)

def es_mac(valor: str) -> bool:
    """
    Detecta si el valor es una dirección MAC **con separadores obligatorios**.
    Solo acepta formatos con : o - (no cadenas continuas de hex).
    """
    if not valor:
        return False
    
    cleaned = valor.strip()
    
    # Primero: regex estricto (tu original) → requiere exactamente 5 separadores
    if MAC_REGEX.match(cleaned):
        return True
    
    # Segundo: versiones más flexibles pero **siempre con separadores**
    # Normalizamos a : y verificamos que haya al menos 5 separadores
    normalized = cleaned.upper().replace("-", ":").replace(".", ":")
    groups = re.findall(r'[0-9A-F]{2}', normalized)
    
    # Debe tener exactamente 6 grupos hex y al menos 5 separadores :
    if len(groups) == 6 and normalized.count(':') >= 5:
        return True
    
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

from librouteros.query import Key   # ← Asegúrate de tener este import en el archivo

def obtener_info_usuario_sync(
    host: str,
    port: int,
    user: str,
    password: str,
    hotspot_username: str
) -> Dict[str, Any]:
    """Obtiene información del usuario con consulta filtrada eficiente"""
    api = None
    try:
        api = MikrotikAPI(host, port, user, password, timeout=10)
        api.open()
        
        print(f"🔍 Buscando usuario específico: {hotspot_username}")
        
        name_key = Key('name')
        
        query = (
            api.connection
            .path('/ip/hotspot/user')
            .select(
                '.id', 'name', 'password', 'profile', 'disabled', 'comment',
                'limit-uptime', 'uptime','mac-address'  # puedes agregar más campos si los necesitas
            )
            .where(name_key == hotspot_username)
        )
        
        users_found = list(query)
        
        if not users_found:
            print(f"   → Usuario NO encontrado")
            return {
                "existe": False,
                "tipo_usuario": None,
                "password": "",
                "datos_usuario": None
            }
        
        usuario = users_found[0]
        
        raw_password = usuario.get('password', '')
        user_password = str(raw_password) if raw_password is not None else ""
        
        es_pin = user_password.strip() == ""
        
        print(f"   → Encontrado! Tipo: {'PIN' if es_pin else 'Usuario+Password'}")
        
        return {
            "existe": True,
            "tipo_usuario": "pin" if es_pin else "usuario_password",
            "password": user_password,
            "datos_usuario": dict(usuario),
            "disabled": usuario.get('disabled') == 'yes',
            "raw_password": raw_password
        }
        
    except Exception as e:
        print(f"💥 Error obteniendo información del usuario: {type(e).__name__}: {e}")
        return {
            "existe": False,
            "tipo_usuario": None,
            "password": "",
            "datos_usuario": None,
            "error": str(e)
        }
    finally:
        if api:
            try:
                api.close()
            except:
                pass

            
# ========== ENDPOINT PRINCIPAL MEJORADO ==========
@router.post(
    "/hotspot/auto-reconnect",
    summary="Reconexión automática para dispositivos con MAC aleatoria",
    response_model=AutoReconnectResponse
)
async def auto_reconnect(
    request: AutoReconnectRequest,
    auth_data=Depends(require_api_key),
    db: AsyncSession = Depends(get_db)
):
    print("\n" + "=" * 70)
    print("🔄 INICIANDO RECONEXIÓN AUTOMÁTICA")
    print("=" * 70)

    empresa, router_mikrotik, _ = auth_data

    response_base = {
        "success": False,
        "estado": "error",
        "auto_conexion": "no_conectado",
        "datos_sesion": None,
        "nueva_mac": request.current_mac,
        "mensaje": None,
        "error_detalle": None,
        "timestamp": datetime.utcnow().isoformat()
    }

    try:
        # ─────────────────────────────────────────────
        # 1. VALIDACIONES BÁSICAS
        # ─────────────────────────────────────────────
        if not getattr(empresa, "activa", True):
            response_base.update(
                estado="empresa_inactiva",
                mensaje="Empresa inactiva"
            )
            return response_base

        if not getattr(router_mikrotik, "activo", True):
            response_base.update(
                estado="router_inactivo",
                mensaje="Router inactivo"
            )
            return response_base


        # ─────────────────────────────────────────────
        # 1.1 BLOQUEO: username NO puede ser una MAC
        # ─────────────────────────────────────────────
        if es_mac(request.username):
            print(f"⛔ Username es una MAC con separadores ({request.username}) → rechazado")
            response_base.update(
                estado="expirado",
                mensaje="Usuario no encontrado"
            )
            return response_base


        # ─────────────────────────────────────────────
        # 2. OBTENER USUARIO DESDE MIKROTIK
        # ─────────────────────────────────────────────
        info_usuario = await asyncio.get_event_loop().run_in_executor(
            None,
            obtener_info_usuario_sync,
            router_mikrotik.host,
            router_mikrotik.puerto,
            router_mikrotik.usuario,
            router_mikrotik.password_encrypted,
            request.username
        )

        if not info_usuario.get("existe"):
            response_base.update(
                estado="expirado",
                mensaje="Usuario no encontrado"
            )
            return response_base

        datos_usuario = info_usuario["datos_usuario"]
        comment = (datos_usuario.get("comment") or "").upper()

        # ─────────────────────────────────────────────
        # USUARIO QUE SE USARÁ PARA LOGIN
        # ─────────────────────────────────────────────
        username_login = request.username

        # ─────────────────────────────────────────────
        # 3. LÓGICA ESPECIAL MODE / TL / TA
        # ─────────────────────────────────────────────
        if all(x in comment for x in ("MODE=", "TL=", "TA=")):
            print("⚠️ Usuario con parámetros especiales")

            api = None
            try:
                api = MikrotikAPI(
                    router_mikrotik.host,
                    router_mikrotik.puerto,
                    router_mikrotik.usuario,
                    router_mikrotik.password_encrypted,
                    timeout=10
                )
                api.open()

                # 3.1 Asignar MAC al usuario original (si no tiene)
                mac_actual = (datos_usuario.get("mac-address") or "").strip()

                if not mac_actual:
                    print("   • Usuario sin MAC → buscando cookie")

                    cookies = list(
                        api.connection
                        .path("/ip/hotspot/cookie")
                        .select("mac-address")
                        .where(Key("user") == request.username)
                    )

                    if cookies and cookies[0].get("mac-address"):
                        mac_cookie = cookies[0]["mac-address"].strip()
                        print(f"   • MAC cookie encontrada: {mac_cookie}")

                        api.connection.path("/ip/hotspot/user").update(
                            **{
                                ".id": datos_usuario[".id"],
                                "mac-address": mac_cookie
                            }
                        )

                # 3.2 ← LÓGICA FINAL: Reutilizar original o _RANDMACn (con límite)
                # ────────────────────────────────────────────────────────────────
                mac_normalized = request.current_mac.upper().strip().replace("-", ":").replace(".", ":")
                print(f"   [3.2 OPTIMIZED] Verificando MAC {request.current_mac} → normalizada: {mac_normalized} "
                      f"para usuario base '{request.username}'")

                username_login = request.username  # valor por defecto

                # 1. Checar si coincide con el usuario original (normalizado)
                mac_original_raw = (datos_usuario.get("mac-address") or "").strip()
                mac_original = mac_original_raw.upper().replace("-", ":").replace(".", ":")
                if mac_original == mac_normalized:
                    print(f"   • MAC coincide con usuario ORIGINAL → reutilizando {request.username}")
                else:
                    # 2. UNA SOLA CONSULTA: todos los usuarios con esta MAC (normalizada)
                    usuarios_con_mac = list(
                        api.connection
                        .path("/ip/hotspot/user")
                        .select(".id", "name", "mac-address")
                        .where(Key("mac-address") == mac_normalized)  # ← normalizada
                    )

                    found_randmac = None
                    max_ext = 0
                    base_prefix = f"{request.username}_RANDMAC"
                    MAX_RANDMAC = 15

                    # Procesamos los resultados en Python (normalmente 0 o 1 resultado)
                    for u in usuarios_con_mac:
                        name = u.get("name", "").strip()
                        if name.startswith(base_prefix):
                            try:
                                ext_num = int(name[len(base_prefix):])
                                max_ext = max(max_ext, ext_num)
                                found_randmac = name
                                username_login = name
                                print(f"   • MAC encontrada en {name} (ext {ext_num}) → reutilizando")
                                break  # Podemos romper aquí si solo esperamos uno
                            except ValueError:
                                continue

                    if found_randmac:
                        print(f"   • Reutilizando _RANDMAC encontrado: {username_login}")
                    else:
                        # No encontramos → creamos en el siguiente número después del máximo
                        next_ext = max_ext + 1
                        if next_ext > MAX_RANDMAC:
                            print(f"   • Límite de {MAX_RANDMAC} _RANDMAC alcanzado → "
                                  f"fallback a original: {request.username}")
                            # username_login ya es request.username
                        else:
                            copy_name = f"{request.username}_RANDMAC{next_ext}"
                            print(f"   • No encontrada → creando {copy_name}")

                            api.connection.path("/ip/hotspot/user").add(
                                name=copy_name,
                                password=info_usuario["password"],
                                profile=datos_usuario.get("profile", "default"),
                                comment=datos_usuario.get("comment", ""),
                                disabled="no"
                            )

                            nuevo = list(
                                api.connection
                                .path("/ip/hotspot/user")
                                .select(".id")
                                .where(Key("name") == copy_name)
                            )

                            if nuevo:
                                api.connection.path("/ip/hotspot/user").update(
                                    **{
                                        ".id": nuevo[0][".id"],
                                        "mac-address": request.current_mac
                                    }
                                )
                                print(f"   • MAC {request.current_mac} asignada a {copy_name}")
                                username_login = copy_name
                            else:
                                print("   • Falló obtener/crear nuevo usuario → fallback original")
                            # username_login ya es request.username

            except Exception as e:
                print("💥 Error en lógica especial:", str(e))
                traceback.print_exc()
            finally:
                if api:
                    api.close()

        # ─────────────────────────────────────────────
        # 4. FLUJO ORIGINAL (SE MANTIENE)
        # ─────────────────────────────────────────────
        password_a_usar = (
            "" if info_usuario["tipo_usuario"] == "pin"
            else info_usuario["password"]
        )

        resultado = await ejecutar_auto_conexion(
            router_host=router_mikrotik.host,
            router_port=router_mikrotik.puerto,
            router_user=router_mikrotik.usuario,
            router_password=router_mikrotik.password_encrypted,
            username=username_login,  # ✅ ORIGINAL o _EXTn
            password=password_a_usar,
            mac_address=request.current_mac,
            ip_address=request.current_ip
        )

        response_base.update(
            success=resultado.get("success", False),
            estado="activo",
            auto_conexion="conectado" if resultado.get("conectado") else "no_conectado",
            mensaje=resultado.get("mensaje"),
            error_detalle=resultado.get("error"),
            datos_sesion=resultado.get("session_info", datos_usuario)
        )

        return response_base

    except Exception as e:
        print("💥 ERROR GENERAL:", str(e))
        traceback.print_exc()
        response_base.update(
            mensaje="Error interno del servidor",
            error_detalle=str(e)
        )
        return response_base




# ──────────────────────────────────────────────────────────────────────────────
#                  ENDPOINT: Consulta SEGURA de perfil de usuario hotspot
# ──────────────────────────────────────────────────────────────────────────────

from librouteros.query import Key   # ← ¡IMPORTANTE! No olvides esta línea

class UserProfileRequest(BaseModel):
    username: str = Field(..., description="Nombre de usuario hotspot")
    password: Optional[str] = Field(None, description="Contraseña (opcional solo para usuarios PIN)")

class UserProfileResponse(BaseModel):
    success: bool
    estado: str
    username: str
    tipo_usuario: Optional[str] = None               # "pin" o "usuario_contrasena"
    profile: Optional[str] = None
    mac_cookie_timeout: Optional[str] = None
    mac_authentication: Optional[bool] = None
    disabled: Optional[bool] = None
    comment: Optional[str] = None
    limit_uptime: Optional[str] = None               # ← Campo independiente
    datos_completos: Optional[Dict[str, Any]] = None
    mensaje: Optional[str] = None
    error_detalle: Optional[str] = None
    timestamp: str


def verificar_perfil_seguro_sync(
    host: str,
    port: int,
    api_user: str,
    api_password: str,
    hotspot_username: str,
    provided_password: Optional[str] = None
) -> Dict[str, Any]:
    """
    Consulta segura y eficiente del perfil de usuario hotspot
    Reglas:
    - PIN: solo se permite si NO se envía password
    - Usuario con contraseña: requiere password exacta
    """
    api = None
    try:
        api = MikrotikAPI(host, port, api_user, api_password, timeout=10)
        api.open()
        
        print(f"🔍 [EFICIENTE] Buscando usuario exacto: {hotspot_username}")
        
        name_key = Key('name')
        
        # Consulta filtrada: solo el usuario que necesitamos
        query = (
            api.connection
            .path('/ip/hotspot/user')
            .select(
                '.id', 'name', 'password', 'profile', 'disabled', 'comment',
                'limit-uptime'          # ← Necesario para el campo independiente
            )
            .where(name_key == hotspot_username)
        )
        
        users_found = list(query)
        
        if not users_found:
            print(f"❌ Usuario '{hotspot_username}' NO encontrado en hotspot users")
            return {"valido": False, "razon": "credenciales_invalidas"}
        
        usuario = users_found[0]
        
        # Determinar tipo de usuario
        stored_pass_raw = usuario.get("password", "")
        stored_pass = str(stored_pass_raw).strip() if stored_pass_raw is not None else ""
        es_pin = len(stored_pass) == 0
        
        print(f"   • Tipo detectado: {'PIN (vacío)' if es_pin else 'Usuario con contraseña'}")
        
        # ── REGLAS DE VALIDACIÓN SEGURA ─────────────────────────────────────
        if provided_password is not None:
            # Se envió contraseña
            if es_pin:
                print("❌ PIN no debe recibir contraseña")
                return {"valido": False, "razon": "credenciales_invalidas"}
            else:
                if stored_pass == provided_password:
                    print("✅ Contraseña correcta")
                else:
                    print("❌ Contraseña incorrecta")
                    return {"valido": False, "razon": "credenciales_invalidas"}
        else:
            # NO se envió contraseña
            if es_pin:
                print("✅ PIN autorizado sin contraseña")
            else:
                print("❌ Usuario con contraseña requiere password")
                return {"valido": False, "razon": "credenciales_invalidas"}
        # ─────────────────────────────────────────────────────────────────────
        
        # Obtener datos del perfil
        profile_name = usuario.get("profile", "default")
        profile_query = (
            api.connection
            .path('/ip/hotspot/user/profile')
            .select('name', 'mac-cookie-timeout', 'mac-authentication')
            .where(Key('name') == profile_name)
        )
        profiles = list(profile_query)
        perfil = profiles[0] if profiles else {}
        
        return {
            "valido": True,
            "es_pin": es_pin,
            "tipo_usuario": "pin" if es_pin else "usuario_contrasena",
            "username": hotspot_username,
            "profile": profile_name,
            "mac_cookie_timeout": perfil.get("mac-cookie-timeout"),
            "mac_authentication": perfil.get("mac-authentication", "no") == "yes",
            "disabled": usuario.get("disabled", "no") == "yes",
            "comment": usuario.get("comment", ""),
            "limit_uptime": usuario.get("limit-uptime"),           # ← Campo independiente
            "datos_usuario": dict(usuario),
            "datos_perfil": dict(perfil)
        }
        
    except Exception as e:
        print(f"💥 Error en consulta segura: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        return {"valido": False, "razon": "error_interno"}
    finally:
        if api:
            try:
                api.close()
            except:
                pass


@router.post("/hotspot/user/profile-info",
    summary="🔐 Consulta SEGURA y EFICIENTE del perfil hotspot",
    description="Devuelve datos del usuario solo si las credenciales son correctas según tipo (PIN o contraseña)",
    response_model=UserProfileResponse
)
async def get_user_hotspot_profile(
    request: UserProfileRequest,
    auth_data = Depends(require_api_key),
    db: AsyncSession = Depends(get_db)
):
    print("\n" + "="*80)
    print(f"🔐 CONSULTA SEGURA PERFIL - {request.username} | password: {'SÍ' if request.password else 'NO'}")
    print("="*80)
    
    empresa, router_mikrotik, _ = auth_data
    
    response_base = {
        "success": False,
        "estado": "error",
        "username": request.username,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    try:
        # Validaciones de empresa y router
        if not getattr(empresa, 'activa', True):
            print("❌ Empresa inactiva")
            return {**response_base, "estado": "empresa_inactiva", "mensaje": "Empresa inactiva"}
        
        if not getattr(router_mikrotik, 'activo', True):
            print("❌ Router inactivo")
            return {**response_base, "estado": "router_inactivo", "mensaje": "Router inactivo"}
        
        # Consulta segura y eficiente
        info = await asyncio.get_event_loop().run_in_executor(
            None,
            verificar_perfil_seguro_sync,
            router_mikrotik.host,
            router_mikrotik.puerto,
            router_mikrotik.usuario,
            router_mikrotik.password_encrypted,
            request.username,
            request.password
        )
        
        if not info.get("valido"):
            print("🚫 Credenciales rechazadas o error")
            return {**response_base,
                   "estado": "credenciales_invalidas",
                   "mensaje": "Credenciales incorrectas o no autorizado",
                   "error_detalle": "credenciales_invalidas"}
        
        # ÉXITO
        print("✅ Perfil autorizado correctamente")
        print(f"   • Tipo: {info['tipo_usuario']}")
        print(f"   • Perfil: {info['profile']}")
        print(f"   • Limit Uptime: {info.get('limit_uptime') or 'Sin límite'}")
        
        return {**response_base,
               "success": True,
               "estado": "ok",
               "tipo_usuario": info["tipo_usuario"],
               "profile": info["profile"],
               "mac_cookie_timeout": info["mac_cookie_timeout"],
               "mac_authentication": info["mac_authentication"],
               "disabled": info["disabled"],
               "comment": info["comment"],
               "limit_uptime": info["limit_uptime"],               # ← Visible y directo
               "datos_completos": info["datos_usuario"]}
    
    except Exception as e:
        print(f"💥 ERROR CRÍTICO en endpoint: {str(e)}")
        import traceback
        traceback.print_exc()
        return {**response_base,
               "mensaje": "Error interno del servidor",
               "error_detalle": str(e)}


# ──────────────────────────────────────────────────────────────────────────────
#          VALIDACIÓN LIGERA DE CONEXIÓN REAL AL ROUTER (SOLO LECTURA)
# ──────────────────────────────────────────────────────────────────────────────

class RouterValidateResponse(BaseModel):
    success: bool
    estado: str
    mensaje: Optional[str] = None
    error_detalle: Optional[str] = None
    conexion_ok: bool = False
    timestamp: str


@router.post("/routers/validar-empresa-router",
    summary="Validar conexión real al router (solo consulta)",
    description="""
        Valida la conectividad real con el router MikroTik mediante una prueba mínima
        de conexión (open / close).

        🔹 **No realiza cambios en la base de datos**
        🔹 **No ejecuta comandos de configuración**
        🔹 **Operación de solo lectura, rápida y segura**

        Resultado de la validación:
        - ✔️ Conexión exitosa → `estado = "activo"`
        - ❌ Conexión fallida → `estado = "router_inactivo"`

        Ideal para monitoreo, diagnósticos rápidos y verificación de disponibilidad
        del router en tiempo real.
        """,
    response_model=RouterValidateResponse
)
async def validar_conexion_router(
    auth_data = Depends(require_api_key),
    db: AsyncSession = Depends(get_db)  # se mantiene por compatibilidad, pero no se usa
):
    print("\n" + "="*70)
    print("🔍 VALIDACIÓN DE CONEXIÓN REAL AL ROUTER (SOLO LECTURA)")
    print("="*70)
    
    empresa, router_mikrotik, _ = auth_data
    
    response_base = {
        "success": False,
        "estado": "error",
        "mensaje": None,
        "error_detalle": None,
        "conexion_ok": False,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    try:
        # Validación empresa (consistente con otros endpoints)
        if not getattr(empresa, 'activa', True):
            print("❌ Empresa inactiva")
            return {**response_base,
                   "estado": "empresa_inactiva",
                   "mensaje": "La empresa no se encuentra activa",
                   "error_detalle": "empresa_inactiva"}
        
        # Verificamos que exista router asociado
        if not router_mikrotik:
            print("❌ No hay router asociado")
            return {**response_base,
                   "estado": "sin_routers",
                   "mensaje": "No se encontró router asociado",
                   "error_detalle": "sin_router_asociado"}
        
        print(f"Intentando conexión ligera a {router_mikrotik.host}:{router_mikrotik.puerto}...")
        
        # Prueba mínima de conexión (solo open/close)
        conexion_exitosa = False
        try:
            api = MikrotikAPI(
                router_mikrotik.host,               # ip
                router_mikrotik.puerto,             # port
                router_mikrotik.usuario,            # username
                router_mikrotik.password_encrypted, # password
                timeout=5
            )
            api.open()
            api.close()
            conexion_exitosa = True
            print("✅ Conexión exitosa → router en línea")
        except Exception as conn_err:
            print(f"❌ Falló conexión: {str(conn_err)}")
            conexion_exitosa = False
        
        # Respuesta final - solo lectura, sin modificar nada en BD
        if conexion_exitosa:
            return {**response_base,
                   "success": True,
                   "estado": "activo",
                   "mensaje": "Router en línea y responde correctamente",
                   "conexion_ok": True}
        else:
            return {**response_base,
                   "estado": "router_inactivo",
                   "mensaje": "El router no está en línea (conexión fallida)",
                   "error_detalle": "router_inactivo",
                   "conexion_ok": False}
    
    except Exception as e:
        print(f"💥 ERROR INESPERADO: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        
        return {**response_base,
               "estado": "internal_error",
               "mensaje": "Error interno al validar conexión",
               "error_detalle": "internal_error"}