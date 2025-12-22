# app/api/v1/admin/products.py - VERSIÓN COMPLETA CORREGIDA
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_serializer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional, List, Dict, Any
from datetime import datetime  # <-- IMPORTANTE: Agrega esto
import json

from app.core.database import get_db
from app.core.auth import require_cliente_admin
from app.models.empresa import Empresa
from app.models.router import Router
from app.models.producto import Producto

router = APIRouter()

# ========== SCHEMAS CORREGIDOS ==========
class ProductoCreateRequest(BaseModel):
    router_id: str
    perfil_mikrotik_id: str
    perfil_mikrotik_nombre: str
    nombre_venta: str
    descripcion: Optional[str] = None
    imagen_url: Optional[str] = None
    precio: float
    moneda: str = "MXN"
    detalles: Optional[List[Dict[str, Any]]] = []
    activo: bool = True
    orden_visual: int = 0
    destacado: bool = False

class ProductoUpdateRequest(BaseModel):
    nombre_venta: Optional[str] = None
    descripcion: Optional[str] = None
    imagen_url: Optional[str] = None
    precio: Optional[float] = None
    detalles: Optional[List[Dict[str, Any]]] = None
    activo: Optional[bool] = None
    orden_visual: Optional[int] = None
    destacado: Optional[bool] = None

class ProductoResponse(BaseModel):
    id: int
    router_id: str
    perfil_mikrotik_id: str
    perfil_mikrotik_nombre: str
    nombre_venta: str
    descripcion: Optional[str]
    imagen_url: Optional[str]
    precio: float
    moneda: str
    detalles: List[Dict[str, Any]]
    activo: bool
    orden_visual: int
    destacado: bool
    creado_en: datetime  # <-- CAMBIADO de str a datetime
    
    class Config:
        from_attributes = True
    
    @field_serializer('creado_en')
    def serialize_creado_en(self, creado_en: datetime, _info):
        """Convertir datetime a string ISO para JSON"""
        return creado_en.isoformat() if creado_en else None
    
    @field_serializer('detalles')
    def serialize_detalles(self, detalles: List[Dict[str, Any]], _info):
        """Asegurar que detalles sea una lista JSON serializable"""
        return detalles or []

