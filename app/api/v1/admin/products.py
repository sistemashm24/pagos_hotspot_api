from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator, field_serializer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional, List, Dict, Any
from datetime import datetime

from app.core.database import get_db
from app.core.auth import require_cliente_admin
from app.models.router import Router
from app.models.producto import Producto

router = APIRouter()

# ======================================================
# SCHEMAS
# ======================================================

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
    detalles: List[str]
    activo: bool
    orden_visual: int
    destacado: bool
    creado_en: datetime

    model_config = {"from_attributes": True}

    # 🔥 NORMALIZA detalles desde BD
    @field_validator("detalles", mode="before")
    @classmethod
    def normalizar_detalles(cls, v):
        if not v:
            return []
        if isinstance(v[0], dict):
            return [d.get("texto", "") for d in v]
        return v

    @field_serializer("creado_en")
    def serialize_creado_en(self, creado_en: datetime, _info):
        return creado_en.isoformat() if creado_en else None


# ======================================================
# ENDPOINTS
# ======================================================

@router.post("/products", response_model=ProductoResponse, status_code=status.HTTP_201_CREATED)
async def crear_producto(
    producto_data: ProductoCreateRequest,
    usuario = Depends(require_cliente_admin),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Router).where(
            Router.id == producto_data.router_id,
            Router.empresa_id == usuario.empresa_id
        )
    )
    router = result.scalar_one_or_none()

    if not router:
        raise HTTPException(status_code=404, detail="Router no encontrado")

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

    return ProductoResponse.model_validate(producto)


@router.get("/products", response_model=List[ProductoResponse])
async def listar_productos(
    router_id: Optional[str] = None,
    usuario = Depends(require_cliente_admin),
    db: AsyncSession = Depends(get_db)
):
    query = select(Producto).where(
        Producto.empresa_id == usuario.empresa_id
    )

    if router_id:
        result = await db.execute(
            select(Router).where(
                Router.id == router_id,
                Router.empresa_id == usuario.empresa_id
            )
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Router no encontrado")
        query = query.where(Producto.router_id == router_id)

    query = query.order_by(
        Producto.orden_visual,
        Producto.creado_en.desc()
    )

    result = await db.execute(query)
    productos = result.scalars().all()

    return [ProductoResponse.model_validate(p) for p in productos]


@router.get("/products/{producto_id}", response_model=ProductoResponse)
async def obtener_producto(
    producto_id: int,
    usuario = Depends(require_cliente_admin),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Producto).where(
            Producto.id == producto_id,
            Producto.empresa_id == usuario.empresa_id
        )
    )
    producto = result.scalar_one_or_none()

    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    return ProductoResponse.model_validate(producto)


@router.put("/products/{producto_id}", response_model=ProductoResponse)
async def actualizar_producto(
    producto_id: int,
    producto_data: ProductoUpdateRequest,
    usuario = Depends(require_cliente_admin),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Producto).where(
            Producto.id == producto_id,
            Producto.empresa_id == usuario.empresa_id
        )
    )
    producto = result.scalar_one_or_none()

    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    for field, value in producto_data.dict(exclude_unset=True).items():
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
    result = await db.execute(
        select(Producto).where(
            Producto.id == producto_id,
            Producto.empresa_id == usuario.empresa_id
        )
    )
    producto = result.scalar_one_or_none()

    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    producto.activo = False
    await db.commit()

    return {
        "message": "Producto desactivado",
        "producto_id": producto_id,
        "activo": False
    }
