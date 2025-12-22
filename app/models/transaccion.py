from sqlalchemy import Column, Integer, String, Boolean, TIMESTAMP, DECIMAL, ForeignKey, Index
from sqlalchemy.orm import relationship
from sqlalchemy import text
from ..core.database import Base

class Transaccion(Base):
    __tablename__ = "transacciones"
    
    id = Column(Integer, primary_key=True)
    transaccion_id = Column(String(100), unique=True)
    empresa_id = Column(String(50), ForeignKey("empresas.id"), nullable=False)
    router_id = Column(String(50), ForeignKey("routers.id"), nullable=False)
    producto_id = Column(Integer, ForeignKey("productos.id"))
    
    # Datos del pago
    monto = Column(DECIMAL(10, 2), nullable=False)
    moneda = Column(String(3), default="MXN")
    
    # Datos del cliente final
    cliente_nombre = Column(String(100))
    cliente_email = Column(String(100))
    cliente_telefono = Column(String(20))
    
    # Credenciales generadas
    usuario_hotspot = Column(String(50))
    password_hotspot = Column(String(50))
    expiracion_hotspot = Column(TIMESTAMP)
    
    # Estados
    estado_pago = Column(String(20), default="pending")
    estado_hotspot = Column(String(20), default="pending")
    
    # Auditoría
    api_key_usada = Column(String(64))
    
    # Timestamps
    creada_en = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))
    pagada_en = Column(TIMESTAMP)
    usuario_creado_en = Column(TIMESTAMP)
    
    # Relaciones
    empresa = relationship("Empresa", back_populates="transacciones")
    router = relationship("Router", back_populates="transacciones")
    producto = relationship("Producto", back_populates="transacciones")
    
    __table_args__ = (
        Index('idx_transacciones_empresa', 'empresa_id'),
        Index('idx_transacciones_router', 'router_id'),
        Index('idx_transacciones_producto', 'producto_id'),
        Index('idx_transacciones_estado_pago', 'estado_pago'),
        Index('idx_transacciones_creada_en', 'creada_en')
    )
    
    def __repr__(self):
        return f"<Transaccion {self.transaccion_id} ({self.estado_pago})>"