# ========== ENDPOINTS ==========
@router.post("/products", response_model=ProductoResponse, status_code=status.HTTP_201_CREATED)
async def crear_producto(
    producto_data: ProductoCreateRequest,
    usuario = Depends(require_cliente_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Crear nuevo producto para venta (SOLO CLIENTE_ADMIN)
    """
    print(f"📦 Creando producto: {producto_data.nombre_venta}")
    
    # 1. Verificar que el router pertenece a la empresa del usuario
    result = await db.execute(
        select(Router).where(
            Router.id == producto_data.router_id,
            Router.empresa_id == usuario.empresa_id
        )
    )
    router = result.scalar_one_or_none()
    
    if not router:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Router no encontrado o no pertenece a tu empresa"
        )
    
    print(f"✅ Router encontrado: {router.nombre}")
    
    # 2. Verificar que el router esté activo
    if not router.activo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se pueden crear productos para routers inactivos"
        )
    
    # 3. Verificar que no exista ya un producto con el mismo perfil
    existing_product = await db.execute(
        select(Producto).where(
            Producto.empresa_id == usuario.empresa_id,
            Producto.router_id == producto_data.router_id,
            Producto.perfil_mikrotik_id == producto_data.perfil_mikrotik_id,
            Producto.activo == True
        )
    )
    
    if existing_product.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ya existe un producto activo con este perfil de MikroTik"
        )
    
    # 4. Crear producto
    producto = Producto(
        empresa_id=usuario.empresa_id,
        router_id=producto_data.router_id,
        perfil_mikrotik_id=producto_data.perfil_mikrotik_id,
        perfil_mikrotik_nombre=producto_data.perfil_mikrotik_nombre,
        nombre_venta=producto_data.nombre_venta,
        descripcion=producto_data.descripcion,
        imagen_url=producto_data.imagen_url,
        precio=producto_data.precio,
        moneda=producto_data.moneda,
        detalles=producto_data.detalles or [],
        activo=producto_data.activo,
        orden_visual=producto_data.orden_visual,
        destacado=producto_data.destacado
    )
    
    db.add(producto)
    await db.commit()
    await db.refresh(producto)
    
    print(f"✅ Producto creado ID: {producto.id}")
    
    # 5. Retornar usando el schema corregido
    return ProductoResponse.model_validate(producto)

@router.get("/products", response_model=List[ProductoResponse])
async def listar_productos(
    activos: bool = True,
    router_id: Optional[str] = None,
    destacados: Optional[bool] = None,
    usuario = Depends(require_cliente_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Listar productos de mi empresa (SOLO CLIENTE_ADMIN)
    """
    # Construir query base
    query = select(Producto).where(
        Producto.empresa_id == usuario.empresa_id
    )
    
    # Aplicar filtros
    if activos:
        query = query.where(Producto.activo == True)
    
    if router_id:
        # Verificar que el router pertenezca a la empresa
        result = await db.execute(
            select(Router).where(
                Router.id == router_id,
                Router.empresa_id == usuario.empresa_id
            )
        )
        if not result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Router no encontrado o no pertenece a tu empresa"
            )
        query = query.where(Producto.router_id == router_id)
    
    if destacados is not None:
        query = query.where(Producto.destacado == destacados)
    
    # Ordenar
    query = query.order_by(Producto.orden_visual, Producto.creado_en.desc())
    
    # Ejecutar
    result = await db.execute(query)
    productos = result.scalars().all()
    
    # Convertir usando model_validate en lugar de from_orm
    return [ProductoResponse.model_validate(p) for p in productos]

@router.get("/products/{producto_id}", response_model=ProductoResponse)
async def obtener_producto(
    producto_id: int,
    usuario = Depends(require_cliente_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Obtener detalles de un producto específico (SOLO CLIENTE_ADMIN)
    """
    result = await db.execute(
        select(Producto).where(
            Producto.id == producto_id,
            Producto.empresa_id == usuario.empresa_id
        )
    )
    producto = result.scalar_one_or_none()
    
    if not producto:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Producto no encontrado"
        )
    
    return ProductoResponse.model_validate(producto)

@router.put("/products/{producto_id}", response_model=ProductoResponse)
async def actualizar_producto(
    producto_id: int,
    producto_data: ProductoUpdateRequest,
    usuario = Depends(require_cliente_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Actualizar producto existente (SOLO CLIENTE_ADMIN)
    """
    # Obtener producto
    result = await db.execute(
        select(Producto).where(
            Producto.id == producto_id,
            Producto.empresa_id == usuario.empresa_id
        )
    )
    producto = result.scalar_one_or_none()
    
    if not producto:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Producto no encontrado"
        )
    
    # Actualizar campos
    update_data = producto_data.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(producto, field, value)
    
    await db.commit()
    await db.refresh(producto)
    
    return ProductoResponse.model_validate(producto)

@router.delete("/products/{producto_id}")
async def eliminar_producto(
    producto_id: int,
    usuario = Depends(require_cliente_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Eliminar producto (SOLO CLIENTE_ADMIN)
    
    En realidad desactiva el producto, no lo elimina físicamente
    para mantener histórico de transacciones.
    """
    result = await db.execute(
        select(Producto).where(
            Producto.id == producto_id,
            Producto.empresa_id == usuario.empresa_id
        )
    )
    producto = result.scalar_one_or_none()
    
    if not producto:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Producto no encontrado"
        )
    
    # Verificar si hay transacciones asociadas
    if producto.transacciones:
        # Si hay transacciones, solo desactivamos
        producto.activo = False
        await db.commit()
        
        return {
            "message": "Producto desactivado (tiene transacciones asociadas)",
            "producto_id": producto_id,
            "activo": False
        }
    else:
        # Si no hay transacciones, podemos eliminar
        await db.delete(producto)
        await db.commit()
        
        return {
            "message": "Producto eliminado permanentemente",
            "producto_id": producto_id
        }

@router.put("/products/{producto_id}/toggle-activo")
async def toggle_activo_producto(
    producto_id: int,
    usuario = Depends(require_cliente_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Activar/desactivar producto (SOLO CLIENTE_ADMIN)
    """
    result = await db.execute(
        select(Producto).where(
            Producto.id == producto_id,
            Producto.empresa_id == usuario.empresa_id
        )
    )
    producto = result.scalar_one_or_none()
    
    if not producto:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Producto no encontrado"
        )
    
    producto.activo = not producto.activo
    await db.commit()
    await db.refresh(producto)
    
    return {
        "message": f"Producto {'activado' if producto.activo else 'desactivado'} correctamente",
        "producto_id": producto_id,
        "activo": producto.activo
    }