from typing import Dict, Any, Tuple, Optional
import asyncio
import time
import hashlib
import logging
import re

# ============================================================================
# 1. VERSIÓN v6 - CÓDIGO ORIGINAL EXACTO (el que funcionaba correctamente)
# ============================================================================
async def ejecutar_auto_conexion_v6(
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
    → VERSIÓN ORIGINAL que funcionaba correctamente en v6
    """
    try:
        print(f"🔗 [v6 ORIGINAL] Ejecutando auto-conexión para usuario: {username}, MAC: {mac_address}")
        
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
                    cookies = api.connection(cmd="/ip/hotspot/cookie/print")
                    
                    for cookie in cookies:
                        cookie_mac = cookie.get('mac-address', '').lower()
                        cookie_user = cookie.get('user', '')
                        
                        if cookie_mac == mac_formatted.lower():
                            cookie_exists = True
                            print(f"✅ Cookie existente encontrada: usuario={cookie_user}, MAC={cookie_mac}")
                            
                            if cookie_user.lower() != search_name.lower():
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
                        list(login_result)
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
                        list(login_result)
                        login_success = True
                        metodo_usado = "login con MAC e IP"
                        print(f"✅ MÉTODO 2 exitoso: Login con MAC e IP")
                    except Exception as method2_error:
                        print(f"⚠️ MÉTODO 2 falló: {method2_error}")
                
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
                        list(login_result)
                        login_success = True
                        metodo_usado = "login con numbers"
                        print(f"✅ MÉTODO 3 exitoso")
                    except Exception as method3_error:
                        print(f"⚠️ MÉTODO 3 falló: {method3_error}")
                
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
                        list(login_result)
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
                
                # PASO 7: RETORNAR RESULTADO
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
        
        loop = asyncio.get_event_loop()
        resultado = await loop.run_in_executor(None, conectar_y_verificar)
        return resultado
        
    except Exception as e:
        print(f"❌ Error en auto-conexión v6: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "conectado": False,
            "error": f"Error de conexión: {str(e)}",
            "mensaje": "Error crítico en auto-conexión"
        }

# ============================================================================
# 2. VERSIÓN PARA v7.x (más paciente y optimizada)
# ============================================================================

def clean_script_content(content: str) -> str:
    """Limpia el contenido del script para asegurar compatibilidad"""
    try:
        # Primero eliminar todos los emojis y caracteres no ASCII
        cleaned_content = re.sub(r'[^\x00-\x7F]', ' ', content)
        
        # Reemplazar caracteres problemáticos comunes
        replacements = {
            'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u',
            'Á': 'A', 'É': 'E', 'Í': 'I', 'Ó': 'O', 'Ú': 'U',
            'ñ': 'n', 'Ñ': 'N',
            '¿': '', '¡': '',
            '`': "'", '´': "'", '“': '"', '”': '"', '‘': "'", '’': "'"
        }
        
        for old_char, new_char in replacements.items():
            cleaned_content = cleaned_content.replace(old_char, new_char)
        
        # Normalizar saltos de línea a formato Unix
        cleaned_content = cleaned_content.replace('\r\n', '\n').replace('\r', '\n')
        
        # Eliminar múltiples espacios consecutivos
        cleaned_content = re.sub(r' +', ' ', cleaned_content)
        
        # Eliminar múltiples saltos de línea consecutivos
        cleaned_content = re.sub(r'\n\s*\n', '\n\n', cleaned_content)
        
        logger.info(f"Script limpiado: {len(content)} -> {len(cleaned_content)} caracteres")
        
        return cleaned_content
        
    except Exception as e:
        logger.error(f"Error limpiando script: {e}")
        return content

logger = logging.getLogger("hotspot_v7")
async def ejecutar_auto_conexion_v7(
    router_host: str,
    router_port: int,
    router_user: str,
    router_password: str,
    username: str,
    password: str,
    mac_address: str,
    ip_address: str | None = None
) -> Dict[str, Any]:
    
    logger.info(f"[START] auto-login v7 | user={username} | mac={mac_address}")

    from app.core.mikrotik_api import MikrotikAPI
    def worker():
        with MikrotikAPI(
            router_host,
            router_port,
            router_user,
            router_password,
            timeout=20
        ) as api:

            # Normalizar MAC
            mac = mac_address.lower().replace("-", ":")
            logger.info(f"[1] MAC: {mac}")
            
            # Obtener la conexión directa
            conn = api.connection
            
            # Primero obtener la IP del host si no se proporciona
            client_ip = ip_address
            if not client_ip:
                logger.info(f"[1.5] Obteniendo IP para MAC: {mac}")
                try:
                    hosts = list(conn(cmd='/ip/hotspot/host/print'))
                    for host in hosts:
                        if host.get('mac-address', '').lower() == mac:
                            client_ip = host.get('to-address') or host.get('address')
                            if client_ip:
                                logger.info(f"[1.5][OK] IP obtenida: {client_ip}")
                                break
                except Exception as e:
                    logger.error(f"[1.5][ERROR] Error obteniendo IP: {e}")
            
            if not client_ip:
                logger.error(f"[1.5][FAIL] No se pudo obtener IP para MAC: {mac}")
                return {
                    "success": False,
                    "conectado": False,
                    "error": f"No se pudo obtener IP para MAC {mac}",
                    "mac": mac,
                    "username": username,
                    "mensaje": "El dispositivo no está conectado al hotspot"
                }
            
            # Script ultra simple - solo ASCII
            timestamp = int(time.time())
            script_name = f"__login_{hashlib.md5(f'{mac}_{timestamp}'.encode()).hexdigest()[:8]}"
            
            # Script mínimo en ASCII puro - CON IP FIJA
            script_source = f""":local user "{username}"
:local pass "{password}"
:local mac "{mac}"
:local ip "{client_ip}"

:log info ("Ejecutando login para: " . $mac . " en IP: " . $ip)
/ip/hotspot/active/login user=$user password=$pass ip=$ip mac-address=$mac
:log info "Login ejecutado"
:delay 2

:local sesion [/ip/hotspot/active/find where mac-address=$mac]
:if ([:len $sesion] > 0) do={{
    :local info [/ip/hotspot/active/get $sesion]
    :log info ("Sesion activa: " . ($info->"user") . " en " . ($info->"address"))
}} else={{
    :log warning "No se encontro sesion activa"
}}
"""
            
            # Limpiar el script
            script_source_clean = clean_script_content(script_source)
            
            logger.info(f"[2] Creando script: {script_name}")
            
            try:
                # 1. Eliminar script si ya existe
                try:
                    scripts = list(conn(cmd='/system/script/print'))
                    for script in scripts:
                        if script.get('name') == script_name:
                            logger.info(f"[2][CLEAN] Eliminando script existente: {script_name}")
                            list(conn(cmd='/system/script/remove', numbers=script.get('.id')))
                            break
                except Exception as e:
                    logger.info(f"[2][INFO] No se pudo limpiar script existente: {e}")
                
                # 2. Crear script
                logger.info(f"[2][ADD] Agregando script...")
                list(conn(
                    cmd='/system/script/add',
                    name=script_name,
                    source=script_source_clean
                ))
                logger.info(f"[2][OK] Script creado")
                
                # 3. Ejecutar script
                logger.info(f"[3] Ejecutando script...")
                
                # Primero obtener el ID del script
                scripts = list(conn(cmd='/system/script/print'))
                script_id = None
                for script in scripts:
                    if script.get('name') == script_name:
                        script_id = script.get('.id')
                        break
                
                if not script_id:
                    raise Exception(f"No se encontró ID para script {script_name}")
                
                # Ejecutar usando .id
                logger.info(f"[3][RUN] Ejecutando con ID: {script_id}")
                list(conn(cmd='/system/script/run', **{'.id': script_id}))
                logger.info(f"[3][OK] Script ejecutado")
                
                # 4. Esperar a que el script termine
                time.sleep(3)
                
                # 5. Verificar sesión
                logger.info("[4] Verificando sesión...")
                
                # Obtener todas las sesiones activas
                active_sessions = list(conn(cmd='/ip/hotspot/active/print'))
                matching_sessions = []
                
                for session in active_sessions:
                    session_mac = session.get('mac-address', '').lower()
                    if session_mac == mac:
                        matching_sessions.append(session)
                
                if matching_sessions:
                    sesion = matching_sessions[0]
                    logger.info(f"[4][OK] Sesión encontrada")
                    logger.info(f"    Usuario: {sesion.get('user')}")
                    logger.info(f"    IP: {sesion.get('address')}")
                    logger.info(f"    Uptime: {sesion.get('uptime')}")
                    
                    # 6. Limpiar script
                    try:
                        list(conn(cmd='/system/script/remove', numbers=script_id))
                        logger.info("[5] Script limpiado")
                    except Exception as e:
                        logger.info(f"[5][INFO] No se pudo limpiar script: {e}")
                    
                    return {
                        "success": True,
                        "conectado": True,
                        "ip": sesion.get('address'),
                        "mac": mac,
                        "username": username,
                        "session_info": {
                            "user": sesion.get('user'),
                            "address": sesion.get('address'),
                            "uptime": sesion.get('uptime'),
                            "mac-address": sesion.get('mac-address'),
                            "bytes-in": sesion.get('bytes-in'),
                            "bytes-out": sesion.get('bytes-out')
                        },
                        "mensaje": "Login exitoso"
                    }
                else:
                    logger.warning("[4][WARN] No se encontró sesión activa")
                    
                    # Verificar si el usuario existe de todas formas
                    for session in active_sessions:
                        if session.get('user') == username:
                            logger.info(f"[4][INFO] Usuario {username} encontrado con diferente MAC")
                            return {
                                "success": True,
                                "conectado": True,
                                "ip": session.get('address'),
                                "mac": session.get('mac-address'),
                                "username": username,
                                "session_info": {
                                    "user": session.get('user'),
                                    "address": session.get('address'),
                                    "uptime": session.get('uptime')
                                },
                                "mensaje": "Usuario ya autenticado (diferente MAC)"
                            }
                    
                    # Limpiar script
                    try:
                        list(conn(cmd='/system/script/remove', numbers=script_id))
                    except:
                        pass
                    
                    return {
                        "success": False,
                        "conectado": False,
                        "error": "Script ejecutado pero no se encontró sesión",
                        "ip": client_ip,
                        "mac": mac,
                        "username": username,
                        "mensaje": "Verificar manualmente en router"
                    }
                    
            except Exception as e:
                logger.error(f"[ERROR] {e}")
                import traceback
                traceback.print_exc()
                
                # Intentar limpiar script en caso de error
                try:
                    scripts = list(conn(cmd='/system/script/print'))
                    for script in scripts:
                        if script.get('name') == script_name:
                            list(conn(cmd='/system/script/remove', numbers=script.get('.id')))
                            break
                except:
                    pass
                
                return {
                    "success": False,
                    "conectado": False,
                    "error": str(e),
                    "ip": client_ip,
                    "mac": mac,
                    "username": username
                }

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, worker)


# ============================================================================
# 3. FUNCIÓN PÚBLICA (la que todos llaman) - detecta versión automáticamente
# ============================================================================
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
    Punto de entrada principal.
    Detecta la versión de RouterOS y llama a la función adecuada.
    Conserva la misma firma para no romper el resto del código.
    """
    try:
        print(f"🔍 Detectando versión de RouterOS...")
        
        from app.core.mikrotik_api import MikrotikAPI
        
        # Conexión rápida solo para detectar versión
        with MikrotikAPI(router_host, router_port, router_user, router_password, timeout=8) as api:
            try:
                res = api.connection(cmd="/system/resource/print")
                version_str = next(iter(res)).get("version", "6.48").strip()
                major = int(version_str.split(".")[0])
                print(f"RouterOS detectado: v{version_str}")
            except Exception:
                major = 6
                print("⚠️ No se pudo detectar versión → asumiendo v6")
        
        if major >= 7:
            print("→ Delegando a versión optimizada para v7.x")
            return await ejecutar_auto_conexion_v7(
                router_host, router_port, router_user, router_password,
                username, password, mac_address, ip_address
            )
        else:
            print("→ Usando versión v6 ORIGINAL que funcionaba correctamente")
            return await ejecutar_auto_conexion_v6(
                router_host, router_port, router_user, router_password,
                username, password, mac_address, ip_address
            )
    
    except Exception as e:
        print(f"❌ Error crítico al detectar versión: {e}")
        return {
            "success": False,
            "conectado": False,
            "error": str(e),
            "mensaje": "Error crítico durante la auto-conexión"
        } 
