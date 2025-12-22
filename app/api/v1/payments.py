from typing import Dict, Any, Tuple, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
import asyncio
import time

from app.core.database import get_db
from app.core.auth import require_api_key
from app.services.conekta_service import conekta_service
from app.services.mikrotik_service import mikrotik_service
from app.schemas.request.pagos import PaymentRequest
from app.models.producto import Producto
from app.models.transaccion import Transaccion

router = APIRouter(tags=["Payments - Hotspot"]) 

# ============================================================================
# FUNCIONES AUXILIARES
# ============================================================================

async def rollback_usuario(router, username: str, user_type: str = "usuario_contrasena"):
    """
    Eliminar usuario en MikroTik si falla el pago
    
    Args:
        router: Objeto router con credenciales
        username: Nombre de usuario a eliminar
        user_type: Tipo de usuario (para logging y debug)
    """
    try:
        print(f"🔄 Ejecutando rollback para usuario: '{username}' (tipo: {user_type})")
        print(f"📋 Username tipo: {type(username).__name__}")
        
        await mikrotik_service.delete_hotspot_user(
            router_host=router.host,
            router_port=router.puerto,
            router_user=router.usuario,
            router_password=router.password_encrypted,
            username=username
        )
        
        print(f"✅ Rollback exitoso: Usuario '{username}' eliminado")
        
    except Exception as e:
        print(f"⚠️  Error en rollback (usuario '{username}'): {str(e)}")


