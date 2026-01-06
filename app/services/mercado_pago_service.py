# app/services/mercado_pago_service.py
import mercadopago
import json
import uuid
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
from fastapi import HTTPException, status
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

class MercadoPagoService:
    """Servicio para procesar pagos con Mercado Pago - CON TODOS LOS REQUISITOS"""
    
    # 🎯 MAPEO COMPLETO DE ERRORES DE MERCADO PAGO
    MP_ERRORS = {
        # ======================
        # ERRORES DE FONDOS Y TARJETAS
        # ======================
        "cc_rejected_insufficient_amount": {
            "message": "Fondos insuficientes",
            "user_message": "❌ Fondos insuficientes en la tarjeta.",
            "categoria": "fondos",
            "severidad": "alta"
        },
        "cc_rejected_bad_filled_card_number": {
            "message": "Número de tarjeta incorrecto",
            "user_message": "❌ Número de tarjeta incorrecto. Verifique los datos.",
            "categoria": "datos",
            "severidad": "media"
        },
        "cc_rejected_bad_filled_date": {
            "message": "Fecha de vencimiento incorrecta",
            "user_message": "❌ Fecha de vencimiento incorrecta.",
            "categoria": "datos",
            "severidad": "media"
        },
        "cc_rejected_bad_filled_security_code": {
            "message": "CVV incorrecto",
            "user_message": "❌ Código de seguridad (CVV) incorrecto.",
            "categoria": "datos",
            "severidad": "media"
        },
        "cc_rejected_high_risk": {
            "message": "Alto riesgo",
            "user_message": "⚠️ Pago rechazado por políticas de seguridad.",
            "categoria": "seguridad",
            "severidad": "alta"
        },
        "cc_rejected_card_disabled": {
            "message": "Tarjeta deshabilitada",
            "user_message": "❌ Tarjeta deshabilitada. Contacte a su banco.",
            "categoria": "tarjeta",
            "severidad": "alta"
        },
        "cc_rejected_blacklist": {
            "message": "Tarjeta en lista negra",
            "user_message": "❌ No se puede procesar el pago con esta tarjeta.",
            "categoria": "tarjeta",
            "severidad": "alta"
        },
        "cc_rejected_card_error": {
            "message": "Error en tarjeta",
            "user_message": "❌ Error al procesar la tarjeta. Intente nuevamente.",
            "categoria": "tarjeta",
            "severidad": "media"
        },
        "cc_rejected_duplicated_payment": {
            "message": "Pago duplicado",
            "user_message": "⚠️ Este pago ya fue procesado anteriormente.",
            "categoria": "duplicado",
            "severidad": "media"
        },
        "cc_rejected_call_for_authorize": {
            "message": "Requiere autorización",
            "user_message": "⚠️ El pago requiere autorización del banco.",
            "categoria": "autorizacion",
            "severidad": "media"
        },
        "cc_rejected_max_attempts": {
            "message": "Máximo de intentos excedido",
            "user_message": "⏰ Máximo de intentos excedido. Espere e intente más tarde.",
            "categoria": "intentos",
            "severidad": "alta"
        },
        "cc_rejected_other_reason": {
            "message": "Tarjeta rechazada",
            "user_message": "❌ Tarjeta rechazada. Contacte a su banco.",
            "categoria": "general",
            "severidad": "alta"
        },
        
        # ======================
        # ERRORES DE VALIDACIÓN
        # ======================
        "invalid_payment_method": {
            "message": "Método de pago inválido",
            "user_message": "❌ Método de pago inválido.",
            "categoria": "validacion",
            "severidad": "media"
        },
        "invalid_token": {
            "message": "Token inválido",
            "user_message": "❌ Token de pago inválido o expirado.",
            "categoria": "token",
            "severidad": "alta"
        },
        "invalid_user": {
            "message": "Usuario inválido",
            "user_message": "❌ Información del pagador inválida.",
            "categoria": "validacion",
            "severidad": "media"
        },
        "invalid_installments": {
            "message": "Cuotas inválidas",
            "user_message": "❌ Número de cuotas no válido para esta tarjeta.",
            "categoria": "validacion",
            "severidad": "media"
        },
        
        # ======================
        # ERRORES DE PROCESAMIENTO
        # ======================
        "pending_contingency": {
            "message": "Pago pendiente",
            "user_message": "⏳ El pago está pendiente de confirmación.",
            "categoria": "pendiente",
            "severidad": "baja"
        },
        "pending_review_manual": {
            "message": "Pendiente de revisión manual",
            "user_message": "⏳ El pago está siendo revisado manualmente.",
            "categoria": "pendiente",
            "severidad": "baja"
        },
        "pending_waiting_payment": {
            "message": "Esperando pago",
            "user_message": "⏳ Esperando confirmación del pago.",
            "categoria": "pendiente",
            "severidad": "baja"
        },
        
        # ======================
        # ERRORES DE AUTENTICACIÓN
        # ======================
        "authentication_error": {
            "message": "Error de autenticación",
            "user_message": "🔐 Error de autenticación con Mercado Pago.",
            "categoria": "auth",
            "severidad": "alta"
        },
        "invalid_access_token": {
            "message": "Token de acceso inválido",
            "user_message": "🔐 Credenciales de Mercado Pago inválidas.",
            "categoria": "auth",
            "severidad": "alta"
        },
        
        # ======================
        # DEFAULT
        # ======================
        "default": {
            "message": "Error al procesar el pago",
            "user_message": "❌ Error al procesar el pago. Intente nuevamente.",
            "categoria": "general",
            "severidad": "alta"
        }
    }

    def __init__(self, base_url: str = "https://payhotspot.wispremote.com"):
    #def __init__(self, base_url: str = "https://4d686998b1a3.ngrok-free.app"):
        self.base_url = base_url
    
    def _generate_external_reference(self, empresa_id: str, product_id: int = None) -> str:
        """Generar external_reference única para conciliación"""
        timestamp = int(datetime.now().timestamp())
        unique_id = uuid.uuid4().hex[:6].upper()
        
        if product_id:
            return f"HS{empresa_id[:2]}{product_id:03d}{timestamp}{unique_id}"
        else:
            return f"HS{empresa_id[:2]}{timestamp}{unique_id}"
    
    def _build_payer_info(self, payment_data: Dict[str, Any]) -> Dict[str, Any]:
        """Construir información completa del pagador - REQUISITO DE APROBACIÓN"""
        payer = {
            "email": payment_data.get("customer_email", "")  # 🔴 OBLIGATORIO
        }
        
        # 🟡 NOMBRE Y APELLIDO - Mejora tasa de aprobación
        customer_name = payment_data.get("customer_name", "").strip()
        if customer_name:
            name_parts = customer_name.split(" ", 1)
            payer["first_name"] = name_parts[0]
            if len(name_parts) > 1:
                payer["last_name"] = name_parts[1]
        
        # 🟡 TELÉFONO - Mejora tasa de aprobación
        if payment_data.get("customer_phone"):
            payer["phone"] = {
                "area_code": "",
                "number": self._normalize_phone(payment_data["customer_phone"])
            }
        
        # 🟢 IDENTIFICACIÓN (opcional pero recomendado)
        # payer["identification"] = {
        #     "type": "RFC",
        #     "number": "XAXX010101000"
        # }
        
        # 🟢 DIRECCIÓN (opcional pero recomendado)
        # payer["address"] = {
        #     "street_name": "Calle Ficticia",
        #     "street_number": "123",
        #     "zip_code": "12345"
        # }
        
        return payer
    
    def _build_items_info(self, metadata: Optional[Dict[str, Any]] = None, transaction_amount: float = 0) -> List[Dict[str, Any]]:
        """Construir información de items - REQUISITO DE APROBACIÓN"""
        items = []
        
        if metadata:
            items = [{
                "id": str(metadata.get("producto_id", "1")),  # 🔴 RECOMENDADO
                "title": metadata.get("product_name", "Acceso Hotspot WiFi"),  # 🔴 RECOMENDADO
                "description": f"Acceso WiFi - {metadata.get('product_name', 'Servicio')}",  # 🔴 RECOMENDADO
                "category_id": "services",  # 🔴 RECOMENDADO (services, electronics, etc.)
                "quantity": 1,  # 🔴 RECOMENDADO
                "unit_price": float(transaction_amount),  # 🔴 RECOMENDADO
                # 🟢 CURRENCY_ID no se envía aquí, se infiere automáticamente
            }]
        
        return items
    
