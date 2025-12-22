# app/schemas/request/pagos.py
from typing import Optional, Literal
from pydantic import BaseModel, EmailStr, Field

class PaymentRequest(BaseModel):
    product_id: int = Field(..., alias="producto_id")
    card_token: str = Field(..., alias="token_tarjeta")
    customer_name: str = Field(..., alias="nombre_cliente")
    customer_email: EmailStr = Field(..., alias="email_cliente")
    customer_phone: Optional[str] = Field(None, alias="telefono_cliente")
    
    # Nuevo parámetro para tipo de usuario
    user_type: Optional[Literal["usuario_contrasena", "pin"]] = Field(
        "usuario_contrasena", 
        alias="tipo_usuario",
        description="""
        Tipo de credenciales a generar:
        • 'usuario_contrasena': Genera usuario y contraseña (formato tradicional)
        • 'pin': Genera solo PIN numérico de 6 dígitos (sin contraseña)
        
        Default: 'usuario_contrasena'
        """
    )
    
    # Campos para conexión automática (opcionales)
    mac_address: Optional[str] = Field(None, alias="mac_cliente")
    ip_address: Optional[str] = Field(None, alias="ip_cliente")
    device_info: Optional[str] = Field(None, alias="info_dispositivo")
    
    # Flag para conexión automática
    auto_connect: bool = Field(False, alias="conexion_automatica")

    class Config:
        allow_population_by_field_name = True