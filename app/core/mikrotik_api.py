# app/core/mikrotik_api.py
import logging
import socket
import ssl
import time
import functools
import threading
from typing import List, Dict, Any
from librouteros import connect
from librouteros.exceptions import TrapError, LibRouterosError

logger = logging.getLogger("mikrotik")

class MikrotikConnectionError(Exception):
    """Excepción personalizada para errores de conexión MikroTik"""
    pass

def auto_reconnect(method):
    """Decorador para reconexión automática"""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception as e:
            error_types = (
                ConnectionResetError, ConnectionError, ConnectionAbortedError,
                ConnectionRefusedError, socket.error, socket.timeout,
                TimeoutError, BrokenPipeError, OSError, LibRouterosError,
                TrapError
            )
            
            if isinstance(e, error_types):
                print(f"🔌 Error de conexión detectado, reconectando...")
                self.reconnect()
                return method(self, *args, kwargs)
            raise
    return wrapper

class MikrotikAPI:
    """Clase de conexión MikroTik con reconexión automática"""
    
    def __init__(self, ip: str, port: int, username: str, password: str, timeout: int = 30):
        self.ip = ip
        self.port = port
        self.username = username
        self.password = password
        self.timeout = timeout
        self.connection = None
        self.use_ssl = (port == 8729)
    
    def _connect_with_timeout(self):
        """Conectar con timeout forzado"""
        result = {'connection': None, 'error': None}
        
        def _connect_thread():
            try:
                print(f"Conectando a {self.ip}:{self.port}...")
                
                if self.use_ssl:
                    def ssl_wrapper(sock):
                        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                        context.check_hostname = False
                        context.verify_mode = ssl.CERT_NONE
                        return context.wrap_socket(sock, server_hostname=self.ip)
                    
                    conn = connect(
                        host=self.ip,
                        username=self.username,
                        password=self.password,
                        port=self.port,
                        timeout=self.timeout,
                        ssl_wrapper=ssl_wrapper
                    )
                else:
                    conn = connect(
                        host=self.ip,
                        username=self.username,
                        password=self.password,
                        port=self.port,
                        timeout=self.timeout
                    )
                
                result['connection'] = conn
                print(f"✅ Conexión exitosa a {self.ip}:{self.port}")
                
            except Exception as e:
                result['error'] = e
                print(f"❌ Error en conexión: {type(e).__name__}: {e}")
        
        # Ejecutar en thread
        thread = threading.Thread(target=_connect_thread, daemon=True)
        thread.start()
        thread.join(timeout=self.timeout)
        
        if thread.is_alive():
            raise MikrotikConnectionError(f"Timeout al conectar a {self.ip}:{self.port}")
        if result['error']:
            raise result['error']
        if not result['connection']:
            raise MikrotikConnectionError("Error desconocido al conectar")
        
        return result['connection']
    
    def open(self):
        """Abrir conexión"""
        if not all([self.ip, self.port, self.username, self.password]):
            raise MikrotikConnectionError("Faltan datos de conexión")
        
        try:
            self.connection = self._connect_with_timeout()
        except Exception as e:
            raise MikrotikConnectionError(f"Error al conectar: {e}")
    
    def close(self):
        """Cerrar conexión"""
        if self.connection:
            try:
                self.connection.close()
            except:
                pass
            finally:
                self.connection = None
    
    def reconnect(self, max_attempts=3):
        """Reintentar conexión"""
        for attempt in range(max_attempts):
            try:
                self.close()
                self.open()
                return
            except Exception as e:
                if attempt == max_attempts - 1:
                    raise MikrotikConnectionError(f"No se pudo reconectar después de {max_attempts} intentos: {e}")
                time.sleep(2)
    
    def is_opened(self) -> bool:
        """Verificar si la conexión está activa"""
        if not self.connection:
            return False
        try:
            list(self.connection(cmd="/system/identity/print"))
            return True
        except:
            return False
    
    @auto_reconnect
    def get_hotspot_profiles(self) -> List[Dict[str, Any]]:
        """Obtener perfiles hotspot"""
        if not self.is_opened():
            raise MikrotikConnectionError("Conexión no abierta")
        
        try:
            profiles = self.connection(cmd="/ip/hotspot/user/profile/print")
            return [
                {
                    ".id": p.get(".id", ""),
                    "name": p.get("name", ""),
                    "session-timeout": p.get("session-timeout"),
                    "idle-timeout": p.get("idle-timeout"),
                    "rate-limit": p.get("rate-limit"),
                    "address-list": p.get("address-list"),
                    "shared-users": p.get("shared-users"),
                    "keepalive-timeout": p.get("keepalive-timeout")
                }
                for p in profiles
            ]
        except Exception as e:
            raise Exception(f"Error al obtener perfiles: {e}")
    
    def __enter__(self):
        self.open()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()