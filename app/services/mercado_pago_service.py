# app/services/mercado_pago_service.py
import mercadopago
import aiohttp
import asyncio
import json
import logging
from typing import Dict, Any, Optional
from fastapi import HTTPException, status
from uuid import uuid4



logger = logging.getLogger(__name__)

class MercadoPagoService:
    """Servicio para procesar pagos con Mercado Pago - CON LOGS DETALLADOS"""
    
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

    async def create_payment(
        self,
        access_token: str,
        mode: str,
        payment_data: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Crear pago en Mercado Pago - CON LOGS DETALLADOS"""
        
        print("\n" + "="*60)
        print("🔍 [MERCADO PAGO] INICIANDO PROCESO DE PAGO")
        print("="*60)
        
        try:
            # 1. CONFIGURAR SDK
            print(f"🔧 Configurando SDK Mercado Pago...")
            print(f"   • Modo: {mode}")
            print(f"   • Token length: {len(access_token)} caracteres")
            
            sdk = mercadopago.SDK(access_token)
            
            # 2. CONSTRUIR PAYLOAD
            print(f"📦 Construyendo payload del pago...")
            
            mp_payload = {
                "token": payment_data["token"],
                "issuer_id": None if mode == 'test' else payment_data.get("issuer_id"),  # ← Cambio: Fuerza None en test para evitar mismatch de issuer/BIN
                "payment_method_id": payment_data["payment_method_id"],
                "transaction_amount": float(payment_data["transaction_amount"]),
                "installments": payment_data.get("installments", 1),                
                "payer": payment_data.get("payer", {
                    "email": payment_data["customer_email"]
                }),
                "description": f"Acceso Hotspot - {metadata.get('product_name', 'Servicio WiFi')}" if metadata else "Acceso Hotspot WiFi",
                "metadata": metadata or {},
                "notification_url": None,
                "additional_info": {
                    "ip_address": metadata.get("ip_cliente", "") if metadata else "",
                    "items": metadata.get("items", []) if metadata else []
                }
            }
            
            print(f"💰 Payload completo: {json.dumps(mp_payload, indent=2)}")  # ← Cambio: Log completo del payload para depuración
            
            # 3. CONFIGURAR OPTIONS
            request_options = mercadopago.config.RequestOptions()
            request_options.custom_headers = {
                "x-idempotency-key": str(uuid4())
            }
            print(f"🔑 Idempotency Key: {request_options.custom_headers['x-idempotency-key']}")
            
            # 4. CREAR PAGO
            print(f"📤 Enviando pago a Mercado Pago API...")
            print(f"   • URL: https://api.mercadopago.com/v1/payments")
            
            payment_response = sdk.payment().create(mp_payload, request_options)
            
            print(f"✅ Respuesta recibida de Mercado Pago")
            
            # 5. ANALIZAR RESPUESTA
            print(f"📊 Analizando respuesta...")
            
            if "response" not in payment_response:
                print(f"❌ Respuesta inválida de Mercado Pago")
                print(f"   • Contenido completo: {json.dumps(payment_response, indent=2)}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Respuesta inválida de Mercado Pago"
                )
            
            payment = payment_response["response"]
            
            print(f"📄 RESPUESTA COMPLETA DE MERCADO PAGO:")
            print(f"   • ID: {payment.get('id')}")
            print(f"   • Status: {payment.get('status')}")
            print(f"   • Status Detail: {payment.get('status_detail')}")
            print(f"   • Status Code: {payment.get('status_code')}")
            print(f"   • Description: {payment.get('description')}")
            print(f"   • Message: {payment.get('message')}")
            print(f"   • Amount: ${payment.get('transaction_amount')}")
            print(f"   • Currency: {payment.get('currency_id')}")
            print(f"   • Date Created: {payment.get('date_created')}")
            print(f"   • Date Approved: {payment.get('date_approved')}")
            
            # 6. MANEJAR ERRORES DETALLADOS
            if "cause" in payment:
                print(f"🔍 CÓDIGOS DE ERROR DETALLADOS:")
                for cause in payment["cause"]:
                    print(f"   • Código: {cause.get('code')} - {cause.get('description')}")
            
            # 7. MANEJAR ESTADO
            status_value = payment.get("status", "")
            status_detail = payment.get("status_detail", "")
            
            print(f"🎯 MANEJANDO ESTADO: {status_value} ({status_detail})")
            
            # ESTADO APROBADO
            if status_value == "approved":
                print(f"✅✅✅ PAGO APROBADO")
                return self._build_success_response(payment)
            
            # ESTADO PENDIENTE
            elif status_value == "pending":
                print(f"⏳⏳⏳ PAGO PENDIENTE")
                pending_response = self._build_pending_response(payment)
                pending_response["warning"] = "Pago pendiente de confirmación"
                return pending_response
            
            # ESTADO RECHAZADO
            elif status_value in ["rejected", "cancelled", "refunded", "charged_back"]:
                print(f"❌❌❌ PAGO RECHAZADO")
                error_info = self._parse_mp_error(status_detail)
                print(f"   • Código error: {error_info['code']}")
                print(f"   • Mensaje: {error_info['message']}")
                print(f"   • Categoría: {error_info['categoria']}")
                
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail=error_info["user_message"]
                )
            
            # ESTADO EN PROCESO
            elif status_value in ["in_process", "in_mediation"]:
                print(f"🔄🔄🔄 PAGO EN PROCESO")
                return self._build_pending_response(payment)
            
            # ESTADO DESCONOCIDO
            else:
                print(f"❓❓❓ ESTADO DESCONOCIDO: {status_value}")
                print(f"   • Status Detail: {status_detail}")
                print(f"   • Respuesta completa: {json.dumps(payment, indent=2, default=str)}")
                
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Estado de pago desconocido: {status_value}"
                )
                
        except HTTPException:
            print(f"🔼 Re-lanzando HTTPException")
            raise
            
        except Exception as e:
            print(f"\n💥💥💥 ERROR INESPERADO EN MERCADO PAGO")
            print(f"   • Tipo: {type(e).__name__}")
            print(f"   • Mensaje: {str(e)}")
            print(f"   • Traceback:")
            import traceback
            traceback.print_exc()
            
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error interno al procesar el pago. Intente nuevamente."
            )
        finally:
            print("\n" + "="*60)
            print("📝 FIN DEL PROCESO MERCADO PAGO")
            print("="*60 + "\n")
    
    def _parse_mp_error(self, status_detail: str) -> Dict[str, str]:
        """Parsear código de error de Mercado Pago con logs detallados"""
        
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
            "currency_id": payment.get("currency_id", "MXN"),
            "date_approved": payment.get("date_approved"),
            "payer": payment.get("payer", {}),
            "payment_method": {
                "id": payment.get("payment_method_id"),
                "type": payment.get("payment_type_id"),
                "issuer": payment.get("issuer_id"),
                "last_four_digits": payment.get("card", {}).get("last_four_digits"),
                "installments": payment.get("installments")
            },
            "additional_info": {
                "ip_address": payment.get("additional_info", {}).get("ip_address"),
                "items": payment.get("additional_info", {}).get("items", [])
            },
            "raw_response": payment  # Incluir respuesta completa para debugging
        }
    
    def _build_pending_response(self, payment: Dict) -> Dict[str, Any]:
        """Construir respuesta para pago pendiente"""
        return {
            "payment_id": payment["id"],
            "status": payment["status"],
            "status_detail": payment.get("status_detail", ""),
            "amount": payment.get("transaction_amount", 0),
            "currency_id": payment.get("currency_id", "MXN"),
            "date_created": payment.get("date_created"),
            "payer": payment.get("payer", {}),
            "payment_method": {
                "id": payment.get("payment_method_id"),
                "type": payment.get("payment_type_id")
            }
        }
    
    async def get_payment_status(self, access_token: str, payment_id: int) -> Dict[str, Any]:
        """Obtener estado de un pago existente con logs detallados"""
        
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
            print(f"   • Amount: ${payment.get('transaction_amount')}")
            print(f"   • Date Last Updated: {payment.get('date_last_updated')}")
            
            return {
                "payment_id": payment["id"],
                "status": payment["status"],
                "status_detail": payment.get("status_detail", ""),
                "amount": payment.get("transaction_amount", 0),
                "currency_id": payment.get("currency_id", "MXN"),
                "date_approved": payment.get("date_approved"),
                "date_last_updated": payment.get("date_last_updated"),
                "raw_response": payment  # Incluir respuesta completa
            }
            
        except Exception as e:
            print(f"❌ Error consultando estado del pago {payment_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error al consultar estado del pago: {str(e)}"
            )
    
    def _normalize_phone(self, phone: str) -> str:
        """Normalizar número de teléfono para Mercado Pago"""
        if not phone:
            return ""
            
        digits = ''.join(filter(str.isdigit, phone))
        
        if len(digits) == 12 and digits.startswith('52'):
            return f"+{digits}"
        elif len(digits) == 10:
            return f"+52{digits}"
        else:
            return f"+{digits}" if digits else ""

# Instancia global
mercado_pago_service = MercadoPagoService()