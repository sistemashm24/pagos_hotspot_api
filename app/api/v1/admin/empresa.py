# app/api/v1/admin/empresa.py
from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile
import os
import shutil
import uuid
from pathlib import Path
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
print("\n🔥 >>> CARGANDO: app.api.v1.admin.empresa <<< 🔥\n")

# ========== SCHEMAS ==========
class ConektaConfigUpdate(BaseModel):
    conekta_private_key: str | None = None
    conekta_public_key: str | None = None
    conekta_mode: str = "test"

class ConektaConfigResponse(BaseModel):
    message: str
    configuracion_actual: dict

class MercadoPagoConfigUpdate(BaseModel):
    access_token: str | None = None
    public_key: str | None = None
    webhook_secret: str | None = None
    mode: str = "test"

class MercadoPagoConfigResponse(BaseModel):
    message: str
    configuracion_actual: dict

class EmpresaUpdate(BaseModel):
    nombre: str | None = None
    contacto_email: str | None = None
    contacto_telefono: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    notificaciones_telegram: bool | None = None

class EmpresaInfoResponse(BaseModel):
    id: str
    nombre: str
    contacto_email: str
    contacto_telefono: str | None = None
    logo_url: str | None = None
    conekta_mode: str
    conekta_public_key: str | None = None
    mercado_pago_mode: str | None = "test"
    mercado_pago_public_key: str | None = None
    activa: bool
    creada_en: datetime
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    notificaciones_telegram: bool = False
    
    class Config:
        from_attributes = True

class TelegramTestRequest(BaseModel):
    token: str | None = None
    chat_id: str | None = None

@router.post("/test-telegram")
async def probar_telegram(
    data: TelegramTestRequest,
    usuario = Depends(require_cliente_admin),
    db: AsyncSession = Depends(get_db)
):
    """Enviar un mensaje de prueba a Telegram (Permite probar datos no guardados)"""
    from app.services.telegram_service import telegram_service
    
    empresa = await db.get(Empresa, usuario.empresa_id)
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    
    # Usar datos enviados en la petición o caer de vuelta a los de la BD
    bot_token = data.token or empresa.telegram_bot_token
    chat_id = data.chat_id or empresa.telegram_chat_id
    
    if not bot_token or not chat_id:
        raise HTTPException(status_code=400, detail="Faltan credenciales (Token o Chat ID)")
    
    msg = (
        f"⚡ <b>Prueba de Conexión en Vivo</b>\n"
        f"🏢 Empresa: {empresa.nombre}\n"
        f"✅ ¡Tus credenciales son correctas!"
    )
    
    success = await telegram_service.send_message(bot_token, chat_id, msg)
    
    if not success:
        raise HTTPException(status_code=500, detail="Error de Telegram. Verifica que el Token sea válido y que hayas iniciado chat con el bot.")
    
    return {"message": "Mensaje de prueba enviado con éxito"}

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

@router.put("/mi-empresa")
async def actualizar_info_empresa(
    data: EmpresaUpdate,
    usuario = Depends(require_cliente_admin),
    db: AsyncSession = Depends(get_db)
):
    """Actualizar información básica de MI empresa"""
    empresa = await db.get(Empresa, usuario.empresa_id)
    if not empresa:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Empresa no encontrada"
        )
    
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(empresa, key, value)
    
    await db.commit()
    await db.refresh(empresa)
    
    return {
        "message": "Información de la empresa actualizada correctamente",
        "empresa": {
            "nombre": empresa.nombre,
            "contacto_email": empresa.contacto_email,
            "contacto_telefono": empresa.contacto_telefono,
            "telegram_bot_token": empresa.telegram_bot_token,
            "telegram_chat_id": empresa.telegram_chat_id,
            "notificaciones_telegram": empresa.notificaciones_telegram
        }
    }

@router.put("/mi-empresa/conekta-config")
async def actualizar_config_conekta(
    config_data: ConektaConfigUpdate,
    usuario = Depends(require_cliente_admin),
    db: AsyncSession = Depends(get_db)
):
    """Actualizar configuración de Conekta de MI empresa (Endpoint antiguo)"""
    empresa = await db.get(Empresa, usuario.empresa_id)
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    
    if config_data.conekta_private_key:
        empresa.conekta_private_key = config_data.conekta_private_key
    if config_data.conekta_public_key:
        empresa.conekta_public_key = config_data.conekta_public_key
    empresa.conekta_mode = config_data.conekta_mode
    
    await db.commit()
    return {"message": "Configuración de Conekta actualizada"}