async def ejecutar_auto_conexion(
    router_host: str,
    router_port: int,
    router_user: str,
    router_password: str,
    username: str,
    password: str,
    mac_address: str,
    ip_address: str = None
) -> Dict[str, Any]:
    """
    Ejecutar auto-conexión en MikroTik usando MAC Cookies
    
    FLUJO COMPLETO:
    1. Buscar usuario y vincular MAC
    2. Buscar host en /ip/hotspot/host
    3. Crear/Verificar MAC Cookie en /ip/hotspot/cookie
    4. Ejecutar login con credenciales
    5. Verificar en /ip/hotspot/active
    6. Retornar resultado con info de cookie
    """
    try:
        print(f"🔗 Ejecutando auto-conexión para usuario: {username}, MAC: {mac_address}")
        
        from app.core.mikrotik_api import MikrotikAPI
        
        def conectar_y_verificar():
            with MikrotikAPI(router_host, router_port, router_user, router_password, timeout=10) as api:
                # Formatear MAC correctamente
                mac_formatted = mac_address.lower().replace("-", ":")
                
                # PASO 1: BUSCAR EL USUARIO
                print(f"🔍 Buscando usuario {username}...")
                all_users = api.connection(cmd="/ip/hotspot/user/print")
                user_id = None
                search_name = str(username).strip()
                
                for u in all_users:
                    current_name = str(u.get('name', '')).strip()
                    if current_name == search_name:
                        user_id = u.get('.id')
                        print(f"✅ Usuario encontrado: ID={user_id}")
                        break
                
                if not user_id:
                    print(f"❌ Usuario {username} no encontrado")
                    return {
                        "success": False,
                        "error": f"Usuario {username} no encontrado en MikroTik",
                        "conectado": False
                    }
                
                # PASO 2: VINCULAR MAC AL USUARIO
                print(f"🔗 Vinculando usuario {username} a MAC {mac_formatted}...")
                try:
                    update_result = api.connection(
                        cmd="/ip/hotspot/user/set",
                        **{
                            ".id": user_id,
                            "mac-address": mac_formatted
                        }
                    )
                    list(update_result)
                    print(f"✅ Usuario vinculado a MAC {mac_formatted}")
                except Exception as e:
                    print(f"⚠️ Error vinculando MAC: {e}")
                
                # PASO 3: BUSCAR EL HOST
                print(f"🔍 Buscando host con MAC {mac_formatted} en /ip/hotspot/host...")
                
                host_list = api.connection(cmd="/ip/hotspot/host/print")
                host_id = None
                host_ip = None
                host_server = None
                
                for host in host_list:
                    host_mac = host.get('mac-address', '').lower()
                    
                    if host_mac == mac_formatted.lower():
                        host_id = host.get('.id')
                        host_ip = host.get('address', '')
                        host_server = host.get('server', '')
                        host_authorized = host.get('authorized', 'false')
                        
                        print(f"✅ Host encontrado:")
                        print(f"  .id: {host_id}")
                        print(f"  MAC: {host_mac}")
                        print(f"  IP: {host_ip}")
                        print(f"  Server: {host_server}")
                        print(f"  Autorizado: {host_authorized}")
                        break
                
                if not host_id:
                    print(f"❌ No se encontró el host con MAC {mac_formatted}")
                    return {
                        "success": False,
                        "error": "Cliente no encontrado en hosts. Debe conectarse a la red WiFi primero.",
                        "conectado": False
                    }
                
                # PASO 4: 🍪 CREAR/VERIFICAR MAC COOKIE
                print(f"🍪 Verificando/Creando MAC Cookie para {mac_formatted}...")
                cookie_created = False
                cookie_exists = False
                
                try:
                    # Buscar si ya existe una cookie para esta MAC
                    cookies = api.connection(cmd="/ip/hotspot/cookie/print")
                    
                    for cookie in cookies:
                        cookie_mac = cookie.get('mac-address', '').lower()
                        cookie_user = cookie.get('user', '')
                        
                        if cookie_mac == mac_formatted.lower():
                            cookie_exists = True
                            print(f"✅ Cookie existente encontrada: usuario={cookie_user}, MAC={cookie_mac}")
                            
                            # Verificar si es del usuario correcto
                            if cookie_user.lower() != search_name.lower():
                                # Cookie de otro usuario - eliminar y crear nueva
                                print(f"⚠️ Cookie es de otro usuario ({cookie_user}), eliminando...")
                                try:
                                    del_result = api.connection(
                                        cmd="/ip/hotspot/cookie/remove",
                                        **{".id": cookie.get('.id')}
                                    )
                                    list(del_result)
                                    cookie_exists = False
                                    print(f"✅ Cookie antigua eliminada")
                                except Exception as del_error:
                                    print(f"⚠️ Error eliminando cookie: {del_error}")
                            break
                    
                    # Si no existe cookie, crear una nueva
                    if not cookie_exists:
                        print(f"🆕 Creando nueva MAC Cookie para {username}...")
                        try:
                            add_cookie = api.connection(
                                cmd="/ip/hotspot/cookie/add",
                                **{
                                    "mac-address": mac_formatted,
                                    "user": username
                                }
                            )
                            list(add_cookie)
                            cookie_created = True
                            cookie_exists = True
                            print(f"✅ MAC Cookie creada exitosamente")
                            print(f"   → Ahora visible en: /ip hotspot cookie")
                        except Exception as cookie_error:
                            print(f"⚠️ Error creando cookie: {cookie_error}")
                            cookie_created = False
                    else:
                        print(f"✅ MAC Cookie verificada y válida")
                        
                except Exception as cookie_check_error:
                    print(f"⚠️ Error verificando cookies: {cookie_check_error}")
                
                # PASO 5: INTENTAR AUTORIZAR CON MÚLTIPLES MÉTODOS
                login_success = False
                metodo_usado = None
                
                # 🔥 MÉTODO 1: Login con IP y PASSWORD
                if host_ip:
                    print(f"🔐 MÉTODO 1: Intentando login con IP {host_ip} y contraseña...")
                    try:
                        login_result = api.connection(
                            cmd="/ip/hotspot/active/login",
                            **{
                                "ip": host_ip,
                                "user": username,
                                "password": password
                            }
                        )
                        
                        result_list = list(login_result)
                        login_success = True
                        metodo_usado = "login con IP + Cookie"
                        print(f"✅ MÉTODO 1 exitoso: Login con IP {host_ip}")
                        
                    except Exception as method1_error:
                        error_msg = str(method1_error).lower()
                        print(f"⚠️ MÉTODO 1 falló: {method1_error}")
                        
                        if "already logged in" in error_msg or "already authorized" in error_msg:
                            login_success = True
                            metodo_usado = "ya estaba autorizado"
                            print(f"ℹ️ El host ya está autorizado")
                
                # 🔥 MÉTODO 2: Login con MAC, IP y PASSWORD
                if not login_success and host_ip:
                    print(f"🔐 MÉTODO 2: Intentando login con MAC, IP y contraseña...")
                    try:
                        login_result = api.connection(
                            cmd="/ip/hotspot/active/login",
                            **{
                                "mac-address": mac_formatted,
                                "ip": host_ip,
                                "user": username,
                                "password": password
                            }
                        )
                        
                        result_list = list(login_result)
                        login_success = True
                        metodo_usado = "login con MAC e IP"
                        print(f"✅ MÉTODO 2 exitoso: Login con MAC e IP")
                        
                    except Exception as method2_error:
                        print(f"⚠️ MÉTODO 2 falló: {method2_error}")
                
                # 🔥 MÉTODO 3: Usar numbers (experimental)
                if not login_success and host_server:
                    print(f"🔐 MÉTODO 3: Intentando forzar autenticación en servidor {host_server}...")
                    try:
                        login_result = api.connection(
                            cmd="/ip/hotspot/active/login",
                            **{
                                "numbers": host_id,
                                "user": username
                            }
                        )
                        
                        result_list = list(login_result)
                        login_success = True
                        metodo_usado = "login con numbers"
                        print(f"✅ MÉTODO 3 exitoso")
                        
                    except Exception as method3_error:
                        print(f"⚠️ MÉTODO 3 falló: {method3_error}")
                
                # 🔥 MÉTODO 4: Login completo con todos los parámetros
                if not login_success and host_ip:
                    print(f"🔐 MÉTODO 4: Intentando login completo con todos los parámetros...")
                    try:
                        login_result = api.connection(
                            cmd="/ip/hotspot/active/login",
                            **{
                                "ip": host_ip,
                                "mac-address": mac_formatted,
                                "user": username,
                                "password": password
                            }
                        )
                        
                        result_list = list(login_result)
                        login_success = True
                        metodo_usado = "login completo"
                        print(f"✅ MÉTODO 4 exitoso: Login completo")
                        
                    except Exception as method4_error:
                        error_msg = str(method4_error).lower()
                        print(f"⚠️ MÉTODO 4 falló: {method4_error}")
                        
                        if "already" in error_msg:
                            login_success = True
                            metodo_usado = "ya autenticado"
                
                if not login_success:
                    print(f"❌ Todos los métodos de autenticación fallaron")
                else:
                    print(f"✅ Autenticación exitosa usando: {metodo_usado}")
                
                # PASO 6: VERIFICAR EN SESIONES ACTIVAS
                print(f"🔍 Verificando sesiones activas en /ip/hotspot/active...")
                time.sleep(2.5)
                
                cliente_en_activos = False
                session_id = None
                session_info = {}
                tiene_cookie = cookie_exists
                
                try:
                    active_sessions = api.connection(cmd="/ip/hotspot/active/print")
                    
                    for session in active_sessions:
                        session_mac = session.get('mac-address', '').lower()
                        session_ip = session.get('address', '')
                        session_user = str(session.get('user', '')).strip()
                        
                        # Buscar por MAC, IP o Usuario
                        match_by_mac = session_mac == mac_formatted.lower()
                        match_by_ip = (host_ip and session_ip == host_ip)
                        match_by_user = session_user.lower() == search_name.lower()
                        
                        if match_by_mac or match_by_ip or match_by_user:
                            cliente_en_activos = True
                            session_id = session.get('.id')
                            session_info = {
                                'id': session_id,
                                'user': session.get('user'),
                                'address': session.get('address'),
                                'mac': session.get('mac-address'),
                                'uptime': session.get('uptime', '0s'),
                                'server': session.get('server', '')
                            }
                            
                            print(f"✅✅✅ CLIENTE AUTENTICADO Y ACTIVO:")
                            print(f"  Session ID: {session_id}")
                            print(f"  Usuario: {session.get('user')}")
                            print(f"  MAC: {session.get('mac-address')}")
                            print(f"  IP: {session.get('address')}")
                            print(f"  Uptime: {session.get('uptime', '0s')}")
                            print(f"  Server: {session.get('server', '')}")
                            break
                    
                    # Segunda verificación si no se encontró
                    if not cliente_en_activos:
                        print(f"⚠️ Primera verificación: no encontrado en activos")
                        print(f"🔄 Esperando 3s más y re-verificando...")
                        time.sleep(3.0)
                        
                        active_sessions = api.connection(cmd="/ip/hotspot/active/print")
                        for session in active_sessions:
                            session_mac = session.get('mac-address', '').lower()
                            session_ip = session.get('address', '')
                            
                            if session_mac == mac_formatted.lower() or (host_ip and session_ip == host_ip):
                                cliente_en_activos = True
                                session_id = session.get('.id')
                                session_info = {
                                    'id': session_id,
                                    'user': session.get('user'),
                                    'address': session.get('address'),
                                    'mac': session.get('mac-address')
                                }
                                print(f"✅ Cliente encontrado en segunda verificación")
                                break
                
                except Exception as verify_error:
                    print(f"⚠️ Error verificando sesiones activas: {verify_error}")
                
                # PASO 7: RETORNAR RESULTADO CON INFO DE COOKIE
                resultado = {
                    "success": login_success,
                    "conectado": cliente_en_activos,
                    "mac": mac_formatted,
                    "ip": host_ip or ip_address or "",
                    "username": username,
                    "host_id": host_id,
                    "session_id": session_id,
                    "session_info": session_info if cliente_en_activos else {},
                    "metodo_usado": metodo_usado,
                    "cookie_creada": cookie_created,
                    "tiene_cookie": tiene_cookie,
                    "auto_login_ejecutado": login_success,
                    "verificado_en_activos": cliente_en_activos
                }
                
                if cliente_en_activos:
                    cookie_msg = " 🍪 (Cookie guardada - auto-conexión habilitada)" if tiene_cookie else ""
                    resultado["mensaje"] = f"✅ Autenticado exitosamente{cookie_msg}"
                    print(f"🎉 AUTO-CONEXIÓN COMPLETADA Y VERIFICADA")
                    if tiene_cookie:
                        print(f"🍪 Cookie guardada en /ip/hotspot/cookie")
                        print(f"   → Próximas conexiones serán automáticas")
                elif login_success:
                    resultado["mensaje"] = f"⏳ Login ejecutado ({metodo_usado}). Verificando..."
                    print(f"⚠️ Login ejecutado pero no aparece en activos aún")
                else:
                    resultado["mensaje"] = "❌ No se pudo autenticar. Use credenciales manualmente."
                    resultado["error"] = "Todos los métodos fallaron"
                    print(f"❌ Auto-conexión falló")
                
                return resultado
        
        # Ejecutar en thread
        loop = asyncio.get_event_loop()
        resultado = await loop.run_in_executor(None, conectar_y_verificar)
        return resultado
        
    except Exception as e:
        print(f"❌ Error en auto-conexión: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "conectado": False,
            "error": f"Error de conexión: {str(e)}",
            "mensaje": "Error crítico en auto-conexión"
        }
    

