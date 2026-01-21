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
    """Limpia el contenido del script (solo ASCII seguro)"""
    try:
        cleaned = re.sub(r'[^\x00-\x7F]', ' ', content)
        cleaned = cleaned.replace('\r\n', '\n').replace('\r', '\n')
        cleaned = re.sub(r' +', ' ', cleaned)
        cleaned = re.sub(r'\n\s*\n', '\n\n', cleaned)
        return cleaned
    except Exception:
        return content


logger = logging.getLogger("hotspot_v7")


# ============================================================================
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
    """
    Versión v7 - Login por SCRIPT + limpieza SOLO por username
    Estructura de respuesta 100% compatible con v6
    """

    logger.info(f"[START] auto-login v7 | user={username} | mac={mac_address}")

    from core.mikrotik_api import MikrotikAPI

    def worker():
        with MikrotikAPI(
            router_host,
            router_port,
            router_user,
            router_password,
            timeout=20
        ) as api:

            conn = api.connection
            mac = mac_address.lower().replace("-", ":")
            username_lower = username.strip().lower()

            logger.info(f"[1] MAC: {mac} | Username: {username_lower}")

            # ─────────────────────────────────────────────
            # LIMPIEZA PREVIA: SOLO SESIONES ACTIVAS POR USERNAME
            # ─────────────────────────────────────────────
            logger.info("[CLEAN] Eliminando sesiones activas previas por username...")

            try:
                active = list(conn(cmd='/ip/hotspot/active/print'))
                removed = 0

                for session in active:
                    s_user = str(session.get('user', '')).strip().lower()
                    if s_user == username_lower:
                        sid = session.get('.id')
                        try:
                            list(conn(cmd='/ip/hotspot/active/remove', numbers=sid))
                            removed += 1
                            logger.info(
                                f"[CLEAN] Sesión eliminada | "
                                f"ID={sid} | IP={session.get('address')} | MAC={session.get('mac-address')}"
                            )
                        except Exception as e:
                            logger.warning(f"[CLEAN] Error eliminando sesión {sid}: {e}")

                if removed:
                    logger.info(f"[CLEAN] Total sesiones eliminadas: {removed}")
                else:
                    logger.info("[CLEAN] No había sesiones activas para este usuario")

            except Exception as e:
                logger.error(f"[CLEAN] Error procesando sesiones activas: {e}")

            time.sleep(1.0)

            # ─────────────────────────────────────────────
            # OBTENER IP SI NO SE PROPORCIONA
            # ─────────────────────────────────────────────
            import ipaddress

            def is_valid_ipv4(value: str) -> bool:
                try:
                    ip = ipaddress.ip_address(value)
                    return ip.version == 4 and str(ip) != "0.0.0.0"
                except Exception:
                    return False
                
            client_ip = ip_address if is_valid_ipv4(ip_address) else None

            if not client_ip:
                logger.info("[2] Detectando IP del cliente...")
                try:
                    hosts = list(conn(cmd='/ip/hotspot/host/print'))
                    for host in hosts:
                        if host.get('mac-address', '').lower() == mac:
                            client_ip = host.get('to-address') or host.get('address')
                            if client_ip:
                                logger.info(f"[OK] IP detectada: {client_ip}")
                                break
                except Exception as e:
                    logger.error(f"[ERROR] Detectando IP: {e}")

            if not client_ip:
                return {
                    "success": False,
                    "conectado": False,
                    "error": "No se pudo detectar IP del cliente",
                    "mensaje": "El dispositivo debe estar conectado al hotspot primero"
                }

            # ─────────────────────────────────────────────
            # CREAR SCRIPT DE LOGIN (UNA SOLA VEZ)
            # ─────────────────────────────────────────────
            timestamp = int(time.time())
            script_name = f"__login_{hashlib.md5(f'{mac}_{timestamp}'.encode()).hexdigest()[:8]}"

            script_source = f""":local user "{username}"
:local pass "{password}"
:local mac "{mac}"
:local ip "{client_ip}"

/ip/hotspot/active/login user=$user password=$pass ip=$ip mac-address=$mac
"""

            script_source = clean_script_content(script_source)
            script_id = None

            try:
                # Crear script
                list(conn(
                    cmd='/system/script/add',
                    name=script_name,
                    source=script_source
                ))

                scripts = list(conn(cmd='/system/script/print'))
                script_id = next(
                    (s.get('.id') for s in scripts if s.get('name') == script_name),
                    None
                )

                if not script_id:
                    raise Exception("No se pudo obtener ID del script")

                # Ejecutar script
                list(conn(cmd='/system/script/run', **{'.id': script_id}))
                logger.info("[3] Script ejecutado")

                # ─────────────────────────────────────────
                # VERIFICACIÓN (SOLO POR USERNAME)
                # ─────────────────────────────────────────
                logger.info("[4] Verificando sesión activa...")

                max_wait = 6.0
                interval = 1.0
                elapsed = 0.0
                session_found = None

                while elapsed < max_wait:
                    active = list(conn(cmd='/ip/hotspot/active/print'))
                    for session in active:
                        if str(session.get('user', '')).strip().lower() == username_lower:
                            session_found = session
                            break

                    if session_found:
                        break

                    time.sleep(interval)
                    elapsed += interval

                # Limpieza del script (SIEMPRE)
                try:
                    list(conn(cmd='/system/script/remove', numbers=script_id))
                except Exception as e:
                    logger.warning(f"[CLEAN] No se pudo eliminar script: {e}")

                # ─────────────────────────────────────────
                # RESULTADO FINAL (CONTRATO v6)
                # ─────────────────────────────────────────
                if session_found:
                    return {
                        "success": True,
                        "conectado": True,
                        "ip": session_found.get('address'),
                        "mac": mac,
                        "username": username,
                        "session_info": {
                            "user": session_found.get('user'),
                            "address": session_found.get('address'),
                            "uptime": session_found.get('uptime', '0s'),
                            "bytes-in": session_found.get('bytes-in', '0'),
                            "bytes-out": session_found.get('bytes-out', '0')
                        },
                        "metodo_usado": "script_login",
                        "mensaje": "Conexión exitosa (método: script_login)"
                    }

                return {
                    "success": False,
                    "conectado": False,
                    "error": "Login ejecutado pero la sesión no apareció a tiempo",
                    "mensaje": "El script se ejecutó correctamente pero RouterOS no confirmó la sesión"
                }

            except Exception as e:
                msg = str(e).lower()

                # Limpieza del script SIEMPRE
                if script_id:
                    try:
                        list(conn(cmd='/system/script/remove', numbers=script_id))
                    except Exception as cleanup_err:
                        logger.warning(f"[CLEAN] No se pudo eliminar script tras error: {cleanup_err}")

                # Caso: IP/usuario ya logueado
                if "already logged in" in msg:
                    logger.warning(f"[WARN] Usuario/IP ya tenía sesión activa: {e}")
                    return {
                        "success": True,
                        "conectado": True,
                        "error": None,
                        "mensaje": "El usuario ya estaba conectado previamente"
                    }

                # Otros errores reales
                logger.error(f"[ERROR] {e}")
                return {
                    "success": False,
                    "conectado": False,
                    "error": str(e),
                    "mensaje": "Error durante el proceso de auto-login en RouterOS v7"
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
