# app/schemas/response/auth.py - VERSIÓN MEJORADA
from pydantic import BaseModel, field_validator, ConfigDict
from datetime import datetime
from typing import Optional, Any

class UserResponse(BaseModel):
    id: int
    email: str
    nombre: str
    rol: str
    empresa_id: Optional[str] = None
    activo: bool
    
    @field_validator('empresa_id', mode='before')
    @classmethod
    def handle_empresa_id(cls, v: Any) -> Optional[str]:
        """
        Maneja empresa_id para convertir cualquier valor 'None-like' a None explícito
        """
        # Si es None o string vacío, retornar None
        if v is None:
            return None
        
        # Si es string, verificar si está vacío o es "None"
        if isinstance(v, str):
            v_clean = v.strip()
            if v_clean == "" or v_clean.lower() == "none":
                return None
            return v_clean
        
        # Si es otro tipo, convertir a string
        return str(v)
    
    model_config = ConfigDict(from_attributes=True)

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserResponse