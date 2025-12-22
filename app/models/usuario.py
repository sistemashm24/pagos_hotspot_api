from sqlalchemy import Column, Integer, String, Boolean, TIMESTAMP, ForeignKey, text, CheckConstraint, Index
from sqlalchemy.orm import relationship
from ..core.database import Base

class Usuario(Base):
    __tablename__ = "usuarios"
    
    id = Column(Integer, primary_key=True)
    rol = Column(String(20), nullable=False)
    empresa_id = Column(String(50), ForeignKey("empresas.id"), nullable=True)
    
    email = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    nombre = Column(String(100), nullable=False)
    
    activo = Column(Boolean, default=True)
    ultimo_login = Column(TIMESTAMP)
    creado_en = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))
    
    # Relaciones
    empresa = relationship("Empresa", back_populates="usuarios")
    
    __table_args__ = (
        CheckConstraint(
            "rol IN ('super_admin', 'cliente_admin')",
            name="check_roles_validos"
        ),
        CheckConstraint(
            "(rol = 'cliente_admin' AND empresa_id IS NOT NULL) OR "
            "(rol = 'super_admin' AND empresa_id IS NULL)",
            name="check_empresa_required_for_cliente"
        ),
        Index('idx_usuarios_empresa', 'empresa_id'),
        Index('idx_usuarios_email', 'email'),
        Index('idx_usuarios_activo', 'activo'),
        Index('idx_usuarios_rol', 'rol')
    )
    
    def __repr__(self):
        return f"<Usuario {self.email} ({self.rol})>"