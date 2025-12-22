from sqlalchemy import Column, String, Boolean, TIMESTAMP, Integer, Text, text, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import relationship
import uuid
from ..core.database import Base

class Router(Base):
    __tablename__ = "routers"
    
    id = Column(String(50), primary_key=True, default=lambda: f"RTR_{uuid.uuid4().hex[:8].upper()}")
    empresa_id = Column(String(50), ForeignKey("empresas.id"), nullable=False)
    nombre = Column(String(100), nullable=False)
    
    # Conexión MikroTik
    host = Column(String(50), nullable=False)
    puerto = Column(Integer, default=8728)
    usuario = Column(String(50), nullable=False)
    password_encrypted = Column(Text, nullable=False)
    ubicacion = Column(String(200))
    
    # API Key específica (JWT hash)
    api_key_hash = Column(String(64), unique=True, nullable=False)
    
    activo = Column(Boolean, default=True)
    creado_en = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))
    
    # Relaciones
    empresa = relationship("Empresa", back_populates="routers")
    productos = relationship("Producto", back_populates="router")
    transacciones = relationship("Transaccion", back_populates="router")
    api_keys = relationship("ApiKeyTracking", back_populates="router")
    
    __table_args__ = (
        UniqueConstraint('empresa_id', 'id', name='uix_empresa_router'),
        Index('idx_routers_empresa', 'empresa_id'),
        Index('idx_routers_activo', 'activo')
    )
    
    def __repr__(self):
        return f"<Router {self.nombre} ({self.id})>"