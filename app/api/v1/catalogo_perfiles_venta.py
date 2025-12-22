# app/api/v1/catalogo_perfiles_venta.py - CON RUTAS CORRECTAMENTE ORDENADAS
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel, field_serializer
import json

from app.core.database import get_db
from app.core.auth import require_api_key
from app.models.router import Router
from app.models.producto import Producto

router = APIRouter()

# ========== SCHEMAS ==========
class ProductoVentaResponse(BaseModel):
    """Schema para productos de venta"""
    id: int
    perfil_mikrotik_id: str
    perfil_mikrotik_nombre: str
    nombre_venta: str
    descripcion: Optional[str]
    imagen_url: Optional[str]
    precio: float
    moneda: str
    detalles: List[Dict[str, Any]]
    destacado: bool
    creado_en: datetime
    
    class Config:
        from_attributes = True
    
    @field_serializer('creado_en')
    def serialize_creado_en(self, creado_en: datetime, _info):
        return creado_en.isoformat() if creado_en else None
    
    @field_serializer('detalles')
    def serialize_detalles(self, detalles: List[Dict[str, Any]], _info):
        return detalles or []

# ========== FUNCIÓN AUXILIAR ==========
def _normalizar_detalles(detalles):
    """Normalizar detalles a lista de diccionarios"""
    if detalles is None:
        return []
    
    try:
        if isinstance(detalles, str):
            try:
                parsed = json.loads(detalles)
                return parsed if isinstance(parsed, list) else [parsed]
            except:
                return [{"value": detalles}]
        
        elif isinstance(detalles, list):
            return [
                {str(k): str(v) if not isinstance(v, (dict, list)) else v 
                 for k, v in item.items()} if isinstance(item, dict) 
                else {"value": str(item)}
                for item in detalles
            ]
        else:
            return [{"value": str(detalles)}]
    except:
        return []

# ========== ENDPOINTS - ¡ORDEN CORRECTO! ==========

# 1. ENDPOINT DEBUG (debe ir ANTES de la ruta con parámetro)
@router.get("/catalogo_perfiles_venta/debug")
async def debug_catalogo(
    empresa_router: tuple = Depends(require_api_key),
    db: AsyncSession = Depends(get_db)
):
    """Endpoint para debug - Mostrar datos RAW"""
    empresa, router, metadata = empresa_router
    
    print(f"🐛 Debug para router: {router.nombre}")
    
    result = await db.execute(
        select(Producto).where(
            Producto.empresa_id == empresa.id,
            Producto.router_id == router.id
        )
    )
    
    productos = result.scalars().all()
    
    debug_info = {
        "empresa": empresa.nombre,
        "router": router.nombre,
        "router_id": router.id,
        "empresa_id": empresa.id,
        "total_productos": len(productos),
        "productos": []
    }
    
    for p in productos:
        debug_info["productos"].append({
            "id": p.id,
            "nombre_venta": p.nombre_venta,
            "perfil_mikrotik_id": p.perfil_mikrotik_id,
            "detalles_raw": p.detalles,
            "detalles_tipo": str(type(p.detalles)),
            "detalles_normalizado": _normalizar_detalles(p.detalles),
            "creado_en": p.creado_en.isoformat() if p.creado_en else None,
            "creado_en_tipo": str(type(p.creado_en)),
            "activo": p.activo,
            "precio": float(p.precio),
            "moneda": p.moneda
        })
    
    print(f"📊 Debug: {debug_info['total_productos']} productos encontrados")
    return debug_info

# 2. ENDPOINT PRINCIPAL (sin parámetros)
@router.get("/catalogo_perfiles_venta", response_model=List[ProductoVentaResponse])
async def obtener_catalogo_perfiles_venta(
    empresa_router: tuple = Depends(require_api_key),
    db: AsyncSession = Depends(get_db)
):
    """Obtener catálogo de perfiles MikroTik para venta"""
    empresa, router, metadata = empresa_router
    
    print(f"🛍️ Obteniendo catálogo para router: {router.nombre}")
    
    try:
        result = await db.execute(
            select(Producto).where(
                Producto.empresa_id == empresa.id,
                Producto.router_id == router.id,
                Producto.activo == True
            ).order_by(Producto.orden_visual, Producto.destacado.desc())
        )
        
        productos = result.scalars().all()
        
        print(f"✅ Productos activos encontrados: {len(productos)}")
        
        if not productos:
            return []
        
        # Convertir usando model_validate
        productos_validados = []
        for producto in productos:
            try:
                # Intentar validación normal
                producto_validado = ProductoVentaResponse.model_validate(producto)
                productos_validados.append(producto_validado)
            except Exception as e:
                print(f"⚠️ Error validando producto ID {producto.id}: {e}")
                # Crear manualmente
                producto_validado = ProductoVentaResponse(
                    id=producto.id,
                    perfil_mikrotik_id=producto.perfil_mikrotik_id,
                    perfil_mikrotik_nombre=producto.perfil_mikrotik_nombre,
                    nombre_venta=producto.nombre_venta,
                    descripcion=producto.descripcion,
                    imagen_url=producto.imagen_url,
                    precio=float(producto.precio),
                    moneda=producto.moneda,
                    detalles=_normalizar_detalles(producto.detalles),
                    destacado=producto.destacado,
                    creado_en=producto.creado_en
                )
                productos_validados.append(producto_validado)
        
        print(f"🎉 Retornando {len(productos_validados)} productos")
        return productos_validados
        
    except Exception as e:
        print(f"❌ Error en endpoint: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Error al obtener catálogo: {str(e)}"
        )

# 3. ENDPOINT CON PARÁMETRO (debe ir DESPUÉS)
@router.get("/catalogo_perfiles_venta/{producto_id}", response_model=ProductoVentaResponse)
async def obtener_perfil_venta_detalle(
    producto_id: int,
    empresa_router: tuple = Depends(require_api_key),
    db: AsyncSession = Depends(get_db)
):
    """Obtener detalles de un producto específico"""
    empresa, router, metadata = empresa_router
    
    print(f"🔍 Buscando producto ID: {producto_id}")
    
    result = await db.execute(
        select(Producto).where(
            Producto.id == producto_id,
            Producto.empresa_id == empresa.id,
            Producto.router_id == router.id,
            Producto.activo == True
        )
    )
    
    producto = result.scalar_one_or_none()
    
    if not producto:
        raise HTTPException(
            status_code=404,
            detail="Producto no encontrado o no disponible"
        )
    
    try:
        return ProductoVentaResponse.model_validate(producto)
    except Exception as e:
        print(f"⚠️ Error validando producto: {e}")
        return ProductoVentaResponse(
            id=producto.id,
            perfil_mikrotik_id=producto.perfil_mikrotik_id,
            perfil_mikrotik_nombre=producto.perfil_mikrotik_nombre,
            nombre_venta=producto.nombre_venta,
            descripcion=producto.descripcion,
            imagen_url=producto.imagen_url,
            precio=float(producto.precio),
            moneda=producto.moneda,
            detalles=_normalizar_detalles(producto.detalles),
            destacado=producto.destacado,
            creado_en=producto.creado_en
        )