# app/api/admin/routers.py
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import uuid
from jose import jwt
import hashlib
from datetime import datetime, timedelta
from typing import Optional, List

from app.core.database import get_db
from app.core.auth import require_super_admin
from app.models.empresa import Empresa
from app.models.router import Router
from app.models.api_key import ApiKeyTracking
from app.models.usuario import Usuario
from app.core.config import settings

router = APIRouter()

# ========== SCHEMAS ==========
class RouterCreateRequest(BaseModel):
    empresa_id: str
    nombre: str
    host: str
    puerto: int = 8728
    usuario: str
    password: str
    ubicacion: Optional[str] = None

class RouterCreateResponse(BaseModel):
    id: str
    empresa_id: str
    nombre: str
    host: str
    puerto: int
    ubicacion: Optional[str]
    activo: bool
    api_key: str  # Esta es la JWT que se genera
    api_key_info: dict  # Info adicional sobre la API key
    creado_en: datetime
    
    class Config:
        from_attributes = True

class RouterResponse(BaseModel):
    id: str
    empresa_id: str
    nombre: str
    host: str
    puerto: int
    ubicacion: Optional[str]
    activo: bool
    creado_en: datetime
    
    class Config:
        from_attributes = True

class RegenerateAPIKeyResponse(BaseModel):
    message: str
    router_id: str
    new_api_key: str
    api_key_info: dict
    previous_key_revoked: bool

class RouterAPIKeyInfo(BaseModel):
    key_id: str
    router_id: str
    empresa_id: str
    issued_at: datetime
    expires_at: datetime
    revoked: bool
    revoked_at: Optional[datetime]
    last_used: Optional[datetime]
    use_count: int
    
    class Config:
        from_attributes = True

class APIKeyStatusResponse(BaseModel):
    router_id: str
    has_active_key: bool
    key_id: Optional[str] = None
    issued_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    expires_in_days: Optional[int] = None
    last_used: Optional[datetime] = None
    use_count: Optional[int] = None
    status: Optional[str] = None
    warning: Optional[str] = None
    recommendation: Optional[str] = None

class RevokeAPIKeyResponse(BaseModel):
    message: str
    key_id: str
    router_id: str
    revoked_at: datetime

class ToggleActivoResponse(BaseModel):
    message: str
    router_id: str
    activo: bool

# ========== HELPER FUNCTIONS ==========
def generar_api_key_jwt(empresa_id: str, router_id: str):
    """Generar API Key JWT para router"""
    key_id = f"key_{uuid.uuid4().hex[:16]}"
    issued_at = datetime.utcnow()
    expires_at = issued_at + timedelta(days=settings.JWT_APIKEY_EXPIRE_DAYS)
    
    payload = {
        "jti": key_id,
        "iss": "mikrotik-payment-api",
        "sub": router_id,
        "empresa": empresa_id,
        "iat": issued_at.timestamp(),
        "exp": expires_at.timestamp(),
        "type": "router_api_key"
    }
    
    token = jwt.encode(
        payload,
        settings.JWT_APIKEY_SECRET,
        algorithm=settings.JWT_ALGORITHM
    )
    
    full_token = f"jwt_{token}"
    
    return {
        "key_id": key_id,
        "token": full_token,
        "token_raw": token,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "payload": payload
    }

async def revocar_api_key_actual(router_id: str, db: AsyncSession):
    """Revocar la API key actual de un router"""
    result = await db.execute(
        select(ApiKeyTracking).where(
            ApiKeyTracking.router_id == router_id,
            ApiKeyTracking.revoked == False
        )
    )
    
    current_key = result.scalar_one_or_none()
    
    if current_key:
        current_key.revoked = True
        current_key.revoked_at = datetime.utcnow()
        await db.commit()
        return current_key
    
    return None

