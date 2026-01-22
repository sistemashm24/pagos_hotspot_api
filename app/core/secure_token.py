# app/core/secure_token.py

import os
import logging
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

class SecureTokenManager:
    def __init__(self):
        key = os.getenv("ENCRYPTION_KEY_MERCADO_PAGO")

        if not key:
            raise ValueError(
                "ENCRYPTION_KEY_MERCADO_PAGO no está configurada en el .env"
            )

        try:
            # Fernet espera la clave BASE64 tal cual (44 chars)
            self.cipher = Fernet(key.encode())
        except Exception as e:
            raise ValueError(f"Clave ENCRYPTION_KEY_MERCADO_PAGO inválida: {str(e)}")

    def encrypt(self, value: str) -> str | None:
        if not value or not value.strip():
            return None
        return self.cipher.encrypt(value.strip().encode()).decode()

    def decrypt(self, encrypted: str) -> str | None:
        if not encrypted or not encrypted.strip():
            return None
        try:
            return self.cipher.decrypt(encrypted.encode()).decode()
        except InvalidToken:
            return None

    
    def decrypt_if_needed(self, value: str) -> str:
        if not value:
            return value
        try:
            return self.cipher.decrypt(value.encode()).decode()
        except Exception:
            return value
