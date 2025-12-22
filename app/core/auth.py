# app/core/auth.py - COMPLETO CORREGIDO
from fastapi import Request, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional, Tuple, Dict, Any
from jose import jwt
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import hashlib
import bcrypt

from .config import settings
from ..models.usuario import Usuario
from ..models.empresa import Empresa
from ..models.router import Router
from ..models.api_key import ApiKeyTracking
from .database import get_db

security = HTTPBearer()

class AuthHandler:
    @staticmethod
    async def authenticate_api_key(
        request: Request,
        credentials: HTTPAuthorizationCredentials = Depends(security),
        db: AsyncSession = Depends(get_db)
    ) -> Tuple[Empresa, Router, Dict[str, Any]]:
        """
        Autenticación por API Key JWT de router
        Header: X-API-Key: jwt_eyJ0eXAiOiJKV1NiJ9...
        """
        try:
            token = credentials.credentials
            
            if not token.startswith("jwt_"):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Formato de API Key inválido"
                )
            
            token = token[4:]  # Remover prefijo "jwt_"
            
            # Verificar JWT
            try:
                payload = jwt.decode(
                    token,
                    settings.JWT_APIKEY_SECRET,
                    algorithms=[settings.JWT_ALGORITHM]
                )
            except jwt.ExpiredSignatureError:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="API Key expirada"
                )
            except jwt.InvalidTokenError:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="API Key inválida"
                )
            
            # Verificar en tabla de tracking
            key_hash = hashlib.sha256(token.encode()).hexdigest()
            result = await db.execute(
                select(ApiKeyTracking)
                .where(ApiKeyTracking.key_hash == key_hash)
                .where(ApiKeyTracking.revoked == False)
            )
            api_key = result.scalar_one_or_none()
            
            if not api_key:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="API Key no válida o revocada"
                )
            
            # Obtener empresa y router
            empresa = await db.get(Empresa, api_key.empresa_id)
            router = await db.get(Router, api_key.router_id)
            
            if not empresa or not empresa.activa:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Empresa no activa"
                )
            
            # Actualizar tracking
            api_key.last_used = datetime.utcnow()
            api_key.use_count += 1
            await db.commit()
            
            return empresa, router, {"api_key_id": api_key.key_id, "jwt_payload": payload}
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error en autenticación: {str(e)}"
            )
        
    # app/core/auth.py - FUNCIÓN CORREGIDA COMPLETA
    @staticmethod
    async def authenticate_user_session(
        credentials: HTTPAuthorizationCredentials = Depends(security),
        db: AsyncSession = Depends(get_db)
    ) -> Usuario:
        """
        Autenticación por JWT de sesión de usuario
        """
        try:
            token = credentials.credentials
            
            # Decodificar JWT
            payload = jwt.decode(
                token,
                settings.JWT_SESSION_SECRET,
                algorithms=[settings.JWT_ALGORITHM]
            )
            
            # Obtener usuario
            user_id = payload.get("sub")
            if not user_id:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token inválido"
                )
            
            # ¡¡¡CORRECCIÓN 1: Convertir user_id de string a int!!!
            result = await db.execute(
                select(Usuario).where(Usuario.id == int(user_id))  # ← AQUÍ
            )
            usuario = result.scalar_one_or_none()
            
            if not usuario or not usuario.activo:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Usuario no activo"
                )
            
            return usuario
            
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token expirado"
            )
        # ¡¡¡CORRECCIÓN 2: Cambiar jwt.InvalidTokenError por JWTError!!!
        except jwt.JWTError:  # ← AQUÍ (o simplemente 'except Exception' si prefieres)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token inválido"
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error en autenticación: {str(e)}"
            )
    

    @staticmethod
    def verify_user_password(password: str, hashed_password: str) -> bool:
        """Verificar contraseña de usuario"""
        return bcrypt.checkpw(password.encode('utf-8'), hashed_password.encode('utf-8'))
    
    @staticmethod
    def hash_user_password(password: str) -> str:
        """Hashear contraseña de usuario"""
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

# ========== DEPENDENCIAS CORREGIDAS ==========

# ✅ require_api_key YA ESTÁ BIEN (es una función async)
require_api_key = AuthHandler.authenticate_api_key

# ✅ require_admin YA ESTÁ BIEN (es una función async)  
require_admin = AuthHandler.authenticate_user_session

# ✅ require_super_admin - VERSIÓN CORREGIDA
async def require_super_admin(
    usuario: Usuario = Depends(AuthHandler.authenticate_user_session)
) -> Usuario:
    """
    Verifica que el usuario tenga rol SUPER_ADMIN
    """
    if usuario.rol != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere rol SUPER_ADMIN"
        )
    return usuario

# ✅ require_cliente_admin - VERSIÓN CORREGIDA
async def require_cliente_admin(
    usuario: Usuario = Depends(AuthHandler.authenticate_user_session)
) -> Usuario:
    """
    Verifica que el usuario tenga rol CLIENTE_ADMIN
    """
    if usuario.rol != "cliente_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere rol CLIENTE_ADMIN"
        )
    return usuario