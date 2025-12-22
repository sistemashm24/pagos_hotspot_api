from sqlalchemy import Column, String, Boolean, TIMESTAMP, Integer, ForeignKey, Index
from sqlalchemy.orm import relationship
from ..core.database import Base

class ApiKeyTracking(Base):
    __tablename__ = "api_keys_tracking"
    
    key_id = Column(String(50), primary_key=True)
    empresa_id = Column(String(50), ForeignKey("empresas.id"), nullable=False)
    router_id = Column(String(50), ForeignKey("routers.id"), nullable=False)
    key_hash = Column(String(64), unique=True, nullable=False)
    issued_at = Column(TIMESTAMP, nullable=False)
    expires_at = Column(TIMESTAMP, nullable=False)
    revoked = Column(Boolean, default=False)
    last_used = Column(TIMESTAMP)
    use_count = Column(Integer, default=0)
    
    # Relaciones
    empresa = relationship("Empresa", back_populates="api_keys")
    router = relationship("Router", back_populates="api_keys")
    
    __table_args__ = (
        Index('idx_api_keys_empresa', 'empresa_id'),
        Index('idx_api_keys_router', 'router_id'),
        Index('idx_api_keys_expires', 'expires_at'),
        Index('idx_api_keys_revoked', 'revoked')
    )
    
    def __repr__(self):
        return f"<ApiKeyTracking {self.key_id} ({'active' if not self.revoked else 'revoked'})>"