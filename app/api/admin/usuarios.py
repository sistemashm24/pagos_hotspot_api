# app/api/admin/usuarios.py
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import bcrypt
from typing import Optional

from app.core.database import get_db
from app.core.auth import require_super_admin
from app.models.usuario import Usuario
from app.models.empresa import Empresa
from app.schemas.request.auth import UserCreateRequest
from app.schemas.response.auth import UserResponse

router = APIRouter()

# ========== SCHEMAS ==========
class UserCreateAdminRequest(BaseModel):
    email: str
    password: str
    nombre: str
    rol: str  # "super_admin" o "cliente_admin"
    empresa_id: Optional[str] = None

# ========== ENDPOINTS USUARIOS ==========
@router.post("/usuarios", response_model=dict)
async def crear_usuario_admin(
    usuario_data: UserCreateAdminRequest,
    usuario = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Crear usuario (CLIENTE_ADMIN o SUPER_ADMIN) - SOLO SUPER_ADMIN
    
    SUPER_ADMIN puede crear:
    1. Otros SUPER_ADMIN (sin empresa_id)
    2. CLIENTE_ADMIN (con empresa_id)
    """
    # Validar rol
    if usuario_data.rol not in ["super_admin", "cliente_admin"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Rol inválido. Debe ser 'super_admin' o 'cliente_admin'"
        )
    
    # Validar empresa para cliente_admin
    if usuario_data.rol == "cliente_admin":
        if not usuario_data.empresa_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="cliente_admin requiere empresa_id"
            )
        
        # Verificar que la empresa existe
        empresa = await db.get(Empresa, usuario_data.empresa_id)
        if not empresa:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Empresa no encontrada"
            )
    else:
        # SUPER_ADMIN no debe tener empresa_id
        if usuario_data.empresa_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="super_admin no debe tener empresa_id"
            )
    
    # Verificar si email ya existe
    result = await db.execute(
        select(Usuario).where(Usuario.email == usuario_data.email)
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El email ya está registrado"
        )
    
    # Hashear contraseña
    hashed_password = bcrypt.hashpw(
        usuario_data.password.encode('utf-8'),
        bcrypt.gensalt()
    ).decode('utf-8')
    
    # Crear usuario
    nuevo_usuario = Usuario(
        email=usuario_data.email,
        password_hash=hashed_password,
        nombre=usuario_data.nombre,
        rol=usuario_data.rol,
        empresa_id=usuario_data.empresa_id,
        activo=True
    )
    
    db.add(nuevo_usuario)
    await db.commit()
    await db.refresh(nuevo_usuario)
    
    return {
        "message": "Usuario creado exitosamente",
        "usuario": UserResponse.from_orm(nuevo_usuario)
    }

@router.get("/usuarios", response_model=list[UserResponse])
async def listar_usuarios_admin(
    rol: Optional[str] = None,
    empresa_id: Optional[str] = None,
    usuario = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    """Listar usuarios (SOLO SUPER_ADMIN)"""
    query = select(Usuario)
    
    if rol:
        query = query.where(Usuario.rol == rol)
    
    if empresa_id:
        query = query.where(Usuario.empresa_id == empresa_id)
    
    result = await db.execute(query)
    usuarios = result.scalars().all()
    
    return usuarios

@router.get("/usuarios/{usuario_id}", response_model=UserResponse)
async def obtener_usuario_admin(
    usuario_id: int,
    usuario = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    """Obtener usuario específico (SOLO SUPER_ADMIN)"""
    usuario_obj = await db.get(Usuario, usuario_id)
    
    if not usuario_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado"
        )
    
    return UserResponse.from_orm(usuario_obj)

@router.put("/usuarios/{usuario_id}/toggle-activo")
async def toggle_activo_usuario(
    usuario_id: int,
    usuario = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    """Activar/desactivar usuario (SOLO SUPER_ADMIN)"""
    usuario_obj = await db.get(Usuario, usuario_id)
    
    if not usuario_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado"
        )
    
    # No permitir desactivarse a sí mismo
    if usuario_obj.id == usuario.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No puedes desactivar tu propio usuario"
        )
    
    usuario_obj.activo = not usuario_obj.activo
    await db.commit()
    await db.refresh(usuario_obj)
    
    return {
        "message": f"Usuario {'activado' if usuario_obj.activo else 'desactivado'}",
        "usuario_id": usuario_id,
        "activo": usuario_obj.activo
    }