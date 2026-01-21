# main.py - VERSIÓN WINDOWS (ACTUALIZADO CON MERCADO PAGO)
import sys
import os
from pathlib import Path

# DEBUG: Mostrar path actual
print("=== INICIANDO EN WINDOWS ===")
print(f"Directorio actual: {os.getcwd()}")
print(f"Python path: {sys.path}")

# Agregar raíz del proyecto AL PRINCIPIO del path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from datetime import datetime, timezone


print("\n=== CARGANDO MÓDULOS ===")

# Diccionario de módulos a cargar (ACTUALIZADO CON MERCADO PAGO)
modulos_config = {
    # Públicos V1
    "app.api.v1.auth": {
        "router_name": "router",
        "prefix": "/api/v1/auth",
        "tags": ["Authentication"]
    },
    "app.api.v1.config": {
        "router_name": "router", 
        "prefix": "/api/v1/config",
        "tags": ["Configuration"]
    },
    "app.api.v1.payments": {
        "router_name": "router",
        "prefix": "/api/v1/payments", 
        "tags": ["Pagar Hotspot"]
    },
    # ✅ NUEVO: Mercado Pago
    "app.api.v1.mercado_pago": {
        "router_name": "router",
        "prefix": "/api/v1/payments",
        "tags": ["Pagar Hotspot - Mercado Pago"]
    },
    "app.api.v1.catalogo_perfiles_venta": {
        "router_name": "router",
        "prefix": "/api/v1",
        "tags": ["Catalog"]
    },
    # ✅ NUEVO: Endpoint de Reconexión Automática Hotspot
    "app.api.v1.hotspot.auto_reconnect": {
        "router_name": "router", 
        "prefix": "/api/v1",
        "tags": ["Hotspot - Reconexión Automática"]
    },
    
    # Cliente Admin
    "app.api.v1.admin.empresa": {
        "router_name": "router",
        "prefix": "/api/v1/admin",
        "tags": ["Cliente Admin"]
    },
    "app.api.v1.admin.products": {
        "router_name": "router",
        "prefix": "/api/v1/admin",
        "tags": ["Cliente Admin - Products"]
    },
    "app.api.v1.admin.mikrotik_perfiles": {
        "router_name": "router", 
        "prefix": "/api/v1/admin",
        "tags": ["Cliente Admin - MikroTik"]
    },
    
    # Super Admin
    "app.api.admin.empresas": {
        "router_name": "router",
        "prefix": "/admin",
        "tags": ["Super Admin"]
    },
    "app.api.admin.routers": {
        "router_name": "router",
        "prefix": "/admin", 
        "tags": ["Super Admin - Routers"]
    },
    "app.api.admin.usuarios": {
        "router_name": "router",
        "prefix": "/admin",
        "tags": ["Super Admin - Usuarios"]
    },
    # ✅ NUEVO: Webhook de Mercado Pago
    "app.api.v1.webhooks": {
        "router_name": "router",
        "prefix": "/api/v1/webhook",
        "tags": ["Webhooks"]
    }
}

app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "API **multi-empresa** para procesar pagos con Mercado Pago o Conekta, "
        "crear y gestionar usuarios en Hotspot MikroTik, recibir notificaciones vía webhooks, "
        "y permitir **autoconexión automática** en dispositivos con MAC aleatorio (random MAC).\n\n"
        "**Características principales:**\n"
        "- Pagos con Mercado Pago y Conekta (tarjeta de credito y debito)\n"
        "- Integración con MikroTik Hotspot\n"
        "- Webhooks por empresa para actualizaciones en tiempo real\n"
        "- Autenticación mediante API Keys\n"
        "- Gestión independiente y segura por empresa\n"
        "- **Autoconexión sin necesidad de login manual**, compatible con MAC random"
    ),
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Cargar dinámicamente cada módulo
for module_path, config in modulos_config.items():
    try:
        # Importar el módulo
        module = __import__(module_path, fromlist=[''])
        
        # Obtener el router
        if hasattr(module, config["router_name"]):
            router = getattr(module, config["router_name"])
            app.include_router(router, prefix=config["prefix"], tags=config["tags"])
            print(f"✅ {module_path} cargado en {config['prefix']}")
        else:
            print(f"⚠️  {module_path} no tiene '{config['router_name']}'")
            
    except ModuleNotFoundError as e:
        print(f"❌ No se pudo encontrar {module_path}: {e}")
    except Exception as e:
        print(f"❌ Error cargando {module_path}: {e}")

print("\n=== SERVIDOR LISTO ===")


@app.get("/", summary="Estado de la API", tags=["Health"])
async def root():
    return {
        "message": "Sistema de pagos y gestión de accesos WiFi para hotspots MikroTik",
        "version": "2.0.0",
        "status": "running",        
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z",
        "docs": "/docs"
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)