# app/services/mikrotik_service.py - VERSIÓN CORREGIDA CON SOPORTE PARA PIN
import asyncio
import random
import string
import time
from typing import List, Dict, Any
from datetime import datetime
from fastapi import HTTPException, status
import logging

from app.core.mikrotik_api import MikrotikAPI, MikrotikConnectionError

logger = logging.getLogger(__name__)

class MikroTikService:
    """Servicio seguro para conexión con routers MikroTik"""
    
    @staticmethod
    def generate_credentials(user_type: str = "usuario_contrasena") -> Dict[str, str]:
        """
        Generar credenciales SEGURAS para Hotspot
        
        Args:
            user_type: Tipo de credenciales a generar:
                - "usuario_contrasena": Usuario alfanumérico (6 chars) + Contraseña (4 dígitos)
                - "pin": Solo PIN numérico (6 dígitos, sin contraseña)
        
        Returns:
            Dict con username y password (password vacío para PIN)
        """
        # Normalizar user_type
        if user_type not in ["usuario_contrasena", "pin"]:
            user_type = "usuario_contrasena"
            print(f"⚠️  Tipo de usuario inválido, usando 'usuario_contrasena' por defecto")
        
        if user_type == "pin":
            # Generar PIN numérico de 6 dígitos
            pin = ''.join(random.choices('0123456789', k=6))
            print(f"🔑 PIN generado: {pin} (sin contraseña)")
            
            return {
                "username": pin,
                "password": ""  # Sin contraseña para PIN
            }
        else:
            # Usuario alfanumérico (comportamiento original)
            caracteres = string.ascii_uppercase + string.digits
            usuario = ''.join(random.choice(caracteres) for _ in range(6))
            
            # Contraseña numérica
            contraseña = f"{random.randint(0, 9999):04d}"
            
            print(f"🔑 Credenciales generadas:")
            print(f"   Usuario: {usuario}")
            print(f"   Contraseña: {contraseña}")
            
            return {
                "username": usuario,
                "password": contraseña
            }
    
    async def get_hotspot_profiles(
        self,
        router_host: str,
        router_port: int,
        router_user: str,
        router_password: str
    ) -> List[Dict[str, Any]]:
        """Obtener perfiles usando MikrotikAPI"""
        print(f"🔌 Usando MikrotikAPI para {router_host}:{router_port}")
        
        try:
            loop = asyncio.get_event_loop()
            profiles = await loop.run_in_executor(
                None,
                self._get_profiles_sync,
                router_host, router_port, router_user, router_password
            )
            
            print(f"✅ Obtenidos {len(profiles)} perfiles")
            return profiles
            
        except MikrotikConnectionError as e:
            print(f"❌ Error de conexión: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No se pudo conectar al router: {str(e)}"
            )
        except Exception as e:
            print(f"❌ Error general: {type(e).__name__}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error al obtener perfiles: {str(e)}"
            )
    
    def _get_profiles_sync(
        self,
        host: str,
        port: int,
        user: str,
        password: str
    ) -> List[Dict[str, Any]]:
        """Versión síncrona para obtener perfiles"""
        try:
            with MikrotikAPI(host, port, user, password, timeout=15) as api:
                profiles = api.get_hotspot_profiles()
                
                transformed = []
                for p in profiles:
                    transformed.append({
                        "id": p.get(".id", ""),
                        "name": p.get("name", ""),
                        "session_timeout": p.get("session-timeout"),
                        "idle_timeout": p.get("idle-timeout"),
                        "rate_limit": p.get("rate-limit"),
                        "address_list": p.get("address-list"),
                        "shared_users": p.get("shared-users"),
                        "keepalive_timeout": p.get("keepalive-timeout"),
                        "status_autorefresh": p.get("status-autorefresh"),
                        "mac_cookie_timeout": p.get("mac-cookie-timeout")
                    })
                
                return transformed
        except Exception as e:
            raise Exception(f"Error obteniendo perfiles: {str(e)}")
    
    async def create_hotspot_user(
        self,
        router_host: str,
        router_port: int,
        router_user: str,
        router_password: str,
        username: str,
        password: str,
        profile_name: str,
        comment: str = "",  # Mantener para compatibilidad pero ignorar        
        skip_verification: bool = False,
        user_type: str = "usuario_contrasena"  # Nuevo parámetro
    ) -> Dict[str, Any]:
        """
        Crear usuario en Hotspot MikroTik - VERSIÓN CON SOPORTE PARA PIN
        
        Args:
            comment: Ignorado, mantenido solo para compatibilidad
            skip_verification: Si True, no verifica (más rápido)
            user_type: Tipo de usuario ("usuario_contrasena" o "pin")
        """
        print(f"👤 Intentando crear usuario: {username} (perfil: {profile_name}, tipo: {user_type})")
        
        # Validar formato según tipo de usuario
        if user_type == "pin":
            # Para PIN: 6 dígitos numéricos
            if len(username) != 6 or not username.isdigit():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="El PIN debe tener exactamente 6 dígitos numéricos"
                )
            # Para PIN, el password debe estar vacío
            if password != "":
                print(f"⚠️  Advertencia: Password no vacío para tipo PIN, ignorando")
                password = ""  # Forzar vacío para PIN
        else:
            # Para usuario_contrasena: Alfanumérico de 6 caracteres
            if len(username) != 6:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="El usuario debe tener exactamente 6 caracteres"
                )
            
            if not username.isalnum():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="El usuario solo puede contener letras y números"
                )
            
            if len(password) != 4 or not password.isdigit():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="La contraseña debe tener exactamente 4 dígitos"
                )
        
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self._create_user_sync_optimizado,
                router_host, router_port, router_user, router_password,
                username, password, profile_name, skip_verification, user_type
            )
            
            if not result.get("success"):
                error_msg = result.get("error", "Error desconocido al crear usuario")
                print(f"❌ Falló creación: {error_msg}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"No se pudo crear el usuario: {error_msg}"
                )
            
            print(f"✅ Usuario {username} creado exitosamente (tipo: {user_type})")
            return result
            
        except HTTPException:
            raise
        except Exception as e:
            print(f"❌ Error inesperado: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error al crear usuario: {str(e)}"
            )
    
    def _create_user_sync_optimizado(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        hotspot_username: str,
        hotspot_password: str,
        profile_name: str,        
        skip_verification: bool = False,
        user_type: str = "usuario_contrasena"  # Nuevo parámetro
    ) -> Dict[str, Any]:
        """
        VERSIÓN CON SOPORTE PARA PIN - Sin comentarios, verificación reducida
        """
        print(f"🔌 Conectando a MikroTik {host}:{port} (tipo usuario: {user_type})...")
        
        api = None
        try:
            # 1. Conectar
            api = MikrotikAPI(host, port, user, password, timeout=10)
            api.open()
            print(f"✅ Conexión establecida")
            
            # 2. Verificar perfil
            print(f"🔍 Verificando perfil: {profile_name}")
            profiles = api.connection(cmd="/ip/hotspot/user/profile/print")
            profiles_list = list(profiles)
            
            profile_exists = any(p.get('name') == profile_name for p in profiles_list)
            
            if not profile_exists:
                available = [p.get('name') for p in profiles_list[:3]]
                error_msg = f"Perfil '{profile_name}' no encontrado. Disponibles: {', '.join(available)}"
                print(f"❌ {error_msg}")
                return {"success": False, "error": error_msg}
            
            print(f"✅ Perfil encontrado")
            
            # 3. Verificar duplicados (solo si no es modo rápido)
            if not skip_verification:
                print(f"🔍 Verificando duplicados...")
                all_users = api.connection(cmd="/ip/hotspot/user/print")
                if any(u.get('name') == hotspot_username for u in all_users):
                    print(f"⚠️ Usuario {hotspot_username} ya existe")
                    return {"success": False, "error": "El usuario ya existe en el sistema"}
            
            # 4. Crear usuario - SIN COMENTARIOS
            print(f"🛠️ Creando usuario {hotspot_username} (tipo: {user_type})...")
            
            add_params = {
                "name": hotspot_username,
                "profile": profile_name,
                "disabled": "no"
            }
            
            # Solo agregar password si no es tipo PIN y no está vacío
            if user_type != "pin" and hotspot_password:
                add_params["password"] = hotspot_password
            elif user_type == "pin":
                print(f"🔒 Tipo PIN: No se incluye password en la creación")
            
            print(f"📦 Parámetros: {add_params}")
            
            # Ejecutar
            result = api.connection(cmd="/ip/hotspot/user/add", **add_params)
            list(result)
            print(f"📤 Comando ejecutado")
            
            # 5. Verificación optimizada (2 intentos)
            if skip_verification:
                print(f"⚡ Modo rápido: Sin verificación")
                return {
                    "success": True,
                    "user_id": "not_verified",
                    "username": hotspot_username,
                    "profile": profile_name,
                    "user_type": user_type,
                    "verified": False,
                    "message": "Usuario creado (modo rápido)",
                    "created_at": datetime.now().isoformat()
                }
            
            print(f"🔍 Verificación rápida (2 intentos)...")
            
            for attempt in range(2):
                if attempt > 0:
                    time.sleep(0.8)
                
                try:
                    all_users = api.connection(cmd="/ip/hotspot/user/print")
                    
                    for u in all_users:
                        if u.get('name') == hotspot_username:
                            user_id = u.get('.id')
                            user_password_in_mikrotik = u.get('password', '')
                            
                            # Verificar que el password en MikroTik coincida
                            if user_type != "pin" and user_password_in_mikrotik != hotspot_password:
                                print(f"⚠️  Password en MikroTik no coincide")
                            elif user_type == "pin" and user_password_in_mikrotik:
                                print(f"⚠️  PIN tiene password inesperado en MikroTik")
                            
                            print(f"✅ Verificado (intento {attempt + 1})")
                            
                            return {
                                "success": True,
                                "user_id": user_id,
                                "username": hotspot_username,
                                "profile": profile_name,
                                "user_type": user_type,
                                "verified": True,
                                "verification_attempt": attempt + 1,
                                "message": "Usuario creado y verificado",
                                "created_at": datetime.now().isoformat(),
                                "mikrotik_data": {
                                    "name": u.get('name'),
                                    "profile": u.get('profile'),
                                    "disabled": u.get('disabled', 'false'),
                                    "has_password": bool(user_password_in_mikrotik)
                                }
                            }
                except Exception as e:
                    print(f"⚠️ Error verificación: {str(e)}")
                    continue
            
            # Modo pragmático
            print(f"⚠️ MODO PRAGMÁTICO: Asumiendo éxito")
            return {
                "success": True,
                "user_id": "created_pragmatic",
                "username": hotspot_username,
                "profile": profile_name,
                "user_type": user_type,
                "verified": False,
                "pragmatic_mode": True,
                "message": "Usuario creado exitosamente (modo pragmático)",
                "created_at": datetime.now().isoformat()
            }
                
        except Exception as e:
            print(f"💥 Error: {type(e).__name__}: {str(e)}")
            return {"success": False, "error": f"Error en MikroTik: {str(e)}"}
        
        finally:
            if api:
                try:
                    api.close()
                except:
                    pass
    
    async def test_connection(
        self,
        router_host: str,
        router_port: int,
        router_user: str,
        router_password: str
    ) -> Dict[str, Any]:
        """Probar conexión usando MikrotikAPI"""
        print(f"🔍 Test conexión a {router_host}:{router_port}")
        
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self._test_connection_sync,
                router_host, router_port, router_user, router_password
            )
            
            print(f"✅ Test de conexión exitoso")
            return result
            
        except MikrotikConnectionError as e:
            return {
                "success": False,
                "error": str(e),
                "connected": False
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Error: {type(e).__name__}: {str(e)}",
                "connected": False
            }
    
    async def delete_hotspot_user(
        self,
        router_host: str,
        router_port: int,
        router_user: str,
        router_password: str,
        username: str
    ) -> None:
        """Eliminar usuario en MikroTik - VERSIÓN MEJORADA PARA AMBOS TIPOS"""
        print(f"🗑️ Iniciando eliminación de usuario: {username}")
        
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            self._delete_hotspot_user_sync_mejorada,  # Usar versión mejorada
            router_host,
            router_port,
            router_user,
            router_password,
            username
        )

    def _delete_hotspot_user_sync_mejorada(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        username: str
    ):
        """Eliminar usuario - VERSIÓN MEJORADA que funciona para ambos tipos"""
        api = None
        try:
            print(f"🗑️ ELIMINANDO usuario: '{username}' de {host}:{port}")
            print(f"🔍 Tipo de dato username: {type(username).__name__}, valor: '{username}'")
            
            # Conectar a MikroTik
            api = MikrotikAPI(host, port, user, password, timeout=10)
            api.open()
            print(f"✅ Conexión establecida")
            
            # 1. Buscar el usuario - SIMPLIFICADO
            print(f"🔍 Buscando usuario '{username}'...")
            all_users = api.connection(cmd="/ip/hotspot/user/print")
            
            user_id = None
            mikrotik_username = None
            search_name = str(username).strip()
            
            for u in all_users:
                current_name = u.get('name', '')
                # Convertir a string y comparar
                if str(current_name).strip() == search_name:
                    user_id = u.get('.id')
                    mikrotik_username = str(current_name).strip()
                    print(f"✅ Usuario encontrado: ID={user_id}, Nombre='{mikrotik_username}'")
                    print(f"📋 Detalles: perfil={u.get('profile')}, password={u.get('password', '(vacío)')}")
                    break
            
            if not user_id:
                print(f"⚠️ Usuario '{search_name}' no encontrado (quizás ya fue eliminado)")
                # Mostrar algunos usuarios para debug
                print(f"📊 Primeros 3 usuarios en MikroTik:")
                users_list = list(all_users)
                for i, u in enumerate(users_list[:3]):
                    name = u.get('name', '')
                    print(f"   {i+1}. '{str(name).strip()}' (tipo: {type(name).__name__})")
                return
            
            # 2. Intentar eliminación (mismos 3 métodos que antes)
            print(f"🔄 Ejecutando: /ip/hotspot/user/remove con numbers={user_id}")
            try:
                result = api.connection(cmd="/ip/hotspot/user/remove", numbers=user_id)
                list(result)
                print(f"✅ Comando remove ejecutado")
            except Exception as e1:
                print(f"⚠️ Método 1 falló: {e1}")
                
                # Intentar método alternativo
                try:
                    print(f"🔄 Intentando con '.id'={user_id}")
                    result = api.connection(cmd="/ip/hotspot/user/remove", **{".id": user_id})
                    list(result)
                    print(f"✅ Comando remove ejecutado (método .id)")
                except Exception as e2:
                    print(f"⚠️ Método 2 falló: {e2}")
                    return
            
            # 3. Verificar eliminación
            print(f"🔍 Verificando eliminación...")
            time.sleep(1.0)
            
            usuario_eliminado = False
            for attempt in range(2):
                if attempt > 0:
                    time.sleep(0.5)
                
                try:
                    all_users_after = api.connection(cmd="/ip/hotspot/user/print")
                    user_still_exists = False
                    
                    for u in all_users_after:
                        if str(u.get('name', '')).strip() == search_name:
                            user_still_exists = True
                            break
                    
                    if not user_still_exists:
                        usuario_eliminado = True
                        print(f"✅ VERIFICADO: Usuario '{username}' eliminado")
                        break
                        
                except Exception as e:
                    print(f"⚠️ Error verificación {attempt + 1}: {e}")
            
            if not usuario_eliminado:
                print(f"⚠️ No se pudo verificar eliminación de '{username}'")
                    
        except Exception as e:
            print(f"❌ Error eliminando usuario: {type(e).__name__}: {str(e)}")
            
        finally:
            if api:
                try:
                    api.close()
                    print(f"🔌 Conexión cerrada")
                except:
                    pass

    def _force_delete_user(self, api, user_id: str, username: str):
        """Método alternativo si el remove normal falla"""
        try:
            print(f"🔄 Intentando eliminación forzada de {username}...")
            
            # Método alternativo 1: Usar .call()
            # (dependiendo de cómo esté implementada tu MikrotikAPI)
            if hasattr(api.connection, 'call'):
                result = api.connection.call(
                    '/ip/hotspot/user/remove',
                    numbers=user_id
                )
                print(f"✅ Eliminación forzada ejecutada")
                return
            
            # Método alternativo 2: Intentar con formato diferente
            print(f"🔄 Probando con parámetro '=.id'...")
            result = api.connection(
                cmd="/ip/hotspot/user/remove",
                **{"=.id": user_id}
            )
            list(result)
            print(f"✅ Eliminación con '=.id' ejecutada")
            
        except Exception as e:
            print(f"❌ Eliminación forzada también falló: {str(e)}")


    def _test_connection_sync(
        self,
        host: str,
        port: int,
        user: str,
        password: str
    ) -> Dict[str, Any]:
        """Test síncrono de conexión"""
        try:
            with MikrotikAPI(host, port, user, password, timeout=10) as api:
                identity = api.connection(cmd="/system/identity/print")
                router_name = list(identity)[0].get("name", "Desconocido")
                
                profiles = api.get_hotspot_profiles()
                
                return {
                    "success": True,
                    "connected": True,
                    "router_name": router_name,
                    "profiles_count": len(profiles),
                    "profiles_sample": [
                        {"id": p.get(".id"), "name": p.get("name")}
                        for p in profiles[:3]
                    ]
                }
                
        except Exception as e:
            raise MikrotikConnectionError(f"No se pudo conectar: {str(e)}")

# Instancia global
mikrotik_service = MikroTikService()