# app/services/mercado_pago_service.py - CORREGIR EL PAYLOAD

    async def create_payment(
        self,
        access_token: str,
        mode: str,
        payment_data: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Crear pago en Mercado Pago - CORREGIDO"""
        
        print("\n" + "="*60)
        print("🔍 [MERCADO PAGO] CREANDO PAGO CORREGIDO")
        print("="*60)
        
        try:
            sdk = mercadopago.SDK(access_token)
            
            # GENERAR EXTERNAL REFERENCE
            empresa_id = metadata.get("empresa_id", "00") if metadata else "00"
            producto_id = metadata.get("producto_id") if metadata else None
            external_reference = self._generate_external_reference(empresa_id, producto_id)
            
            print(f"📌 External Reference generada: {external_reference}")
            
            # CONSTRUIR PAYLOAD CORREGIDO
            transaction_amount = float(payment_data["transaction_amount"])
            
            mp_payload = {
                # 🔴 DATOS BÁSICOS OBLIGATORIOS
                "transaction_amount": transaction_amount,
                "token": payment_data["token"],
                "description": f"Acceso Hotspot - {metadata.get('product_name', 'WiFi')}" if metadata else "Acceso Hotspot WiFi",
                "payment_method_id": payment_data["payment_method_id"],
                "installments": payment_data.get("installments", 1),
                
                # 🔴 REQUISITOS OBLIGATORIOS
                "external_reference": external_reference,
                "notification_url": urljoin(self.base_url, "/api/v1/webhook/mercado-pago"),
                
                # 🟡 MEJORAS
                "statement_descriptor": "HOTSPOT WIFI",
                "binary_mode": True,
                
                # 🟢 INFORMACIÓN DEL PAGADOR (nivel principal)
                "payer": self._build_payer_info(payment_data),
                
                # 📊 METADATOS
                "metadata": metadata or {},
                
                # 🛒 INFORMACIÓN DE ITEMS (SOLO items e ip_address)
                "additional_info": {
                    "items": self._build_items_info(metadata, transaction_amount),
                    "ip_address": metadata.get("ip_cliente", "") if metadata else ""
                    # ❌ ELIMINAR: "payer" aquí
                }
            }
            
            # Agregar issuer_id si existe (excepto en test)
            if payment_data.get("issuer_id") and mode != 'test':
                mp_payload["issuer_id"] = payment_data["issuer_id"]
            
            print(f"\n📦 PAYLOAD CORREGIDO:")
            print(f"   • External Reference: {external_reference}")
            print(f"   • Notification URL: {mp_payload['notification_url']}")
            print(f"   • Payer: {mp_payload['payer'].get('email')}")
            print(f"   • Items: {len(mp_payload['additional_info']['items'])} item(s)")
            
            # Mostrar payload completo para debug
            print(f"\n🔍 PAYLOAD COMPLETO (sensible):")
            payload_debug = mp_payload.copy()
            if "token" in payload_debug:
                payload_debug["token"] = f"{payload_debug['token'][:10]}..."
            print(json.dumps(payload_debug, indent=2))
            
            # CONFIGURAR HEADERS
            request_options = mercadopago.config.RequestOptions()
            request_options.custom_headers = {
                "x-idempotency-key": str(uuid.uuid4())
            }
            
            # CREAR PAGO
            print(f"\n📤 Enviando a Mercado Pago API...")
            payment_response = sdk.payment().create(mp_payload, request_options)
            
            print(f"📥 Respuesta recibida")
            
            # MANEJAR RESPUESTA
            if "response" not in payment_response:
                error_msg = "Respuesta inválida de Mercado Pago"
                if isinstance(payment_response, dict):
                    if "message" in payment_response:
                        error_msg = payment_response["message"]
                    elif "error" in payment_response:
                        error_msg = payment_response["error"]
                
                print(f"❌ {error_msg}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Error de Mercado Pago: {error_msg}"
                )
            
            payment = payment_response["response"]
            
            # Verificar si es un error 400
            if isinstance(payment, dict) and payment.get("status") == 400:
                error_msg = payment.get("message", "Error de validación")
                print(f"❌ Error 400: {error_msg}")
                
                if "cause" in payment:
                    print(f"   • Causas:")
                    for cause in payment["cause"]:
                        print(f"     - {cause.get('description')}")
                
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Error de validación: {error_msg}"
                )
            
            # Agregar external_reference a la respuesta
            payment["external_reference"] = external_reference
            
            print(f"\n✅ PAGO PROCESADO CORRECTAMENTE:")
            print(f"   • Payment ID: {payment.get('id')}")
            print(f"   • Status: {payment.get('status')}")
            
            # MANEJAR ESTADO DEL PAGO
            status_value = payment.get("status", "").lower()
            
            if status_value == "approved":
                print(f"🎉🎉🎉 PAGO APROBADO 🎉🎉🎉")
                response = self._build_success_response(payment)
                response["external_reference"] = external_reference
                response["notification_url_configured"] = True
                return response
            
            elif status_value == "pending":
                print(f"⏳⏳⏳ PAGO PENDIENTE ⏳⏳⏳")
                response = self._build_pending_response(payment)
                response["external_reference"] = external_reference
                response["notification_url_configured"] = True
                response["warning"] = "Pago pendiente de confirmación"
                return response
            
            elif status_value in ["rejected", "cancelled"]:
                print(f"❌❌❌ PAGO RECHAZADO: {status_value}")
                error_info = self._parse_mp_error(payment.get("status_detail", ""))
                print(f"   • Razón: {error_info['user_message']}")
                
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail=error_info["user_message"]
                )
            
            else:
                print(f"⚠️  Estado no manejado: {status_value}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Estado de pago no manejado: {status_value}"
                )
                
        except HTTPException:
            raise
        except Exception as e:
            print(f"\n💥 ERROR INESPERADO: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error interno al procesar el pago"
            )
        

    def _parse_mp_error(self, status_detail: str) -> Dict[str, str]:
        """Parsear código de error de Mercado Pago"""
        
        print(f"🔍 Parseando error de Mercado Pago: '{status_detail}'")
        
        if not status_detail:
            print(f"   ⚠️  Status detail vacío, usando error por defecto")
            default = self.MP_ERRORS["default"]
            return {
                "code": "unknown",
                "message": default["message"],
                "user_message": default["user_message"],
                "categoria": default.get("categoria", "general"),
                "severidad": default.get("severidad", "alta")
            }
        
        status_detail_lower = status_detail.lower()
        
        # Buscar coincidencia exacta
        if status_detail in self.MP_ERRORS:
            error_info = self.MP_ERRORS[status_detail]
            print(f"   ✅ Error encontrado en diccionario: {status_detail}")
            return {
                "code": status_detail,
                "message": error_info["message"],
                "user_message": error_info["user_message"],
                "categoria": error_info.get("categoria", "general"),
                "severidad": error_info.get("severidad", "alta")
            }
        
        # Buscar coincidencia parcial
        for error_code, error_info in self.MP_ERRORS.items():
            if error_code in status_detail_lower or status_detail_lower in error_code:
                print(f"   🔍 Coincidencia parcial: {error_code}")
                return {
                    "code": error_code,
                    "message": error_info["message"],
                    "user_message": error_info["user_message"],
                    "categoria": error_info.get("categoria", "general"),
                    "severidad": error_info.get("severidad", "alta")
                }
        
        # Error por defecto
        print(f"   ⚠️  Error no encontrado en diccionario, usando default")
        default = self.MP_ERRORS["default"]
        return {
            "code": status_detail,
            "message": default["message"],
            "user_message": default["user_message"],
            "categoria": default.get("categoria", "general"),
            "severidad": default.get("severidad", "alta")
        }
    
    def _build_success_response(self, payment: Dict) -> Dict[str, Any]:
        """Construir respuesta para pago exitoso"""
        return {
            "payment_id": payment["id"],
            "status": payment["status"],
            "status_detail": payment.get("status_detail", ""),
            "amount": payment.get("transaction_amount", 0),
            "currency": payment.get("currency_id", "MXN"),  # MP devuelve currency_id
            "date_approved": payment.get("date_approved"),
            "payer": payment.get("payer", {}),
            "payment_method": {
                "id": payment.get("payment_method_id"),
                "type": payment.get("payment_type_id"),
                "issuer": payment.get("issuer_id"),
                "last_four_digits": payment.get("card", {}).get("last_four_digits"),
                "installments": payment.get("installments")
            },
            "additional_info": payment.get("additional_info", {}),
            "external_reference": payment.get("external_reference", ""),
            "notification_url_configured": True,
            "statement_descriptor": payment.get("statement_descriptor", "HOTSPOT WIFI"),
            "binary_mode": True,
            "raw_response": payment
        }
    
    def _build_pending_response(self, payment: Dict) -> Dict[str, Any]:
        """Construir respuesta para pago pendiente"""
        return {
            "payment_id": payment["id"],
            "status": payment["status"],
            "status_detail": payment.get("status_detail", ""),
            "amount": payment.get("transaction_amount", 0),
            "currency": payment.get("currency_id", "MXN"),
            "date_created": payment.get("date_created"),
            "payer": payment.get("payer", {}),
            "payment_method": {
                "id": payment.get("payment_method_id"),
                "type": payment.get("payment_type_id")
            },
            "external_reference": payment.get("external_reference", ""),
            "notification_url_configured": True,
            "statement_descriptor": payment.get("statement_descriptor", "HOTSPOT WIFI"),
            "binary_mode": True
        }
    
    def _normalize_phone(self, phone: str) -> str:
        """Normalizar número de teléfono para Mercado Pago"""
        if not phone:
            return ""
            
        digits = ''.join(filter(str.isdigit, phone))
        
        if len(digits) == 12 and digits.startswith('52'):
            return digits[2:]  # Quitar +52
        elif len(digits) == 10:
            return digits
        else:
            return digits if digits else ""
    
    async def get_payment_status(self, access_token: str, payment_id: int) -> Dict[str, Any]:
        """Obtener estado de un pago existente"""
        
        print(f"\n🔍 CONSULTANDO ESTADO DE PAGO: {payment_id}")
        
        try:
            sdk = mercadopago.SDK(access_token)
            response = sdk.payment().get(payment_id)
            
            if "response" not in response:
                print(f"❌ Respuesta inválida para pago {payment_id}")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Pago no encontrado"
                )
            
            payment = response["response"]
            
            print(f"📊 Estado actual del pago {payment_id}:")
            print(f"   • Status: {payment.get('status')}")
            print(f"   • Status Detail: {payment.get('status_detail')}")
            print(f"   • External Ref: {payment.get('external_reference')}")
            
            return {
                "payment_id": payment["id"],
                "status": payment["status"],
                "status_detail": payment.get("status_detail", ""),
                "amount": payment.get("transaction_amount", 0),
                "currency": payment.get("currency_id", "MXN"),
                "date_approved": payment.get("date_approved"),
                "date_last_updated": payment.get("date_last_updated"),
                "external_reference": payment.get("external_reference", ""),
                "raw_response": payment
            }
            
        except Exception as e:
            print(f"❌ Error consultando estado del pago {payment_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error al consultar estado del pago: {str(e)}"
            )
    
    async def verify_webhook_signature(self, request_data: Dict, signature: str) -> bool:
        """Verificar firma del webhook (para producción)"""
        # Implementación básica - en producción usarías la clave pública de MP
        return True

# Instancia global
#mercado_pago_service = MercadoPagoService(base_url="https://4d686998b1a3.ngrok-free.app")
mercado_pago_service = MercadoPagoService(base_url="https://payhotspot.wispremote.com")