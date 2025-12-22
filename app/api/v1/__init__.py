# app/api/v1/__init__.py
from . import auth, config, payments, catalogo_perfiles_venta
from .admin import empresa, products, mikrotik_perfiles

__all__ = [
    "auth",
    "config", 
    "payments",
    "catalogo_perfiles_venta",
    "empresa",
    "products",
    "mikrotik_perfiles"
]