from fastapi import APIRouter, Depends
from app.core.auth import require_api_key

router = APIRouter(tags=["Configuration"])

@router.get("/public")
async def get_public_config(
     auth_data = Depends(require_api_key)
):
    """Config para frontend cliente (incluye API Key pública Conekta)"""
    empresa, router, _ = auth_data
    
    return {
        "empresa": {
            "id": empresa.id,
            "nombre": empresa.nombre,
            "conekta_public_key": empresa.conekta_public_key,
            "conekta_mode": empresa.conekta_mode
        },
        "router": {
            "id": router.id,
            "nombre": router.nombre,
            "ubicacion": router.ubicacion
        }
    }