def validar_estado_pago_conekta(payment_result: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Validar estado de pago de Conekta y retornar mensaje apropiado
    
    Args:
        payment_result: Resultado de la API de Conekta
        
    Returns:
        tuple: (es_valido: bool, mensaje_error: str)
    """
    status = payment_result.get("payment_status", "").lower()
    
    # Estados válidos
    if status == "paid":
        return True, ""
    
    # Mapeo de estados inválidos a mensajes
    status_messages = {
        "pending": "El pago está pendiente de confirmación.",
        "declined": "El pago fue declinado. Contacte a su banco.",
        "expired": "El pago expiró. Realice una nueva transacción.",
        "canceled": "El pago fue cancelado.",
        "refunded": "El pago fue reembolsado.",
        "chargeback": "Disputa activa en el pago.",
        "pre_authorized": "Pago pre-autorizado pendiente de captura.",
        "partially_paid": "El pago está parcialmente completado.",
        "pending_payment": "Pendiente de procesamiento de pago.",
        "failed": "El pago falló. Intente nuevamente.",
        "voided": "El pago fue anulado.",
    }
    
    mensaje = status_messages.get(status, "El pago no fue aprobado.")
    return False, mensaje


def construir_respuesta_auto_conexion(
    auto_connect_requested: bool,
    mac_address: str = None,
    ip_address: str = None,
    auto_conexion_resultado: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Construir estructura de respuesta para auto-conexión
    
    Args:
        auto_connect_requested: Si se solicitó auto-conexión
        mac_address: Dirección MAC del cliente
        ip_address: Dirección IP del cliente
        auto_conexion_resultado: Resultado de la auto-conexión
        
    Returns:
        Dict con estructura de auto_conexion
    """
    if not auto_connect_requested:
        return {
            "estado": "no_conectado",
            "mac": "",
            "ip": "",
            "mensaje": "Favor de ingresar sus credenciales para conectar a Internet",
            "verificado": False
        }
    
    if not mac_address:
        return {
            "estado": "no_conectado",
            "mac": "",
            "ip": "",
            "mensaje": "No se pudo conectar automáticamente. Use las credenciales para conectar a Internet",
            "verificado": False
        }
    
    # Si tenemos resultado de la auto-conexión
    if auto_conexion_resultado:
        # SOLO dos estados: "conectado" o "no_conectado"
        if auto_conexion_resultado.get("conectado"):
            return {
                "estado": "conectado",
                "mac": mac_address,
                "ip": ip_address or "",
                "mensaje": "¡Conexión establecida con éxito! Disfrute de Internet sin límites",
                "verificado": True,
                "session_id": auto_conexion_resultado.get("session_id")
            }
        else:
            # Cualquier otro caso es "no_conectado"
            mensaje = "No se pudo conectar automáticamente. Use las credenciales para conectar a Internet"
            
            if auto_conexion_resultado.get("auto_login_ejecutado"):
                mensaje = "Su conexión está en proceso. Si no se conecta automáticamente, use las credenciales"
            elif auto_conexion_resultado.get("error"):
                if "timeout" in str(auto_conexion_resultado.get("error")).lower():
                    mensaje = "El servicio está tardando en responder. Use las credenciales para conectarse a internet"
                elif "connection" in str(auto_conexion_resultado.get("error")).lower():
                    mensaje = "No se pudo conectar automáticamente. Use las credenciales para conectar a Internet"
                else:
                    mensaje = "No se pudo conectar automáticamente. Use las credenciales para conectar a Internet"
            
            return {
                "estado": "no_conectado",
                "mac": mac_address,
                "ip": ip_address or "",
                "mensaje": mensaje,
                "verificado": False
            }
    
    # Caso genérico (sin resultado)
    return {
        "estado": "no_conectado",
        "mac": mac_address,
        "ip": ip_address or "",
        "mensaje": "Procesando su conexión automática...",
        "verificado": False
    }


def construir_respuesta_exitosa(
    transaccion: Transaccion,
    credentials: Dict[str, str],
    producto: Producto,
    payment_data: PaymentRequest,
    auto_conexion_info: Dict[str, Any],
    user_type: str
) -> Dict[str, Any]:
    """
    Construir respuesta exitosa del endpoint
    
    Args:
        transaccion: Objeto Transaccion guardado
        credentials: Credenciales generadas
        producto: Producto comprado
        payment_data: Datos del pago
        auto_conexion_info: Info de auto-conexión
        user_type: Tipo de usuario generado
        
    Returns:
        Dict con respuesta estructurada
    """
    return {
        "success": True,
        "id_transaccion": transaccion.transaccion_id,
        "estado_pago": "paid",
        "tipo_usuario": user_type,  # ✅ Mantener en respuesta
        "usuario_hotspot": {
            "usuario": credentials["username"],
            "contrasena": credentials["password"]
        },
        "producto": {
            "nombre": producto.nombre_venta,
            "precio": float(producto.precio),
            "moneda": producto.moneda,
            "perfil_mikrotik": producto.perfil_mikrotik_nombre
        },
        "cliente": {
            "nombre": payment_data.customer_name,
            "email": payment_data.customer_email
        },
        "timestamp": datetime.utcnow().isoformat(),
        "auto_conexion": auto_conexion_info
    }


def manejar_error_inesperado(
    error: Exception,
    usuario_creado: bool,
    router,
    credentials: Dict[str, str],
    db: AsyncSession,
    user_type: str  # Agregar este parámetro
):
    """
    Manejar error inesperado y determinar mensaje apropiado
    
    Args:
        error: Excepción capturada
        usuario_creado: Si el usuario fue creado en MikroTik
        router: Objeto router para rollback
        credentials: Credenciales para rollback
        db: Sesión de BD para rollback
        user_type: Tipo de usuario (para rollback)
    """
    print(f"❌ Error inesperado: {type(error).__name__}: {str(error)}")
    
    # Determinar tipo de error
    if not usuario_creado:
        # Error CREANDO usuario en MikroTik
        error_msg = "No se pudo crear el acceso a internet. Contacte al administrador."
    elif "conekta" in str(error).lower():
        # Error de Conekta (no manejado por HTTPException)
        error_msg = "Error procesando el pago. Verifique los datos de su tarjeta."
    else:
        error_msg = "Error interno del servidor."
    
    # Rollback del usuario si se creó
    if usuario_creado:
        asyncio.create_task(rollback_usuario(router, credentials["username"], user_type))  # Pasar user_type
    
    # Rollback de BD
    asyncio.create_task(db.rollback())
    
    return HTTPException(
        status_code=500,
        detail=error_msg
    )


# ============================================================================
# ENDPOINT PRINCIPAL
# ============================================================================

@router.post("/pagar-conekta",
    summary="Procesar pago para acceso Hotspot MikroTik",
    description="""
    ## 📋 Descripción
    
    Procesa pagos mediante Conekta para crear usuarios en Hotspot MikroTik.
    
    ## 🔐 Autenticación
    - Requiere API Key en header: `X-API-Key: jwt_eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...`
    
    ## 📥 Parámetros del Request
    
    ### 🏷️ Campos Requeridos:
    • **producto_id** (integer): ID del producto
    • **token_tarjeta** (string): Token de tarjeta Conekta.js
    • **nombre_cliente** (string): Nombre del cliente
    • **email_cliente** (string): Email válido
    
    ### 🔧 Campos Opcionales:
    • **tipo_usuario** (string):
      - 'usuario_contrasena' (default): Usuario + contraseña (ej: 'AB3C9D' + '1234')
      - 'pin': Solo PIN numérico de 6 dígitos (sin contraseña, ej: '123456')
      - Si es null/vacío o valor inválido → 'usuario_contrasena'
    
    • **telefono_cliente** (string): Teléfono
    • **mac_cliente** (string): MAC para conexión automática
    • **ip_cliente** (string): IP del cliente
    • **info_dispositivo** (string): Info adicional
    • **conexion_automatica** (boolean): Intenta conexión automática (default: false)
    """
)
async def pagar_hotspot_conekta(
    payment_data: PaymentRequest,
    auth_data = Depends(require_api_key),
    db: AsyncSession = Depends(get_db)
):
    """
    Procesar pago para acceso Hotspot MikroTik
    
    Flujo:
    1. Validar producto y empresa
    2. Generar credenciales según tipo de usuario
    3. Crear usuario en MikroTik (CRÍTICO - si falla, no hay pago)
    4. Procesar pago con Conekta
    5. Validar estado del pago (doble verificación)
    6. Guardar transacción en BD
    7. Ejecutar auto-conexión si se solicitó
    8. Retornar credenciales al cliente
    """
    empresa, router, auth_info = auth_data

    # 1. Obtener producto
    result = await db.execute(
        select(Producto).where(Producto.id == payment_data.product_id)
    )
    producto = result.scalar_one_or_none()

    if not producto or producto.empresa_id != empresa.id:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    # 2. Normalizar tipo de usuario
    user_type = payment_data.user_type or "usuario_contrasena"
    if user_type not in ["usuario_contrasena", "pin"]:
        user_type = "usuario_contrasena"
    
    print(f"🔧 Tipo de usuario configurado: {user_type}")

    # 3. Validar parámetros para auto-conexión
    auto_connect_requested = payment_data.auto_connect
    
    # 4. Generar credenciales según tipo de usuario
    credentials = mikrotik_service.generate_credentials(user_type=user_type)
    usuario_creado = False

    try:
        # 🔴 **PASO CRÍTICO 1: CREAR USUARIO EN MIKROTIK**
        print(f"🔴 Creando usuario en MikroTik: {credentials['username']} (tipo: {user_type})")
        
        await mikrotik_service.create_hotspot_user(
            router_host=router.host,
            router_port=router.puerto,
            router_user=router.usuario,
            router_password=router.password_encrypted,
            username=credentials["username"],
            password=credentials["password"],
            profile_name=producto.perfil_mikrotik_nombre,
            user_type=user_type
        )
        
        usuario_creado = True
        print(f"✅ Usuario creado en MikroTik")
        
        # 🟢 **PASO CRÍTICO 2: PROCESAR PAGO EN CONEKTA**
        payment_result = await conekta_service.create_order(
            private_key=empresa.conekta_private_key,
            mode=empresa.conekta_mode,
            amount=float(producto.precio),
            currency=producto.moneda,
            card_token=payment_data.card_token,
            customer_info={
                "nombre": payment_data.customer_name,
                "email": payment_data.customer_email,
                "telefono": payment_data.customer_phone
            },
            description=producto.nombre_venta,
            metadata={
                "empresa_id": empresa.id,
                "router_id": router.id,
                "producto_id": producto.id,
                "auto_connect_requested": auto_connect_requested,
                "mac_cliente": payment_data.mac_address or "",
                "ip_cliente": payment_data.ip_address or "",
                "user_type": user_type  # ✅ Guardar en metadata de Conekta
            }
        )

        # 🔒 **VALIDACIÓN DE SEGURIDAD (DOBLE CHECK)**
        es_valido, mensaje_error = validar_estado_pago_conekta(payment_result)
        
        if not es_valido:
            print(f"❌ Validación fallida: {mensaje_error}")
            
            # Rollback del usuario creado
            if usuario_creado:
                await rollback_usuario(router, credentials["username"], user_type)  # Pasar user_type
            
            await db.rollback()
            raise HTTPException(status_code=402, detail=mensaje_error)

        print(f"✅ Pago procesado exitosamente: {payment_result['order_id']}")

        # 5. Guardar transacción (SIN tipo_usuario para evitar error)
        transaccion = Transaccion(
            transaccion_id=payment_result["order_id"],
            empresa_id=empresa.id,
            router_id=router.id,
            producto_id=producto.id,
            monto=producto.precio,
            moneda=producto.moneda,
            cliente_nombre=payment_data.customer_name,
            cliente_email=payment_data.customer_email,
            cliente_telefono=payment_data.customer_phone,
            usuario_hotspot=credentials["username"],
            password_hotspot=credentials["password"],
            # ❌ NO incluir tipo_usuario aquí - no existe en el modelo
            estado_pago="paid",
            estado_hotspot="active",
            api_key_usada=auth_info.get("api_key_id", ""),
            pagada_en=datetime.utcnow(),
            usuario_creado_en=datetime.utcnow()
        )
        db.add(transaccion)
        await db.commit()

        print(f"✅ Transacción guardada: {transaccion.transaccion_id} (tipo: {user_type})")

        # 🔄 **EJECUTAR AUTO-CONEXIÓN SI SE SOLICITÓ**
        auto_conexion_resultado = None
        if auto_connect_requested and payment_data.mac_address:
            try:
                auto_conexion_resultado = await ejecutar_auto_conexion(
                    router_host=router.host,
                    router_port=router.puerto,
                    router_user=router.usuario,
                    router_password=router.password_encrypted,
                    username=credentials["username"],
                    password=credentials["password"],
                    mac_address=payment_data.mac_address,
                    ip_address=payment_data.ip_address
                )
                
                if auto_conexion_resultado and auto_conexion_resultado.get("conectado"):
                    print(f"✅✅✅ Auto-conexión VERIFICADA: Cliente autenticado en activos")
                elif auto_conexion_resultado and auto_conexion_resultado.get("success"):
                    print(f"⚠️  Auto-login ejecutado pero no verificado en activos")
                else:
                    print(f"⚠️  Auto-conexión falló parcialmente")
                    
            except Exception as auto_connect_error:
                print(f"⚠️  Error en auto-conexión: {auto_connect_error}")
                auto_conexion_resultado = {
                    "success": False,
                    "conectado": False,
                    "error": str(auto_connect_error)
                }

        # 6. Construir info de auto-conexión
        auto_conexion_info = construir_respuesta_auto_conexion(
            auto_connect_requested=auto_connect_requested,
            mac_address=payment_data.mac_address,
            ip_address=payment_data.ip_address,
            auto_conexion_resultado=auto_conexion_resultado
        )

        # 7. Construir y retornar respuesta
        response_data = construir_respuesta_exitosa(
            transaccion=transaccion,
            credentials=credentials,
            producto=producto,
            payment_data=payment_data,
            auto_conexion_info=auto_conexion_info,
            user_type=user_type
        )

        return response_data

    # 🔴 **MANEJO DE ERRORES HTTP (de conekta_service u otros)**
    except HTTPException as http_exc:
        print(f"❌ Error HTTP {http_exc.status_code}: {http_exc.detail}")
        
        # 🔥 CORRECCIÓN: Hacer rollback SIEMPRE que sea error 402 (pago rechazado)
        # ConektaService ahora lanza 402 para TODOS los errores de pago
        if usuario_creado and http_exc.status_code == 402:
            print(f"🔄 Ejecutando rollback por pago rechazado...")
            await rollback_usuario(router, credentials["username"], user_type)  # Pasar user_type
        
        await db.rollback()
        raise http_exc  # Este error ya tiene mensaje claro
        
    # 🔴 **MANEJO DE ERRORES INESPERADOS**
    except Exception as e:
        error_exception = manejar_error_inesperado(
            error=e,
            usuario_creado=usuario_creado,
            router=router,
            credentials=credentials,
            db=db,
            user_type=user_type  # Pasar user_type
        )
        raise error_exception
    

    #####______
    
    
    
"""
📦 FLUJO COMPLETO DE PAGO:

CLIENTE FINAL (en portal WiFi del cliente) 
       ↓
HEADER: X-API-Key: jwt_eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
       ↓
POST /api/v1/payments/process (TU SISTEMA)
       ↓
require_api_key() VALIDA EL TOKEN ←─┐
       ↓                            │
DEVUELVE: (empresa, router, auth_info) ──┤
       ↓                            │ ¡ES EL MISMO TOKEN!
PROCESA PAGO EN CONEKTA             │ QUE SE GENERA CON:
       ↓                            │ POST /admin/empresas/.../routers
CREA USUARIO EN MIKROTIK            │
       ↓                            │
RETORNA CREDENCIALES AL CLIENTE     │
                                    │
token = "jwt_eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
       └─────────────────────────────┘
"""

# =============================================
# DETALLE DE CÓMO FUNCIONA require_api_key():
# =============================================
"""
require_api_key() HACE:

1. Recibe: X-API-Key: jwt_eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
2. Quita "jwt_" → queda el JWT puro
3. Calcula SHA256(JWT) → hash
4. Busca en api_keys_tracking:
   WHERE key_hash = hash 
   AND revoked = False 
   AND expires_at > NOW()
5. Si encuentra, decodifica JWT para validar firma
6. Con el router_id del JWT, busca el router
7. Con el empresa_id, busca la empresa
8. Retorna tupla: (empresa, router, auth_info)

ENTONCES TU ENDPOINT /process TIENE ACCESO A:
• empresa.conekta_private_key (para procesar pago)
• router.host, .puerto, .usuario, .password (para MikroTik)
• Datos del JWT (para auditoría)
"""