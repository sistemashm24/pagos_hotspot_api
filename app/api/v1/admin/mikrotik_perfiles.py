# app/api/v1/admin/mikrotik_perfiles.py - VERSIÓN FINAL
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel

from app.core.database import get_db
from app.core.auth import require_cliente_admin
from app.models.router import Router
from app.services.mikrotik_service import mikrotik_service

from typing import Optional  

router = APIRouter()

# ========== SCHEMAS ==========
class PerfilMikrotikResponse(BaseModel):
    """Schema para perfiles técnicos de MikroTik"""
    id: str                     # Ej: "*003", "*004" (el .id de MikroTik)
    name: str                   # Nombre del perfil
    # TODOS estos campos deben ser Optional[str]
    session_timeout: Optional[str] = None
    idle_timeout: Optional[str] = None
    keepalive_timeout: Optional[str] = None
    status_autorefresh: Optional[str] = None
    shared_users: Optional[str] = None
    rate_limit: Optional[str] = None
    address_list: Optional[str] = None
    mac_cookie_timeout: Optional[str] = None
    
    class Config:
        from_attributes = True

class ConexionTestResponse(BaseModel):
    """Respuesta para test de conexión"""
    success: bool
    message: str
    router: Dict[str, Any]
    perfiles_encontrados: int = 0
    error: Optional[str] = None
    sugerencias: Optional[List[str]] = None
    timestamp: str

# ========== ENDPOINTS ==========
@router.get("/routers/{router_id}/mikrotik-profiles", 
            response_model=List[PerfilMikrotikResponse])
async def obtener_perfiles_mikrotik_router(
    router_id: str,
    usuario = Depends(require_cliente_admin),  # ← ¡CORRECTO AHORA!
    db: AsyncSession = Depends(get_db)
):
    """
    Obtener perfiles REALES del MikroTik (SOLO CLIENTE_ADMIN)
    
    Conecta al router MikroTik real y obtiene los perfiles Hotspot existentes.
    El cliente los usa para mapear a productos comerciales.
    
    Ejemplo de respuesta:
    [
      {
        "id": "*003",
        "name": "1_Semana_tiempo_corrido",
        "session_timeout": "7d",
        "rate_limit": "10M/10M"
      },
      {
        "id": "*002",
        "name": "1_Dia",
        "session_timeout": "1d"
      }
    ]
    """
    # 1. Verificar que el router existe y pertenece al cliente
    result = await db.execute(
        select(Router).where(
            Router.id == router_id,
            Router.empresa_id == usuario.empresa_id  # ← ¡AHORA FUNCIONA!
        )
    )
    router_obj = result.scalar_one_or_none()
    
    if not router_obj:
        raise HTTPException(
            status_code=404,
            detail="Router no encontrado o no pertenece a tu empresa"
        )
    
    # 2. Verificar que el router esté activo
    if not router_obj.activo:
        raise HTTPException(
            status_code=400,
            detail="El router está inactivo. Actívalo primero desde el panel."
        )
    
    # 3. Verificar credenciales básicas
    if not all([router_obj.host, router_obj.usuario, router_obj.password_encrypted]):
        raise HTTPException(
            status_code=400,
            detail="El router no tiene credenciales configuradas completas (host, usuario, contraseña)"
        )
    
    try:
        # 4. 🔌 CONEXIÓN REAL AL MIKROTIK
        perfiles_reales = await mikrotik_service.get_hotspot_profiles(
            router_host=router_obj.host,
            router_port=router_obj.puerto,
            router_user=router_obj.usuario,
            router_password=router_obj.password_encrypted
        )
        
        if not perfiles_reales:
            return []  # Devolver lista vacía si no hay perfiles
        
        # 5. Transformar a formato de respuesta
        perfiles_transformados = []
        for perfil in perfiles_reales:
            perfiles_transformados.append(PerfilMikrotikResponse(
                id=perfil.get("id", ""),
                name=perfil.get("name", ""),
                session_timeout=perfil.get("session_timeout"),
                idle_timeout=perfil.get("idle_timeout"),
                rate_limit=perfil.get("rate_limit"),
                # Estos campos pueden estar vacíos dependiendo del router
                keepalive_timeout=perfil.get("keepalive-timeout"),
                status_autorefresh=perfil.get("status-autorefresh"),
                shared_users=perfil.get("shared-users"),
                address_list=perfil.get("address-list"),
                mac_cookie_timeout=perfil.get("mac-cookie-timeout")
            ))
        
        return perfiles_transformados
        
    except HTTPException as he:
        # Re-lanzar excepciones HTTP ya manejadas
        raise he
    except Exception as e:
        # Log para debugging
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error conectando a MikroTik {router_obj.host}:{router_obj.puerto}: {str(e)}")
        
        raise HTTPException(
            status_code=500,
            detail=f"Error al conectar con el router MikroTik: {str(e)}"
        )

# En tu mikrotik_perfiles.py - Modifica test_conexion_mikrotik
@router.get("/routers/{router_id}/test-connection")
async def test_conexion_mikrotik(
    router_id: str,
    usuario = Depends(require_cliente_admin),
    db: AsyncSession = Depends(get_db)
):
    """Probar conexión con router MikroTik usando MikrotikAPI"""
    print(f"🔍 Test conexión para router: {router_id}")
    
    # 1. Verificar que el router existe
    result = await db.execute(
        select(Router).where(
            Router.id == router_id,
            Router.empresa_id == usuario.empresa_id
        )
    )
    router_obj = result.scalar_one_or_none()
    
    if not router_obj:
        return {
            "success": False,
            "message": "Router no encontrado",
            "error": "Router no encontrado o no pertenece a tu empresa"
        }
    
    print(f"✅ Router encontrado: {router_obj.nombre}")
    print(f"   Host: {router_obj.host}:{router_obj.puerto}")
    print(f"   Usuario: {router_obj.usuario}")
    
    # 2. Usar el nuevo servicio con MikrotikAPI
    try:
        test_result = await mikrotik_service.test_connection(
            router_host=router_obj.host,
            router_port=router_obj.puerto,
            router_user=router_obj.usuario,
            router_password=router_obj.password_encrypted
        )
        
        return {
            "success": test_result.get("success", False),
            "message": "Conexión exitosa" if test_result.get("success") else "Error de conexión",
            "router": {
                "id": router_obj.id,
                "nombre": router_obj.nombre,
                "host": router_obj.host,
                "puerto": router_obj.puerto,
                "activo": router_obj.activo
            },
            "perfiles_encontrados": test_result.get("profiles_count", 0),
            "router_name": test_result.get("router_name"),
            "error": test_result.get("error"),
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        print(f"❌ Error en test: {type(e).__name__}: {str(e)}")
        return {
            "success": False,
            "message": "Error de conexión",
            "router": {
                "id": router_obj.id,
                "nombre": router_obj.nombre,
                "host": router_obj.host,
                "puerto": router_obj.puerto,
                "activo": router_obj.activo
            },
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }