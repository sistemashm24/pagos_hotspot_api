from pydantic import BaseModel, EmailStr

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class UserCreateRequest(BaseModel):
    email: EmailStr
    password: str
    nombre: str
    rol: str
    empresa_id: str = None