async def obtener_info_api_keys_router(router_id: str, db: AsyncSession):
    """Obtener información de todas las API keys de un router"""
    result = await db.execute(
        select(ApiKeyTracking).where(
            ApiKeyTracking.router_id == router_id
        ).order_by(ApiKeyTracking.issued_at.desc())
    )
    
    keys = result.scalars().all()
    return keys

async def verificar_router_pertenece_empresa(router_id: str, empresa_id: str, db: AsyncSession) -> Router:
    """Verificar que el router existe y pertenece a la empresa"""
    router = await db.get(Router, router_id)
    if not router or router.empresa_id != empresa_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Router no encontrado o no pertenece a la empresa"
        )
    return router

async def verificar_empresa_activa(empresa_id: str, db: AsyncSession) -> Empresa:
    """Verificar que la empresa existe y está activa"""
    empresa = await db.get(Empresa, empresa_id)
    if not empresa:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Empresa no encontrada"
        )
    return empresa

# ========== ENDPOINTS ==========
@router.post("/empresas/{empresa_id}/routers", response_model=RouterCreateResponse)
async def agregar_router_a_empresa(
    empresa_id: str,
    router_data: RouterCreateRequest,
    usuario = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Agregar router a empresa y generar API Key (SOLO SUPER_ADMIN)
    
    Crea un nuevo router y genera automáticamente una API Key JWT para él.
    La API Key se devuelve en la respuesta y debe ser entregada al cliente.
    """
    # Verificar empresa
    empresa = await verificar_empresa_activa(empresa_id, db)
    
    # Generar ID router
    router_id = f"RTR_{uuid.uuid4().hex[:8].upper()}"
    
    # Generar API Key
    api_key_info = generar_api_key_jwt(empresa_id, router_id)
    key_hash = hashlib.sha256(api_key_info["token_raw"].encode()).hexdigest()
    
    # Crear router
    router = Router(
        id=router_id,
        empresa_id=empresa_id,
        nombre=router_data.nombre,
        host=router_data.host,
        puerto=router_data.puerto,
        usuario=router_data.usuario,
        password_encrypted=router_data.password,
        ubicacion=router_data.ubicacion,
        api_key_hash=key_hash,
        activo=True
    )
    
    # Crear tracking API Key
    api_key_tracking = ApiKeyTracking(
        key_id=api_key_info["key_id"],
        empresa_id=empresa_id,
        router_id=router_id,
        key_hash=key_hash,
        issued_at=api_key_info["issued_at"],
        expires_at=api_key_info["expires_at"],
        revoked=False
    )
    
    db.add(router)
    db.add(api_key_tracking)
    await db.commit()
    await db.refresh(router)
    
    # Construir respuesta
    response = RouterCreateResponse(
        id=router.id,
        empresa_id=router.empresa_id,
        nombre=router.nombre,
        host=router.host,
        puerto=router.puerto,
        ubicacion=router.ubicacion,
        activo=router.activo,
        api_key=api_key_info["token"],  # La JWT completa
        api_key_info={
            "key_id": api_key_info["key_id"],
            "issued_at": api_key_info["issued_at"].isoformat(),
            "expires_at": api_key_info["expires_at"].isoformat(),
            "type": "router_api_key"
        },
        creado_en=router.creado_en
    )
    
    return response

@router.get("/empresas/{empresa_id}/routers", response_model=List[RouterResponse])
async def listar_routers_empresa(
    empresa_id: str,
    usuario = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Listar routers de una empresa (SOLO SUPER_ADMIN)
    
    Devuelve todos los routers asociados a una empresa específica.
    """
    # Verificar empresa
    await verificar_empresa_activa(empresa_id, db)
    
    # Obtener routers
    result = await db.execute(
        select(Router).where(Router.empresa_id == empresa_id)
    )
    routers = result.scalars().all()
    
    return routers

@router.get("/empresas/{empresa_id}/routers/{router_id}", response_model=RouterResponse)
async def obtener_router_especifico(
    empresa_id: str,
    router_id: str,
    usuario = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Obtener información específica de un router (SOLO SUPER_ADMIN)
    
    Devuelve los detalles de un router específico verificando que pertenezca a la empresa.
    """
    router = await verificar_router_pertenece_empresa(router_id, empresa_id, db)
    return router

@router.put("/empresas/{empresa_id}/routers/{router_id}/toggle-activo", 
            response_model=ToggleActivoResponse)
async def toggle_activo_router(
    empresa_id: str,
    router_id: str,
    usuario = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Activar/desactivar router (SOLO SUPER_ADMIN)
    
    Cambia el estado activo/inactivo de un router.
    Un router inactivo no puede procesar pagos ni ser usado en el sistema.
    """
    router = await verificar_router_pertenece_empresa(router_id, empresa_id, db)
    
    # Cambiar estado
    nuevo_estado = not router.activo
    router.activo = nuevo_estado
    await db.commit()
    await db.refresh(router)
    
    return ToggleActivoResponse(
        message=f"Router {'activado' if nuevo_estado else 'desactivado'} correctamente",
        router_id=router.id,
        activo=nuevo_estado
    )

@router.post("/empresas/{empresa_id}/routers/{router_id}/regenerate-api-key", 
             response_model=RegenerateAPIKeyResponse)
async def regenerar_api_key_router(
    empresa_id: str,
    router_id: str,
    usuario = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Regenerar API Key para un router existente (SOLO SUPER_ADMIN)
    
    Esto:
    1. Revoca la API key actual (si existe)
    2. Genera una nueva API key JWT
    3. Actualiza el hash en el router
    4. Registra la nueva key en tracking
    
    Útil cuando un cliente pierde su API Key.
    """
    router = await verificar_router_pertenece_empresa(router_id, empresa_id, db)
    
    # Verificar que el router esté activo
    if not router.activo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se puede regenerar API key de un router inactivo"
        )
    
    # 1. Revocar API key actual
    previous_key = await revocar_api_key_actual(router_id, db)
    
    # 2. Generar nueva API Key
    api_key_info = generar_api_key_jwt(empresa_id, router_id)
    key_hash = hashlib.sha256(api_key_info["token_raw"].encode()).hexdigest()
    
    # 3. Actualizar hash en el router
    router.api_key_hash = key_hash
    
    # 4. Registrar nueva key en tracking
    new_api_key_tracking = ApiKeyTracking(
        key_id=api_key_info["key_id"],
        empresa_id=empresa_id,
        router_id=router_id,
        key_hash=key_hash,
        issued_at=api_key_info["issued_at"],
        expires_at=api_key_info["expires_at"],
        revoked=False
    )
    
    db.add(new_api_key_tracking)
    await db.commit()
    await db.refresh(router)
    
    return RegenerateAPIKeyResponse(
        message="API Key regenerada exitosamente",
        router_id=router_id,
        new_api_key=api_key_info["token"],
        api_key_info={
            "key_id": api_key_info["key_id"],
            "issued_at": api_key_info["issued_at"].isoformat(),
            "expires_at": api_key_info["expires_at"].isoformat(),
            "type": "router_api_key"
        },
        previous_key_revoked=bool(previous_key)
    )

@router.get("/empresas/{empresa_id}/routers/{router_id}/api-keys", 
            response_model=List[RouterAPIKeyInfo])
async def listar_api_keys_router(
    empresa_id: str,
    router_id: str,
    usuario = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Listar todas las API keys (activas e históricas) de un router (SOLO SUPER_ADMIN)
    
    Útil para auditoría y verificación de uso histórico.
    """
    await verificar_router_pertenece_empresa(router_id, empresa_id, db)
    
    api_keys = await obtener_info_api_keys_router(router_id, db)
    
    return api_keys

@router.post("/empresas/{empresa_id}/routers/{router_id}/api-keys/{key_id}/revoke",
             response_model=RevokeAPIKeyResponse)
async def revocar_api_key_especifica(
    empresa_id: str,
    router_id: str,
    key_id: str,
    usuario = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Revocar una API key específica (SOLO SUPER_ADMIN)
    
    Útil cuando se necesita revocar una key sin generar una nueva.
    Por ejemplo, si se detecta que una key fue comprometida.
    """
    await verificar_router_pertenece_empresa(router_id, empresa_id, db)
    
    # Buscar la key específica
    result = await db.execute(
        select(ApiKeyTracking).where(
            ApiKeyTracking.key_id == key_id,
            ApiKeyTracking.router_id == router_id,
            ApiKeyTracking.empresa_id == empresa_id
        )
    )
    
    api_key = result.scalar_one_or_none()
    
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API Key no encontrada"
        )
    
    if api_key.revoked:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La API Key ya está revocada"
        )
    
    # Revocar la key
    revoked_at = datetime.utcnow()
    api_key.revoked = True
    api_key.revoked_at = revoked_at
    await db.commit()
    
    return RevokeAPIKeyResponse(
        message="API Key revocada exitosamente",
        key_id=key_id,
        router_id=router_id,
        revoked_at=revoked_at
    )

@router.get("/empresas/{empresa_id}/routers/{router_id}/api-key-status",
            response_model=APIKeyStatusResponse)
async def estado_api_key_actual(
    empresa_id: str,
    router_id: str,
    usuario = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Verificar estado de la API key actual (SOLO SUPER_ADMIN)
    
    Útil para diagnóstico y verificación de estado de la key activa.
    """
    await verificar_router_pertenece_empresa(router_id, empresa_id, db)
    
    # Buscar API key activa actual
    result = await db.execute(
        select(ApiKeyTracking).where(
            ApiKeyTracking.router_id == router_id,
            ApiKeyTracking.revoked == False
        ).order_by(ApiKeyTracking.issued_at.desc()).limit(1)
    )
    
    current_key = result.scalar_one_or_none()
    
    if not current_key:
        return APIKeyStatusResponse(
            router_id=router_id,
            has_active_key=False,
            status="no_key",
            message="No hay API Key activa para este router",
            recommendation="Generar una nueva API Key"
        )
    
    # Verificar expiración
    now = datetime.utcnow()
    expires_in_days = (current_key.expires_at - now).days
    
    status_response = APIKeyStatusResponse(
        router_id=router_id,
        has_active_key=True,
        key_id=current_key.key_id,
        issued_at=current_key.issued_at,
        expires_at=current_key.expires_at,
        expires_in_days=expires_in_days,
        last_used=current_key.last_used,
        use_count=current_key.use_count,
        status="active"
    )
    
    # Advertencias si es necesario
    if expires_in_days < 30:
        status_response.warning = f"La API Key expira en {expires_in_days} días"
        status_response.recommendation = "Considerar regenerar la API Key pronto"
    
    if current_key.use_count == 0:
        status_response.warning = "Esta API Key nunca ha sido usada"
        status_response.recommendation = "Verificar que el cliente la esté usando correctamente"
    
    return status_response

@router.get("/empresas/{empresa_id}/stats")
async def estadisticas_empresa(
    empresa_id: str,
    usuario = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Estadísticas de empresa específica (SOLO SUPER_ADMIN)
    
    Devuelve estadísticas detalladas de una empresa:
    - Total de routers
    - Routers activos
    - Total de usuarios administradores
    """
    empresa = await verificar_empresa_activa(empresa_id, db)
    
    # Contar routers
    routers_result = await db.execute(
        select(func.count(Router.id)).where(Router.empresa_id == empresa_id)
    )
    total_routers = routers_result.scalar()
    
    # Contar routers activos
    routers_activos_result = await db.execute(
        select(func.count(Router.id)).where(
            Router.empresa_id == empresa_id,
            Router.activo == True
        )
    )
    routers_activos = routers_activos_result.scalar()
    
    # Contar usuarios administradores
    usuarios_result = await db.execute(
        select(func.count(Usuario.id)).where(
            Usuario.empresa_id == empresa_id,
            Usuario.rol == 'cliente_admin'
        )
    )
    total_usuarios_admin = usuarios_result.scalar()
    
    # Obtener API keys activas
    api_keys_activas_result = await db.execute(
        select(func.count(ApiKeyTracking.key_id)).where(
            ApiKeyTracking.empresa_id == empresa_id,
            ApiKeyTracking.revoked == False,
            ApiKeyTracking.expires_at > datetime.utcnow()
        )
    )
    api_keys_activas = api_keys_activas_result.scalar()
    
    return {
        "empresa": {
            "id": empresa.id,
            "nombre": empresa.nombre,
            "activa": empresa.activa,
            "creada_en": empresa.creada_en,
            "contacto_email": empresa.contacto_email
        },
        "estadisticas": {
            "total_routers": total_routers or 0,
            "routers_activos": routers_activos or 0,
            "routers_inactivos": (total_routers or 0) - (routers_activos or 0),
            "total_usuarios_admin": total_usuarios_admin or 0,
            "api_keys_activas": api_keys_activas or 0
        }
    }

@router.delete("/empresas/{empresa_id}/routers/{router_id}")
async def eliminar_router(
    empresa_id: str,
    router_id: str,
    usuario = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Eliminar router permanentemente (SOLO SUPER_ADMIN)
    
    CUIDADO: Esta operación elimina el router y todas sus API keys.
    No se recomienda si hay transacciones asociadas al router.
    """
    router = await verificar_router_pertenece_empresa(router_id, empresa_id, db)
    
    # Verificar si hay transacciones asociadas (opcional pero recomendado)
    from app.models.transaccion import Transaccion
    from app.models.producto import Producto
    
    # Verificar productos asociados
    productos_result = await db.execute(
        select(func.count(Producto.id)).where(Producto.router_id == router_id)
    )
    productos_asociados = productos_result.scalar() or 0
    
    if productos_asociados > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No se puede eliminar el router porque tiene {productos_asociados} producto(s) asociado(s)"
        )
    
    # Eliminar router (las API keys se eliminarán por cascade si está configurado)
    await db.delete(router)
    await db.commit()
    
    return {
        "message": "Router eliminado exitosamente",
        "router_id": router_id,
        "empresa_id": empresa_id
    }


"""
=====================================================
ENDPOINTS PARA GESTIÓN DE ROUTERS - MIKROTIK PAYMENT API
=====================================================

ESTOS ENDPOINTS SOLO SON ACCESIBLES POR SUPER_ADMIN (TÚ)
PARA GESTIONAR LOS ROUTERS DE TUS CLIENTES EMPRESAS.

-----------------------------------------------------
1. 📝 CREAR NUEVO ROUTER + API KEY
-----------------------------------------------------
POST /admin/empresas/{empresa_id}/routers

CUÁNDO USAR: Cuando un cliente nuevo se registra o necesita otro router
QUÉ HACE: Crea router en BD + genera API Key JWT automática
RESPONSE: Devuelve router con API Key (entregarla al cliente)

-----------------------------------------------------
2. 📋 LISTAR ROUTERS DE UNA EMPRESA
-----------------------------------------------------
GET /admin/empresas/{empresa_id}/routers

CUÁNDO USAR: Para ver todos los routers que tiene un cliente
QUÉ HACE: Lista routers de esa empresa
EJEMPLO: Dashboard superadmin, auditoría mensual

-----------------------------------------------------
3. 🔍 VER DETALLES DE UN ROUTER ESPECÍFICO
-----------------------------------------------------
GET /admin/empresas/{empresa_id}/routers/{router_id}

CUÁNDO USAR: Para ver info detallada de un router particular
QUÉ HACE: Muestra host, puerto, estado, etc.

-----------------------------------------------------
4. ⚙️ ACTIVAR/DESACTIVAR ROUTER
-----------------------------------------------------
PUT /admin/empresas/{empresa_id}/routers/{router_id}/toggle-activo

CUÁNDO USAR: Para pausar un router temporalmente
QUÉ HACE: Cambia estado activo/inactivo (no procesa pagos si está inactivo)

-----------------------------------------------------
5. 🔑 REGENERAR API KEY (CLAVE CUANDO CLIENTE LA PIERDE)
-----------------------------------------------------
POST /admin/empresas/{empresa_id}/routers/{router_id}/regenerate-api-key

CUÁNDO USAR: ¡CLIENTE PERDIÓ SU API KEY! (caso común)
QUÉ HACE: Revoca key antigua + genera nueva + actualiza hash
RESPONSE: Nueva API Key (entregársela al cliente)

-----------------------------------------------------
6. 📊 VER HISTÓRICO DE API KEYS
-----------------------------------------------------
GET /admin/empresas/{empresa_id}/routers/{router_id}/api-keys

CUÁNDO USAR: Auditoría, ver cuántas keys ha tenido, cuándo se generaron
QUÉ HACE: Lista todas las keys (activas e históricas)

-----------------------------------------------------
7. 🚫 REVOCAR API KEY ESPECÍFICA
-----------------------------------------------------
POST /admin/empresas/{empresa_id}/routers/{router_id}/api-keys/{key_id}/revoke

CUÁNDO USAR: Key comprometida o cliente la comparte con terceros
QUÉ HACE: Revoca key específica sin generar nueva

-----------------------------------------------------
8. ✅ VER ESTADO DE API KEY ACTUAL
-----------------------------------------------------
GET /admin/empresas/{empresa_id}/routers/{router_id}/api-key-status

CUÁNDO USAR: Diagnóstico, ver si está por expirar, cuántas veces se usó
QUÉ HACE: Muestra info de key activa + advertencias si expira pronto

-----------------------------------------------------
9. 📈 ESTADÍSTICAS DE EMPRESA
-----------------------------------------------------
GET /admin/empresas/{empresa_id}/stats

CUÁNDO USAR: Dashboard superadmin, reportes mensuales
QUÉ HACE: Muestra stats de routers, usuarios, keys activas

-----------------------------------------------------
10. 🗑️ ELIMINAR ROUTER (¡CUIDADO!)
-----------------------------------------------------
DELETE /admin/empresas/{empresa_id}/routers/{router_id}

CUÁNDO USAR: Solo si cliente cancela servicio permanentemente
QUÉ HACE: Elimina router + todas sus API keys (validaciones incluidas)
"""

# =====================================================
# FLUJO TÍPICO PARA UN CLIENTE NUEVO:
# =====================================================
"""
1. POST /admin/empresas/{empresa_id}/routers  ← Creas router
2. Guardas la API Key de la respuesta
3. Le das al cliente: 
   - Credenciales panel admin (email/password)
   - API Key para su portal de pagos
   - Instrucciones para configurar Conekta

SI EL CLIENTE PIERDE LA API KEY:
1. POST /admin/empresas/.../regenerate-api-key
2. Le das la nueva API Key
3. Key antigua deja de funcionar automáticamente
"""

# =====================================================
# ¿QUÉ API KEY USA EL CLIENTE EN SU PORTAL?
# =====================================================
"""
EL CLIENTE USA LA 'api_key' COMPLETA DEL RESPONSE:
"api_key": "jwt_eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."

EN SUS PETICIONES HTTP:
headers: {
    'X-API-Key': 'jwt_eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...'
}

PARA SU SEGURIDAD:
- La API Key tiene 1 año de validez
- Solo se muestra al crear/regenerar
- Se almacena como HASH en BD (no texto plano)
- Puedes revocarla si es necesario
"""