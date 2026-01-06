from sqlalchemy import Column, String, Boolean, TIMESTAMP, text
from sqlalchemy.orm import relationship
import uuid
from ..core.database import Base

class Empresa(Base):
    __tablename__ = "empresas"
    
    id = Column(String(50), primary_key=True, default=lambda: f"EMP_{uuid.uuid4().hex[:10].upper()}")
    nombre = Column(String(100), nullable=False)
    contacto_email = Column(String(100))
    contacto_telefono = Column(String(20))
    
    # CONFIGURACIÓN CONEKTA DEL CLIENTE
    conekta_private_key = Column(String(100), nullable=False)
    conekta_public_key = Column(String(100), nullable=False)
    conekta_mode = Column(String(10), default="test")
            
    # Campos Mercado Pago
    mercado_pago_access_token = Column(String(255), nullable=True)
    mercado_pago_public_key = Column(String(255), nullable=True)
    mercado_pago_mode = Column(String(20), default='test')  # 'test' o 'live'

      # NUEVO: CLAVE SECRETA PARA WEBHOOK (IMPORTANTE)
    mercado_pago_webhook_secret = Column(String(255), nullable=True)

    activa = Column(Boolean, default=True)
    creada_en = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))
    
    # Relaciones
    routers = relationship("Router", back_populates="empresa", cascade="all, delete-orphan")
    usuarios = relationship("Usuario", back_populates="empresa")
    productos = relationship("Producto", back_populates="empresa")
    transacciones = relationship("Transaccion", back_populates="empresa")
    api_keys = relationship("ApiKeyTracking", back_populates="empresa")
    
    def __repr__(self):
        return f"<Empresa {self.nombre} ({self.id})>"