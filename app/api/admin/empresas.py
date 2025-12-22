# app/api/admin/empresas.py
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import uuid
from datetime import datetime
from typing import Optional

from app.core.database import get_db
from app.core.auth import require_super_admin
from app.models.empresa import Empresa
from app.models.usuario import Usuario

router = APIRouter()

# ========== SCHEMAS ==========
class EmpresaCreateRequest(BaseModel):
    nombre: str
    contacto_email: str
    contacto_telefono: Optional[str] = None
    conekta_private_key: str = "key_test_default"
    conekta_public_key: str = "key_test_default_pub"
    conekta_mode: str = "test"

class EmpresaResponse(BaseModel):
    id: str
    nombre: str
    contacto_email: str
    contacto_telefono: Optional[str] = None
    conekta_mode: str
    activa: bool
    creada_en: datetime
    
    class Config:
        from_attributes = True

# ========== ENDPOINTS EMPRESAS ==========
@router.post("/empresas", response_model=EmpresaResponse)
async def crear_empresa(
    empresa_data: EmpresaCreateRequest,
    usuario = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    """Crear nueva empresa (SOLO SUPER_ADMIN)"""
    empresa_id = f"EMP_{uuid.uuid4().hex[:10].upper()}"
    
    empresa = Empresa(
        id=empresa_id,
        nombre=empresa_data.nombre,
        contacto_email=empresa_data.contacto_email,
        contacto_telefono=empresa_data.contacto_telefono,
        conekta_private_key=empresa_data.conekta_private_key,
        conekta_public_key=empresa_data.conekta_public_key,
        conekta_mode=empresa_data.conekta_mode,
        activa=True
    )
    
    db.add(empresa)
    await db.commit()
    await db.refresh(empresa)
    
    return empresa

@router.get("/empresas", response_model=list[EmpresaResponse])
async def listar_empresas(
    usuario = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    """Listar todas las empresas (SOLO SUPER_ADMIN)"""
    result = await db.execute(select(Empresa))
    empresas = result.scalars().all()
    return empresas

@router.get("/dashboard")
async def dashboard_global(
    usuario = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    """Dashboard global con estadísticas (SOLO SUPER_ADMIN)"""
    # Estadísticas
    empresas_result = await db.execute(
        select(func.count(Empresa.id))
    )
    total_empresas = empresas_result.scalar()
    
    usuarios_result = await db.execute(
        select(func.count(Usuario.id))
    )
    total_usuarios = usuarios_result.scalar()
    
    empresas_activas_result = await db.execute(
        select(func.count(Empresa.id)).where(Empresa.activa == True)
    )
    empresas_activas = empresas_activas_result.scalar()
    
    return {
        "estadisticas": {
            "total_empresas": total_empresas,
            "empresas_activas": empresas_activas,
            "total_usuarios": total_usuarios
        },
        "timestamp": datetime.utcnow().isoformat()
    }