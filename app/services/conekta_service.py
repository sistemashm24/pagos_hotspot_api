# app/services/conekta_service.py - VERSIÓN COMPLETA CON TODOS LOS ERRORES
import aiohttp
import asyncio
import base64
import json
import logging
from typing import Dict, Any, Optional
from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

class ConektaService:
    """Servicio para procesar pagos con Conekta - TODOS LOS ERRORES"""
    
    BASE_URL = "https://api.conekta.io"
    
    # 🎯 MAPEO COMPLETO DE ERRORES DE CONEKTA
    # Basado en: https://developers.conekta.com/reference/errores
    CONEKTA_ERRORS = {
        # ======================
        # ERRORES DE PROCESAMIENTO (40x)
        # ======================
        "processing_error": {
            "message": "Error al procesar el pago.",
            "user_message": "Error al procesar el pago. Intente nuevamente."
        },
        
        # Tokenización
        "conekta.errors.processing.tokenization.used": {
            "message": "The token has already been used.",
            "user_message": "El token de tarjeta ya fue utilizado. Genere un nuevo token."
        },
        "conekta.errors.processing.tokenization.invalid": {
            "message": "Invalid token.",
            "user_message": "Token de tarjeta inválido. Genere un nuevo token."
        },
        "conekta.errors.processing.tokenization.expired": {
            "message": "Token expired.",
            "user_message": "Token de tarjeta expirado. Genere un nuevo token."
        },
        
        # Tarjetas
        "card_declined": {
            "message": "Card was declined.",
            "user_message": "Tarjeta declinada. Contacte a su banco."
        },
        "insufficient_funds": {
            "message": "Insufficient funds.",
            "user_message": "Fondos insuficientes en la tarjeta."
        },
        "expired_card": {
            "message": "Expired card.",
            "user_message": "Tarjeta expirada. Use otra tarjeta."
        },
        "invalid_card": {
            "message": "Invalid card.",
            "user_message": "Tarjeta inválida. Verifique los datos."
        },
        "stolen_card": {
            "message": "Stolen card.",
            "user_message": "Tarjeta reportada como robada."
        },
        "suspected_fraud": {
            "message": "Suspected fraud.",
            "user_message": "Actividad sospechosa detectada."
        },
        "card_not_supported": {
            "message": "Card not supported.",
            "user_message": "Tarjeta no soportada."
        },
        "card_number_incorrect": {
            "message": "Card number incorrect.",
            "user_message": "Número de tarjeta incorrecto."
        },
        "cvv_incorrect": {
            "message": "CVV incorrect.",
            "user_message": "Código de seguridad (CVV) incorrecto."
        },
        
        # ======================
        # ERRORES DE VALIDACIÓN (30x)
        # ======================
        "parameter_validation_error": {
            "message": "Parameter validation error.",
            "user_message": "Datos inválidos en la solicitud."
        },
        "invalid_parameter": {
            "message": "Invalid parameter.",
            "user_message": "Parámetro inválido."
        },
        "missing_parameter": {
            "message": "Missing parameter.",
            "user_message": "Falta parámetro requerido."
        },
        "invalid_amount": {
            "message": "Invalid amount.",
            "user_message": "Monto inválido."
        },
        "invalid_currency": {
            "message": "Invalid currency.",
            "user_message": "Moneda inválida."
        },
        "invalid_email": {
            "message": "Invalid email.",
            "user_message": "Correo electrónico inválido."
        },
        "invalid_phone": {
            "message": "Invalid phone.",
            "user_message": "Número de teléfono inválido."
        },
        
        # ======================
        # ERRORES DE AUTENTICACIÓN (20x)
        # ======================
        "authentication_error": {
            "message": "Authentication error.",
            "user_message": "Error de autenticación. Contacte al administrador."
        },
        "invalid_api_key": {
            "message": "Invalid API key.",
            "user_message": "Clave API inválida."
        },
        "unauthorized_request": {
            "message": "Unauthorized request.",
            "user_message": "No autorizado."
        },
        
        # ======================
        # ERRORES DE RECURSO (10x)
        # ======================
        "resource_not_found": {
            "message": "Resource not found.",
            "user_message": "Recurso no encontrado."
        },
        "order_not_found": {
            "message": "Order not found.",
            "user_message": "Orden no encontrada."
        },
        "customer_not_found": {
            "message": "Customer not found.",
            "user_message": "Cliente no encontrado."
        },
        
        # ======================
        # ERRORES DE GATEWAY (50x)
        # ======================
        "gateway_error": {
            "message": "Gateway error.",
            "user_message": "Error en el procesador de pagos."
        },
        "bank_connection_error": {
            "message": "Bank connection error.",
            "user_message": "Error de conexión con el banco."
        },
        "server_error": {
            "message": "Server error.",
            "user_message": "Error interno del servidor."
        },
        
        # ======================
        # ERRORES DE LÍMITE
        # ======================
        "rate_limit_exceeded": {
            "message": "Rate limit exceeded.",
            "user_message": "Límite de solicitudes excedido. Espere un momento."
        },
        "quota_exceeded": {
            "message": "Quota exceeded.",
            "user_message": "Cuota excedida. Contacte a Conekta."
        },
        
        # ======================
        # DEFAULT
        # ======================
        "default": {
            "message": "Unknown error.",
            "user_message": "Error al procesar el pago. Intente nuevamente."
        }
    }

    async def create_order(
        self,
        private_key: str,
        mode: str,
        amount: float,
        currency: str,
        card_token: str,
        customer_info: Dict[str, Any],
        description: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Crear orden de pago en Conekta - MANEJO COMPLETO DE ERRORES"""
        
        print(f"🔍 [CONEKTA] Iniciando pago...")
        
        try:
            # Validaciones básicas
            if not card_token or card_token == "tok_2zD9Phs4sGnJN9ckc":  # Token de prueba usado
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Token de tarjeta inválido o ya utilizado."
                )
            
            # Normalizar teléfono
            normalized_phone = self._normalize_phone(customer_info.get("telefono", ""))
            
            url = f"{self.BASE_URL}/orders"
            amount_cents = int(amount * 100)
            
            payload = {
                "currency": currency.upper(),
                "customer_info": {
                    "name": customer_info.get("nombre", ""),
                    "email": customer_info.get("email", ""),
                    "phone": normalized_phone
                },
                "line_items": [{
                    "name": description[:250],
                    "unit_price": amount_cents,
                    "quantity": 1
                }],
                "charges": [{
                    "payment_method": {
                        "type": "card",
                        "token_id": card_token
                    }
                }],
                "metadata": metadata or {}
            }
            
            auth_str = f"{private_key}:"
            auth_b64 = base64.b64encode(auth_str.encode()).decode()
            
            headers = {
                "Accept": "application/vnd.conekta-v2.1.0+json",
                "Content-Type": "application/json",
                "Authorization": f"Basic {auth_b64}",
                "User-Agent": "MikroTik-Payment-API/1.0"
            }
            
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                
                async with session.post(url, json=payload, headers=headers) as resp:
                    
                    response_text = await resp.text()
                    status_code = resp.status
                    
                    # Log para debugging
                    if status_code != 200:
                        print(f"❌ Conekta Status: {status_code}")
                        print(f"📄 Respuesta: {response_text[:500]}")
                    
                    # Parsear respuesta
                    try:
                        data = json.loads(response_text) if response_text else {}
                    except json.JSONDecodeError:
                        data = {"raw_response": response_text}
                    
                    # ✅ Éxito
                    if status_code == 200:
                        print(f"✅ Pago exitoso - ID: {data.get('id')}")
                        
                        # Validar que el pago realmente está "paid"
                        payment_status = data.get("payment_status", "").lower()
                        if payment_status != "paid":
                            print(f"⚠️  Estado inesperado: {payment_status}")
                            # Aún así retornamos, pero el endpoint hará validación adicional
                        
                        return {
                            "order_id": data.get("id"),
                            "payment_status": data.get("payment_status", ""),
                            "amount": data.get("amount", 0) / 100,
                            "currency": data.get("currency"),
                            "created_at": data.get("created_at"),
                            "customer_info": data.get("customer_info", {})
                        }
                    
                    # ❌ Error - Manejo completo
                    else:
                        error_info = self._parse_conekta_error_response(data, status_code)
                        
                        print(f"❌ Error Conekta: {error_info['code']} - {error_info['user_message']}")
                        
                        # Lanzar excepción apropiada
                        if status_code == 402:
                            raise HTTPException(
                                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                                detail=error_info["user_message"]
                            )
                        elif status_code == 400:
                            raise HTTPException(
                                status_code=status.HTTP_400_BAD_REQUEST,
                                detail=error_info["user_message"]
                            )
                        elif status_code == 401:
                            raise HTTPException(
                                status_code=status.HTTP_401_UNAUTHORIZED,
                                detail=error_info["user_message"]
                            )
                        elif status_code == 404:
                            raise HTTPException(
                                status_code=status.HTTP_404_NOT_FOUND,
                                detail=error_info["user_message"]
                            )
                        elif status_code == 422:
                            raise HTTPException(
                                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail=error_info["user_message"]
                            )
                        elif status_code == 429:
                            raise HTTPException(
                                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                                detail=error_info["user_message"]
                            )
                        else:
                            raise HTTPException(
                                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                                detail=error_info["user_message"]
                            )
                        
        except asyncio.TimeoutError:
            error_msg = "Tiempo de espera agotado al conectar con Conekta."
            print(f"⏰ {error_msg}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Tiempo de espera agotado. Intente nuevamente."
            )
        except HTTPException:
            raise  # Re-lanzar excepciones HTTP ya manejadas
        except Exception as e:
            error_msg = "Error interno al procesar el pago."
            print(f"💥 Error inesperado: {type(e).__name__}: {str(e)}")
            import traceback
            traceback.print_exc()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=error_msg
            )
    
    def _parse_conekta_error_response(self, data: Dict, status_code: int) -> Dict[str, str]:
        """
        Parsear respuesta de error de Conekta de manera completa
        
        Returns:
            Dict con: {"code": "error_code", "message": "msg técnico", "user_message": "msg para usuario"}
        """
        error_code = "default"
        technical_message = "Unknown error"
        user_message = self.CONEKTA_ERRORS["default"]["user_message"]
        
        # 1. Extraer código de error
        if "details" in data and isinstance(data["details"], list) and data["details"]:
            detail = data["details"][0]
            error_code = detail.get("code", "")
            
            # Si no hay código en details, buscar en type
            if not error_code and "type" in data:
                error_code = data["type"]
            
            # Buscar mensaje técnico
            technical_message = detail.get("debug_message", detail.get("message", ""))
            
        elif "type" in data:
            error_code = data["type"]
            technical_message = data.get("message", "")
        
        elif "message" in data:
            technical_message = data["message"]
        
        # 2. Normalizar código de error
        error_code_lower = error_code.lower().strip()
        
        # Buscar coincidencia exacta o parcial
        matched_error = None
        for known_error in self.CONEKTA_ERRORS:
            if known_error in error_code_lower or error_code_lower in known_error:
                matched_error = known_error
                break
        
        # 3. Obtener mensajes
        if matched_error and matched_error in self.CONEKTA_ERRORS:
            error_info = self.CONEKTA_ERRORS[matched_error]
            user_message = error_info["user_message"]
        else:
            # Si no encontramos coincidencia, intentar deducir del mensaje
            tech_lower = technical_message.lower()
            
            if any(word in tech_lower for word in ["token", "tokenization"]):
                if "already" in tech_lower or "used" in tech_lower:
                    user_message = self.CONEKTA_ERRORS["conekta.errors.processing.tokenization.used"]["user_message"]
                elif "invalid" in tech_lower:
                    user_message = self.CONEKTA_ERRORS["conekta.errors.processing.tokenization.invalid"]["user_message"]
                elif "expired" in tech_lower:
                    user_message = self.CONEKTA_ERRORS["conekta.errors.processing.tokenization.expired"]["user_message"]
            
            elif "card" in tech_lower or "tarjeta" in tech_lower:
                if "declined" in tech_lower or "rechazada" in tech_lower:
                    user_message = self.CONEKTA_ERRORS["card_declined"]["user_message"]
                elif "insufficient" in tech_lower or "fondos" in tech_lower:
                    user_message = self.CONEKTA_ERRORS["insufficient_funds"]["user_message"]
                elif "expired" in tech_lower or "expirada" in tech_lower:
                    user_message = self.CONEKTA_ERRORS["expired_card"]["user_message"]
                elif "invalid" in tech_lower or "inválida" in tech_lower:
                    user_message = self.CONEKTA_ERRORS["invalid_card"]["user_message"]
            
            elif "funds" in tech_lower:
                user_message = self.CONEKTA_ERRORS["insufficient_funds"]["user_message"]
            
            elif "authentication" in tech_lower or "auth" in tech_lower:
                user_message = self.CONEKTA_ERRORS["authentication_error"]["user_message"]
            
            elif "parameter" in tech_lower or "validation" in tech_lower:
                user_message = self.CONEKTA_ERRORS["parameter_validation_error"]["user_message"]
        
        return {
            "code": error_code,
            "message": technical_message,
            "user_message": user_message
        }
    
    def _normalize_phone(self, phone: str) -> str:
        """Normalizar número de teléfono"""
        if not phone:
            return "+521234567890"
            
        digits = ''.join(filter(str.isdigit, phone))
        
        if len(digits) == 12 and digits.startswith('52'):
            return f"+{digits}"
        elif len(digits) == 10:
            return f"+52{digits}"
        else:
            return "+521234567890"

# Instancia global
conekta_service = ConektaService()