@router.get("/mi-empresa/conekta", response_model=ConektaConfigResponse)
async def obtener_config_conekta(
    usuario = Depends(require_cliente_admin),
    db: AsyncSession = Depends(get_db)
):
    """Obtener configuración de Conekta de MI empresa"""
    empresa = await db.get(Empresa, usuario.empresa_id)
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    
    return {
        "message": "Configuración cargada",
        "configuracion_actual": {
            "conekta_public_key": empresa.conekta_public_key,
            "conekta_mode": empresa.conekta_mode,
            "conekta_private_key": "********" if empresa.conekta_private_key else None
        }
    }

@router.post("/mi-empresa/configurar-conekta")
async def configurar_conekta(
    data: ConektaConfigUpdate,
    usuario = Depends(require_cliente_admin),
    db: AsyncSession = Depends(get_db)
):
    """Configurar credenciales de Conekta (Nuevo endpoint usado por Desktop)"""
    empresa = await db.get(Empresa, usuario.empresa_id)
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    
    if data.conekta_private_key:
        empresa.conekta_private_key = data.conekta_private_key
    if data.conekta_public_key:
        empresa.conekta_public_key = data.conekta_public_key
    empresa.conekta_mode = data.conekta_mode
    
    await db.commit()
    return {"message": "Credenciales de Conekta actualizadas correctamente"}

@router.get("/mi-empresa/mercado-pago", response_model=MercadoPagoConfigResponse)
async def obtener_config_mercado_pago(
    usuario = Depends(require_cliente_admin),
    db: AsyncSession = Depends(get_db)
):
    """Obtener configuración de Mercado Pago de MI empresa"""
    empresa = await db.get(Empresa, usuario.empresa_id)
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    
    return {
        "message": "Configuración cargada",
        "configuracion_actual": {
            "access_token": "********" if empresa.mercado_pago_access_token else None,
            "public_key": empresa.mercado_pago_public_key,
            "mode": empresa.mercado_pago_mode,
            "webhook_secret": "********" if empresa.mercado_pago_webhook_secret else None
        }
    }

@router.post("/mi-empresa/configurar-credenciales")
async def configurar_mercado_pago(
    data: MercadoPagoConfigUpdate,
    usuario = Depends(require_cliente_admin),
    db: AsyncSession = Depends(get_db)
):
    """Configurar credenciales de Mercado Pago"""
    empresa = await db.get(Empresa, usuario.empresa_id)
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    
    if data.access_token:
        empresa.mercado_pago_access_token = data.access_token
    if data.public_key:
        empresa.mercado_pago_public_key = data.public_key
    if data.webhook_secret:
        empresa.mercado_pago_webhook_secret = data.webhook_secret
    empresa.mercado_pago_mode = data.mode
    
    await db.commit()
    return {"message": "Credenciales de Mercado Pago actualizadas correctamente"}

@router.post("/mi-empresa/logo")
async def subir_logo_empresa(
    file: UploadFile = File(...),
    usuario = Depends(require_cliente_admin),
    db: AsyncSession = Depends(get_db)
):
    """Subir o actualizar el logo de la empresa"""
    empresa = await db.get(Empresa, usuario.empresa_id)
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    
    # Validar extensión
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
        raise HTTPException(status_code=400, detail="Formato de imagen no permitido")
    
    # Generar nombre único
    filename = f"logo_{empresa.id}_{uuid.uuid4().hex[:6]}{ext}"
    static_dir = Path("static/logos")
    static_dir.mkdir(parents=True, exist_ok=True)
    
    file_path = static_dir / filename
    
    # Guardar archivo
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al guardar el archivo: {str(e)}")
    
    # Eliminar logo anterior si existe
    if empresa.logo_url and "static/logos/" in empresa.logo_url:
        old_path = Path(empresa.logo_url.split("/")[-2] + "/" + empresa.logo_url.split("/")[-1])
        # Esto es complejo por el host, mejor solo guardar el path relativo o absoluto
        # Para simplificar, guardaremos el path relativo accesible vía web
    
    # Actualizar URL del logo (usamos path relativo para que el cliente construya la URL completa)
    empresa.logo_url = f"/static/logos/{filename}"
    
    await db.commit()
    await db.refresh(empresa)
    
    return {
        "message": "Logo actualizado correctamente",
        "logo_url": empresa.logo_url
    }

    return {
        "message": "Logo actualizado correctamente",
        "logo_url": empresa.logo_url
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
