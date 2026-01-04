# app/schemas/request/mercado_pago.py
from typing import Optional, Literal
from pydantic import BaseModel, EmailStr, Field

class MercadoPagoPaymentRequest(BaseModel):
    product_id: int = Field(..., alias="producto_id")
    payment_method_id: str = Field(..., alias="payment_method_id")
    token: str = Field(..., alias="token")
    issuer_id: Optional[str] = Field(None, alias="issuer_id")
    transaction_amount: float = Field(..., alias="monto")
    installments: int = Field(1, alias="cuotas")
    customer_name: str = Field(..., alias="nombre_cliente")
    customer_email: EmailStr = Field(..., alias="email_cliente")
    customer_phone: Optional[str] = Field(None, alias="telefono_cliente")
    
    # Tipo de usuario (igual que Conekta)
    user_type: Optional[Literal["usuario_contrasena", "pin"]] = Field(
        "usuario_contrasena", 
        alias="tipo_usuario",
        description="Tipo de credenciales a generar"
    )
    
    # Campos para conexión automática
    mac_address: Optional[str] = Field(None, alias="mac_cliente")
    ip_address: Optional[str] = Field(None, alias="ip_cliente")
    device_info: Optional[str] = Field(None, alias="info_dispositivo")
    
    # Flag para conexión automática
    auto_connect: bool = Field(False, alias="conexion_automatica")
    
    # Información del pagador
    payer: Optional[dict] = Field(None, alias="payer")

    class Config:
        allow_population_by_field_name = True