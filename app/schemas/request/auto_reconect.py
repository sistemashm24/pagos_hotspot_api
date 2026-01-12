# app/schemas/request/hotspot.py
from pydantic import BaseModel, Field
from typing import Optional

class AutoReconnectRequest(BaseModel):
    """Request para reconexión automática - API Key viene en header"""
    username: str = Field(..., description="Usuario hotspot guardado en localStorage")
    password: str = Field("", description="Contraseña (puede estar vacía para usuarios PIN)")
    stored_mac: Optional[str] = Field(None, description="MAC anterior guardada en localStorage")
    current_mac: str = Field(..., description="Nueva MAC actual del dispositivo")
    current_ip: Optional[str] = Field(None, description="IP actual del dispositivo")
    current_ssid: Optional[str] = Field(None, description="SSID actual de conexión")
    # NOTA: api_key NO va aquí, viene en el header Authorization

class AutoReconnectResponse(BaseModel):
    """Respuesta estandarizada para reconexión automática"""
    success: bool
    estado: str  # "activo", "expirado", "error"
    auto_conexion: str  # "conectado", "no_conectado"
    datos_sesion: Optional[dict] = None
    nueva_mac: Optional[str] = None
    tiempo_acumulado: Optional[str] = None
    tiempo_restante: Optional[str] = None
    primera_sesion: Optional[str] = None
    mensaje: Optional[str] = None
    error_detalle: Optional[str] = None
    timestamp: str