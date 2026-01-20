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
    Versión v6 - Login DIRECTO (sin scripts) + limpieza SOLO de sesiones activas por username
    """
    logger.info(f"[START] auto-login v6 DIRECTO | user={username} | mac={mac_address} | ip={ip_address or 'auto-detect'}")

    from app.core.mikrotik_api import MikrotikAPI
    
    def worker():
        with MikrotikAPI(
            router_host,
            router_port,
            router_user,
            router_password,
            timeout=15  # un poco más de margen por si el login tarda
        ) as api:

            mac = mac_address.lower().replace("-", ":")
            username_lower = username.strip().lower()
            logger.info(f"[1] MAC: {mac} | Username normalizado: {username_lower}")
            
            conn = api.connection
            
            # ── LIMPIEZA PREVIA: SOLO sesiones activas por username ───────────────
            logger.info("[LIMPIEZA] Eliminando sesiones activas previas (solo por username)...")

            try:
                active = list(conn(cmd='/ip/hotspot/active/print'))
                logger.info(f"[LIMPIEZA] Sesiones activas encontradas: {len(active)}")

                removed_sessions = 0
                for session in active:
                    s_user = str(session.get('user', '')).strip().lower()
                    
                    if s_user == username_lower:
                        sid = session.get('.id')
                        s_ip = session.get('address', 'sin-ip')
                        s_mac_report = session.get('mac-address', 'sin-mac')
                        
                        try:
                            list(conn(cmd='/ip/hotspot/active/remove', numbers=sid))
                            removed_sessions += 1
                            logger.info(
                                f"[LIMPIEZA] Sesión eliminada → "
                                f"ID: {sid} | User: '{session.get('user')}' | "
                                f"IP: {s_ip} | MAC reportada: {s_mac_report}"
                            )
                        except Exception as remove_err:
                            logger.warning(f"[LIMPIEZA] Falló eliminar sesión {sid}: {remove_err}")

                if removed_sessions > 0:
                    logger.info(f"[LIMPIEZA] Éxito: {removed_sessions} sesión(es) eliminada(s)")
                else:
                    logger.info("[LIMPIEZA] No había sesiones activas para este usuario")
            except Exception as e:
                logger.error(f"[LIMPIEZA] Error al procesar sesiones activas: {e}")

            time.sleep(1.0)  # reducido, solo lo necesario para que la eliminación se refleje
            
            # ── OBTENER IP si no viene dada ────────────────────────────────────────
            client_ip = ip_address
            if not client_ip:
                logger.info("[2] Detectando IP del cliente...")
                try:
                    hosts = list(conn(cmd='/ip/hotspot/host/print'))
                    for host in hosts:
                        if host.get('mac-address', '').lower() == mac:
                            client_ip = host.get('address', '')
                            if client_ip:
                                logger.info(f"[OK] IP detectada: {client_ip}")
                                break
                except Exception as e:
                    logger.error(f"Error obteniendo IP: {e}")

            if not client_ip:
                return {
                    "success": False,
                    "conectado": False,
                    "error": "No se pudo detectar IP del cliente",
                    "mensaje": "El dispositivo debe estar conectado al hotspot primero"
                }

            # ── LOGIN DIRECTO (múltiples intentos con parámetros diferentes) ───────
            logger.info("[LOGIN DIRECTO] Intentando autenticación...")

            success = False
            metodo_usado = "ninguno"
            error_msg = None

            try:
                # Intento 1: Básico con IP + user + pass (el más común que funciona)
                logger.info("Intento 1: login con IP + user + pass")
                list(conn(
                    cmd="/ip/hotspot/active/login",
                    **{"ip": client_ip, "user": username, "password": password}
                ))
                success = True
                metodo_usado = "ip_user_pass"
            except Exception as e1:
                error_msg = str(e1)
                logger.warning(f"Intento 1 falló: {e1}")

            if not success:
                try:
                    # Intento 2: Agregar mac-address explícitamente
                    logger.info("Intento 2: login con IP + MAC + user + pass")
                    list(conn(
                        cmd="/ip/hotspot/active/login",
                        **{"ip": client_ip, "mac-address": mac, "user": username, "password": password}
                    ))
                    success = True
                    metodo_usado = "ip_mac_user_pass"
                except Exception as e2:
                    logger.warning(f"Intento 2 falló: {e2}")

            if not success:
                try:
                    # Intento 3: Solo user + pass (a veces funciona si ya está autorizado por IP)
                    logger.info("Intento 3: login solo con user + pass")
                    list(conn(
                        cmd="/ip/hotspot/active/login",
                        **{"user": username, "password": password}
                    ))
                    success = True
                    metodo_usado = "user_pass"
                except Exception as e3:
                    logger.warning(f"Intento 3 falló: {e3}")

            # ── VERIFICACIÓN RÁPIDA (con polling corto) ─────────────────────────────
            if success:
                logger.info("[VERIFICACIÓN] Esperando y verificando sesión activa...")
                
                max_wait = 6.0
                interval = 0.8
                elapsed = 0.0
                
                while elapsed < max_wait:
                    active = list(conn(cmd='/ip/hotspot/active/print'))
                    for session in active:
                        if session.get('address') == client_ip or \
                           str(session.get('user', '')).strip().lower() == username_lower:
                            return {
                                "success": True,
                                "conectado": True,
                                "ip": session.get('address'),
                                "mac": mac,
                                "username": username,
                                "session_info": {
                                    "user": session.get('user'),
                                    "address": session.get('address'),
                                    "uptime": session.get('uptime', '0s'),
                                    "bytes-in": session.get('bytes-in', '0'),
                                    "bytes-out": session.get('bytes-out', '0')
                                },
                                "metodo_usado": metodo_usado,
                                "mensaje": f"Conexión exitosa (método: {metodo_usado})"
                            }
                    
                    time.sleep(interval)
                    elapsed += interval

            # Si llegó aquí → fallo
            return {
                "success": False,
                "conectado": False,
                "error": error_msg or "No se pudo autenticar con ninguno de los métodos",
                "mensaje": "Login directo falló después de varios intentos. Revisa logs del router."
            }

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, worker)
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
