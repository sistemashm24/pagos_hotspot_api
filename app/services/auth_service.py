# app/services/auth_service.py - VERSIÓN COMPLETA Y CORREGIDA
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timedelta
from jose import jwt
import bcrypt

from app.core.config import settings
from app.models.usuario import Usuario
from app.schemas.request.auth import LoginRequest
from app.schemas.response.auth import LoginResponse, UserResponse
from app.core.security import create_access_token

class AuthService:
    @staticmethod
    async def authenticate_user(
        login_data: LoginRequest,
        db: AsyncSession
    ) -> LoginResponse:
        """Autenticar usuario y generar JWT"""
        # DEBUG: Imprimir credenciales recibidas (sin password por seguridad)
        print(f"DEBUG - Intento de login para email: {login_data.email}")
        
        # 1. Buscar usuario por email
        result = await db.execute(
            select(Usuario).where(Usuario.email == login_data.email)
        )
        usuario = result.scalar_one_or_none()
        
        if not usuario:
            print(f"DEBUG - Usuario no encontrado: {login_data.email}")
            raise ValueError("Credenciales incorrectas")
        
        print(f"DEBUG - Usuario encontrado: {usuario.email}, ID: {usuario.id}, Rol: {usuario.rol}")
        
        if not usuario.activo:
            print(f"DEBUG - Usuario inactivo: {usuario.email}")
            raise ValueError("Usuario inactivo. Contacta al administrador.")
        
        # 2. Verificar contraseña
        try:
            password_valid = bcrypt.checkpw(
                login_data.password.encode('utf-8'),
                usuario.password_hash.encode('utf-8')
            )
            print(f"DEBUG - Verificación de password: {'ÉXITO' if password_valid else 'FALLÓ'}")
        except Exception as e:
            print(f"DEBUG - Error en verificación de password: {str(e)}")
            raise ValueError(f"Error verificando contraseña: {str(e)}")
        
        if not password_valid:
            raise ValueError("Credenciales incorrectas")
        
        # 3. Actualizar último login
        usuario.ultimo_login = datetime.utcnow()
        await db.commit()
        print(f"DEBUG - Último login actualizado: {usuario.ultimo_login}")
        
        # 4. Crear token
        token_data = {
            "sub": str(usuario.id),
            "email": usuario.email,
            "nombre": usuario.nombre,
            "rol": usuario.rol,
            "empresa_id": usuario.empresa_id
        }
        
        access_token = create_access_token(token_data)
        print(f"DEBUG - Token generado (primeros 50 chars): {access_token[:50]}...")
        
        # 5. Obtener fecha de expiración del token
        try:
            payload = jwt.decode(
                access_token,
                settings.JWT_SESSION_SECRET,
                algorithms=[settings.JWT_ALGORITHM]
            )
            expires_at = datetime.fromtimestamp(payload["exp"])
            print(f"DEBUG - Token expira: {expires_at}")
        except Exception as e:
            print(f"DEBUG - Error decodificando token: {str(e)}")
            expires_at = datetime.utcnow() + timedelta(
                hours=settings.JWT_SESSION_EXPIRE_HOURS
            )
        
        # 6. Crear UserResponse MANUALMENTE para evitar problemas con empresa_id
        print(f"DEBUG - Creando UserResponse...")
        print(f"  empresa_id en BD: {repr(usuario.empresa_id)}")
        print(f"  empresa_id tipo: {type(usuario.empresa_id)}")
        print(f"  empresa_id es None: {usuario.empresa_id is None}")
        
        # Preparar datos para UserResponse
        user_data = {
            "id": usuario.id,
            "email": usuario.email,
            "nombre": usuario.nombre,
            "rol": usuario.rol,
            "activo": usuario.activo,
        }
        
        # Manejar empresa_id correctamente
        if usuario.empresa_id is not None:
            user_data["empresa_id"] = str(usuario.empresa_id)
            print(f"  empresa_id agregado como string: {user_data['empresa_id']}")
        else:
            # No agregamos la clave si es None, el schema tiene valor por defecto None
            print(f"  empresa_id es None, usando valor por defecto del schema")
        
        print(f"DEBUG - Datos para UserResponse: {user_data}")
        
        # Crear UserResponse
        try:
            user_response = UserResponse(**user_data)
            print(f"DEBUG - UserResponse creado exitosamente")
        except Exception as e:
            print(f"DEBUG - Error creando UserResponse: {str(e)}")
            print(f"DEBUG - Intentando método alternativo...")
            # Método alternativo sin empresa_id
            user_response = UserResponse(
                id=usuario.id,
                email=usuario.email,
                nombre=usuario.nombre,
                rol=usuario.rol,
                activo=usuario.activo
                # empresa_id se omitirá, usando el valor por defecto None
            )
        
        # 7. Crear LoginResponse
        login_response = LoginResponse(
            access_token=access_token,
            token_type="bearer",
            expires_at=expires_at,
            user=user_response
        )
        
        print(f"DEBUG - Login exitoso para usuario ID: {usuario.id}")
        print(f"DEBUG - Response completo: {login_response.dict(exclude={'access_token'})}")
        
        return login_response
    
    @staticmethod
    async def reset_password_debug(
        email: str,
        new_password: str,
        db: AsyncSession
    ) -> bool:
        """Método para resetear contraseña (solo para desarrollo/debug)"""
        print(f"DEBUG - Reseteando contraseña para: {email}")
        
        result = await db.execute(
            select(Usuario).where(Usuario.email == email)
        )
        usuario = result.scalar_one_or_none()
        
        if not usuario:
            print(f"DEBUG - Usuario no encontrado: {email}")
            return False
        
        # Generar nuevo hash
        salt = bcrypt.gensalt(rounds=12)
        new_hash = bcrypt.hashpw(new_password.encode('utf-8'), salt)
        
        # Actualizar en BD
        usuario.password_hash = new_hash.decode('utf-8')
        await db.commit()
        
        print(f"DEBUG - Contraseña actualizada exitosamente")
        print(f"DEBUG - Nueva contraseña: {new_password}")
        print(f"DEBUG - Nuevo hash: {usuario.password_hash[:30]}...")
        
        return True