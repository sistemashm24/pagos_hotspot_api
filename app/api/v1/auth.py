from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.services.auth_service import AuthService
from app.schemas.request.auth import LoginRequest, ChangePasswordRequest
from app.schemas.response.auth import LoginResponse
from app.core.auth import AuthHandler

router = APIRouter(tags=["Authentication"])

@router.post("/login", response_model=LoginResponse)
async def login(
    login_data: LoginRequest,
    db: AsyncSession = Depends(get_db)
):
    """Login tradicional con email/contraseña → JWT sesión"""
    try:
        result = await AuthService.authenticate_user(login_data, db)
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error en login: {str(e)}"
        )

@router.post("/logout")
async def logout(
    usuario = Depends(AuthHandler.authenticate_user_session)
):
    """Cerrar sesión"""
    return {"message": "Sesión cerrada exitosamente"}

@router.post("/change-password")
async def change_password(
    password_data: ChangePasswordRequest,
    usuario = Depends(AuthHandler.authenticate_user_session),
    db: AsyncSession = Depends(get_db)
):
    """Cambiar contraseña del usuario actual"""
    try:
        # Verificar contraseña actual
        if not AuthHandler.verify_user_password(
            password_data.current_password, 
            usuario.password_hash
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Contraseña actual incorrecta"
            )
        
        # Hashear nueva contraseña
        nueva_hash = AuthHandler.hash_user_password(password_data.new_password)
        
        # Actualizar en base de datos
        usuario.password_hash = nueva_hash
        await db.commit()
        
        return {"message": "Contraseña actualizada exitosamente"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al cambiar contraseña: {str(e)}"
        )