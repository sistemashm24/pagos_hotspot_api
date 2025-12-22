# app/core/security.py - VERSIÓN CORREGIDA
from passlib.context import CryptContext
from datetime import datetime, timedelta
from typing import Optional
from jose import jwt  # ← ¡CORREGIDO! Importa jwt de jose
from .config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            hours=settings.JWT_SESSION_EXPIRE_HOURS
        )
    
    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "access_token"
    })
    
    encoded_jwt = jwt.encode(
        to_encode, 
        settings.JWT_SESSION_SECRET, 
        algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt