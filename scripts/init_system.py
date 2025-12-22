import asyncio
import bcrypt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import sys
import os

# Añadir al path
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app.core.database import AsyncSessionLocal
from app.core.config import settings
from app.models.usuario import Usuario

async def create_super_admin():
    print("👑 Creando super administrador...")
    
    async with AsyncSessionLocal() as db:
        # Verificar si ya existe
        result = await db.execute(
            select(Usuario).where(Usuario.email == settings.SUPER_ADMIN_INITIAL_EMAIL)
        )
        existing = result.scalar_one_or_none()
        
        if not existing:
            # Hashear contraseña
            hashed_pw = bcrypt.hashpw(
                settings.SUPER_ADMIN_INITIAL_PASSWORD.encode('utf-8'),
                bcrypt.gensalt()
            ).decode('utf-8')
            
            # Crear super admin
            admin = Usuario(
                email=settings.SUPER_ADMIN_INITIAL_EMAIL,
                password_hash=hashed_pw,
                nombre="Super Administrador",
                rol="super_admin",
                activo=True
            )
            
            db.add(admin)
            await db.commit()
            print(f"✅ Super admin creado: {settings.SUPER_ADMIN_INITIAL_EMAIL}")
            print(f"   Contraseña: {settings.SUPER_ADMIN_INITIAL_PASSWORD}")
        else:
            print("⚠️  Super admin ya existe")

if __name__ == "__main__":
    asyncio.run(create_super_admin())