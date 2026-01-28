# app/api/v1/admin/empresa.py
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime

from app.core.database import get_db
from app.core.auth import require_cliente_admin
from app.models.empresa import Empresa
from app.models.router import Router
from app.models.producto import Producto
from app.models.transaccion import Transaccion

router = APIRouter()

# ========== SCHEMAS ==========
class ConektaConfigUpdate(BaseModel):
    conekta_private_key: str
    conekta_public_key: str
    conekta_mode: str = "test"

class EmpresaInfoResponse(BaseModel):
    id: str
    nombre: str
    contacto_email: str
    contacto_telefono: str = None
    conekta_mode: str
    conekta_public_key: str
    activa: bool
    creada_en: datetime
    
    class Config:
        from_attributes = True

# ========== ENDPOINTS ==========
@router.get("/mi-empresa", response_model=EmpresaInfoResponse)
async def obtener_info_mi_empresa(
    usuario = Depends(require_cliente_admin),
    db: AsyncSession = Depends(get_db)
):
    """Obtener información de MI empresa"""
    empresa = await db.get(Empresa, usuario.empresa_id)
    if not empresa:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Empresa no encontrada"
        )
    
    return empresa

@router.put("/mi-empresa/conekta-config")
async def actualizar_config_conekta(
    config_data: ConektaConfigUpdate,
    usuario = Depends(require_cliente_admin),
    db: AsyncSession = Depends(get_db)
):
    """Actualizar configuración de Conekta de MI empresa"""
    empresa = await db.get(Empresa, usuario.empresa_id)
    if not empresa:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Empresa no encontrada"
        )
    
    empresa.conekta_private_key = config_data.conekta_private_key
    empresa.conekta_public_key = config_data.conekta_public_key
    empresa.conekta_mode = config_data.conekta_mode
    
    await db.commit()
    
    return {
        "message": "Configuración de Conekta actualizada",
        "conekta_mode": empresa.conekta_mode,
        "public_key_updated": True
    }

@router.get("/mi-empresa/dashboard")
async def dashboard_mi_empresa(
    usuario = Depends(require_cliente_admin),
    db: AsyncSession = Depends(get_db)
):
    """Dashboard de MI empresa"""
    empresa = await db.get(Empresa, usuario.empresa_id)
    if not empresa:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Empresa no encontrada"
        )
    
    # Obtener routers
    routers_result = await db.execute(
        select(Router).where(Router.empresa_id == usuario.empresa_id)
    )
    routers = routers_result.scalars().all()
    
    # Estadísticas de transacciones
    transacciones_result = await db.execute(
        select(
            func.count(Transaccion.id).label("total"),
            func.sum(Transaccion.monto).label("ingresos_totales"),
            func.count(Transaccion.id).filter(Transaccion.estado_pago == "paid").label("pagadas"),
            func.count(Transaccion.id).filter(Transaccion.estado_pago == "pending").label("pendientes")
        ).where(Transaccion.empresa_id == usuario.empresa_id)
    )
    stats = transacciones_result.first()
    
    # Transacciones recientes
    recientes_result = await db.execute(
        select(Transaccion)
        .where(Transaccion.empresa_id == usuario.empresa_id)
        .order_by(Transaccion.creada_en.desc())
        .limit(5)
    )
    transacciones_recientes = recientes_result.scalars().all()
    
    return {
        "empresa": {
            "nombre": empresa.nombre,
            "activa": empresa.activa
        },
        "estadisticas": {
            "total_transacciones": stats.total or 0,
            "ingresos_totales": float(stats.ingresos_totales or 0),
            "transacciones_pagadas": stats.pagadas or 0,
            "transacciones_pendientes": stats.pendientes or 0,
            "total_routers": len(routers)
        },
        "transacciones_recientes": [
            {
                "id": t.id,
                "transaccion_id": t.transaccion_id,
                "monto": float(t.monto),
                "estado": t.estado_pago,
                "fecha": t.creada_en.isoformat() if t.creada_en else None
            }
            for t in transacciones_recientes
        ]
    }

@router.get("/mi-empresa/routers")
async def listar_mis_routers(
    usuario = Depends(require_cliente_admin),
    db: AsyncSession = Depends(get_db)
):
    """Listar MIS routers"""
    result = await db.execute(
        select(Router).where(Router.empresa_id == usuario.empresa_id)
    )
    routers = result.scalars().all()
    
    return {
        "empresa_id": usuario.empresa_id,
        "total": len(routers),
        "routers": [
            {
                "id": r.id,
                "nombre": r.nombre,
                "host": r.host,
                "ubicacion": r.ubicacion,
                "activo": r.activo,
                "creado_en": r.creado_en.isoformat() if r.creado_en else None
            }
            for r in routers
        ]
    }

@router.get("/mi-empresa/transacciones")
async def listar_mis_transacciones(
    limit: int = 50,
    offset: int = 0,
    usuario = Depends(require_cliente_admin),
    db: AsyncSession = Depends(get_db)
):
    """Listar MIS transacciones"""
    # Total
    total_result = await db.execute(
        select(func.count(Transaccion.id)).where(
            Transaccion.empresa_id == usuario.empresa_id
        )
    )
    total = total_result.scalar()
    
    # Transacciones paginadas
    result = await db.execute(
        select(Transaccion)
        .where(Transaccion.empresa_id == usuario.empresa_id)
        .order_by(Transaccion.creada_en.desc())
        .offset(offset)
        .limit(limit)
    )
    transacciones = result.scalars().all()
    
    return {
        "empresa_id": usuario.empresa_id,
        "total": total,
        "limit": limit,
        "offset": offset,
        "transacciones": [
            {
                "id": t.id,
                "transaccion_id": t.transaccion_id,
                "monto": float(t.monto),
                "estado_pago": t.estado_pago,
                "cliente_nombre": t.cliente_nombre,
                "creada_en": t.creada_en.isoformat() if t.creada_en else None
            }
            for t in transacciones
        ]
    }



class RouterUpdate(BaseModel):
    nombre: str | None = None
    host: str | None = None
    puerto: int | None = 8728
    usuario: str | None = None
    password_encrypted: str | None = None
    ubicacion: str | None = None


@router.put("/mi-empresa/routers/{router_id}")
async def actualizar_router_mi_empresa(
    router_id: str,
    data: RouterUpdate,
    usuario = Depends(require_cliente_admin),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Router).where(
            Router.id == router_id,
            Router.empresa_id == usuario.empresa_id
        )
    )
    router_obj = result.scalar_one_or_none()

    if not router_obj:
        raise HTTPException(
            status_code=404,
            detail="Router no encontrado o no pertenece a tu empresa"
        )

    datos = data.model_dump(exclude_unset=True)

    # Puerto por default
    if "puerto" not in datos:
        datos["puerto"] = 8728

    for campo, valor in datos.items():
        setattr(router_obj, campo, valor)

    await db.commit()
    await db.refresh(router_obj)

    return {
        "message": "Router actualizado correctamente",
        "router": {
            "id": router_obj.id,
            "nombre": router_obj.nombre,
            "host": router_obj.host,
            "puerto": router_obj.puerto,
            "usuario": router_obj.usuario,
            "ubicacion": router_obj.ubicacion,
            "activo": router_obj.activo
        }
    }
