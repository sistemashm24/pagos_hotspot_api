from sqlalchemy import Column, Integer, String, Boolean, TIMESTAMP, Text, DECIMAL, ForeignKey, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy import text
from ..core.database import Base

class Producto(Base):
    __tablename__ = "productos"
    
    id = Column(Integer, primary_key=True)
    empresa_id = Column(String(50), ForeignKey("empresas.id"), nullable=False)
    router_id = Column(String(50), ForeignKey("routers.id"), nullable=False)
    
    # 🔗 RELACIÓN CON PERFIL MIKROTIK (EXACTO)
    perfil_mikrotik_id = Column(String(100), nullable=False)
    perfil_mikrotik_nombre = Column(String(100), nullable=False)
    
    # 🛍️ DATOS COMERCIALES
    nombre_venta = Column(String(100), nullable=False)
    descripcion = Column(Text)
    imagen_url = Column(String(500))
    precio = Column(DECIMAL(10, 2), nullable=False)
    moneda = Column(String(3), default="MXN")
    detalles = Column(JSONB, default=[])
    
    # ⚙️ CONFIGURACIÓN VISUAL
    activo = Column(Boolean, default=True)
    orden_visual = Column(Integer, default=0)
    destacado = Column(Boolean, default=False)
    
    # 📅 METADATA
    creado_en = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))
    
    # Relaciones
    empresa = relationship("Empresa", back_populates="productos")
    router = relationship("Router", back_populates="productos")
    transacciones = relationship("Transaccion", back_populates="producto")
    
    __table_args__ = (
        UniqueConstraint('empresa_id', 'router_id', 'perfil_mikrotik_id', 
                        name='uix_empresa_router_perfil'),
        Index('idx_productos_empresa', 'empresa_id'),
        Index('idx_productos_router', 'router_id'),
        Index('idx_productos_activo', 'activo'),
        Index('idx_productos_orden', 'orden_visual')
    )
    
    def __repr__(self):
        return f"<Producto {self.nombre_venta} ({self.precio} {self.moneda})>"