import os
from typing import List
from pydantic_settings import BaseSettings
from pydantic import Field, validator
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = Field(..., env="DATABASE_URL")
    DATABASE_POOL_SIZE: int = Field(20, env="DATABASE_POOL_SIZE")
    
    # JWT Secrets
    JWT_APIKEY_SECRET: str = Field(..., env="JWT_APIKEY_SECRET")
    JWT_SESSION_SECRET: str = Field(..., env="JWT_SESSION_SECRET")
    JWT_ALGORITHM: str = Field("HS256", env="JWT_ALGORITHM")
    JWT_APIKEY_EXPIRE_DAYS: int = Field(365, env="JWT_APIKEY_EXPIRE_DAYS")
    JWT_SESSION_EXPIRE_HOURS: int = Field(24, env="JWT_SESSION_EXPIRE_HOURS")
    
    # Security
    SECRET_KEY: str = Field(..., env="SECRET_KEY")
    BCRYPT_ROUNDS: int = Field(12, env="BCRYPT_ROUNDS")
    
    # CORS
    BACKEND_CORS_ORIGINS: List[str] = Field([], env="BACKEND_CORS_ORIGINS")
    
    # Admin
    SUPER_ADMIN_INITIAL_EMAIL: str = Field(..., env="SUPER_ADMIN_INITIAL_EMAIL")
    SUPER_ADMIN_INITIAL_PASSWORD: str = Field(..., env="SUPER_ADMIN_INITIAL_PASSWORD")
    
    # Conekta
    CONEKTA_DEFAULT_PRIVATE_KEY: str = Field("", env="CONEKTA_DEFAULT_PRIVATE_KEY")
    CONEKTA_DEFAULT_PUBLIC_KEY: str = Field("", env="CONEKTA_DEFAULT_PUBLIC_KEY")
    
    # Clave para encriptar access_token y webhook_secret de Mercado Pago
    ENCRYPTION_KEY_MERCADO_PAGO: str = Field("", env="ENCRYPTION_KEY_MERCADO_PAGO")
    
    # App
    APP_NAME: str = Field("MikroTik Payment API", env="APP_NAME")
    DEBUG: bool = Field(False, env="DEBUG")
    
    @validator("BACKEND_CORS_ORIGINS", pre=True)
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v
    
    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()