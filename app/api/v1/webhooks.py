# app/api/v1/webhooks.py
from fastapi import APIRouter, Request, HTTPException, Depends, BackgroundTasks, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import json
import hashlib
import logging
import hmac
from datetime import datetime
from typing import Optional, Dict, Any

from app.core.database import get_db
from app.models.transaccion import Transaccion
from app.models.empresa import Empresa

from app.services.mercado_pago_service import mercado_pago_service
from app.core.secure_token import SecureTokenManager


router = APIRouter(tags=["Webhooks"])
logger = logging.getLogger(__name__)


def verify_webhook_signature(
    signature_header: Optional[str],
    request_id_header: Optional[str],
    data_id: Optional[str],
    secret_key: str
) -> bool:
    """
    Verificar la firma del webhook de Mercado Pago (formato oficial actual)
    Manifest: id:{data_id};request-id:{request_id};ts:{timestamp};
    """
    if not signature_header or not request_id_header or not data_id or not secret_key:
        logger.warning("Faltan datos requeridos para verificar la firma del webhook")
        return False
    
    try:
        logger.info(f"🔐 VERIFICACIÓN DE FIRMA (FORMATO OFICIAL MERCADO PAGO)")
        
        # Parsear X-Signature de forma más robusta: ts=xxx,v1=yyy
        parts = [p.strip() for p in signature_header.split(',')]
        timestamp = None
        received_hash = None
        
        for part in parts:
            if part.startswith("ts="):
                timestamp = part[3:]
            elif part.startswith("v1="):
                received_hash = part[3:]
        
        if not timestamp or not received_hash:
            logger.error(f"Formato X-Signature inválido o incompleto: {signature_header}")
            return False
        
        # Construir el manifest correcto (exacto según docs MP 2025+)
        message = f"id:{data_id};request-id:{request_id_header};ts:{timestamp};"
        
        # Calcular HMAC-SHA256
        expected_hash = hmac.new(
            secret_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        # Logs para debug mejorados
        logger.info(f"   • Timestamp: {timestamp}")
        logger.info(f"   • Data ID: {data_id}")
        logger.info(f"   • Request-ID: {request_id_header}")
        logger.info(f"   • Manifest completo: '{message}'")
        logger.info(f"   • Hash esperado (primeros 10 chars): {expected_hash[:10]}...")
        logger.info(f"   • Hash recibido (primeros 10 chars): {received_hash[:10]}...")
        logger.info(f"   • Coinciden: {hmac.compare_digest(expected_hash, received_hash)}")
        
        return hmac.compare_digest(expected_hash, received_hash)
        
    except Exception as e:
        logger.error(f"💥 Error verificando firma: {str(e)}", exc_info=True)
        return False
     

async def find_transaction_by_external_ref(db: AsyncSession, external_reference: str) -> Optional[Transaccion]:
    """Buscar transacción por external_reference"""
    try:
        result = await db.execute(
            select(Transaccion).where(Transaccion.external_reference == external_reference)
        )
        return result.scalar_one_or_none()
    except Exception as e:
        logger.error(f"Error buscando transacción por external_ref {external_reference}: {str(e)}")
        return None


async def find_transaction_by_payment_id(db: AsyncSession, payment_id: str) -> Optional[Transaccion]:
    """Buscar transacción por payment_id (transaccion_id)"""
    try:
        result = await db.execute(
            select(Transaccion).where(Transaccion.transaccion_id == payment_id)
        )
        return result.scalar_one_or_none()
    except Exception as e:
        logger.error(f"Error buscando transacción por payment_id {payment_id}: {str(e)}")
        return None


async def update_transaction_from_webhook(
    db: AsyncSession,
    transaction: Transaccion,
    payment_data: Dict[str, Any],
    notification_id: str
) -> Dict[str, Any]:
    """Actualizar transacción con datos del webhook"""
    try:
        old_status = transaction.estado_pago
        new_status = payment_data.get("status", "unknown")
        
        # Actualizar campos básicos
        transaction.estado_pago = new_status
        transaction.notification_id = notification_id
        transaction.webhook_processed = True
        transaction.webhook_received_at = datetime.utcnow()
        
        # ============================================
        # FIX: Usar metadata_json en lugar de metadata
        # ============================================
        # Inicializar metadata_json si es None
        if transaction.metadata_json is None:
            transaction.metadata_json = {}
        
        # Asegurar que metadata_json sea dict
        if not isinstance(transaction.metadata_json, dict):
            transaction.metadata_json = {}
        
        # Inicializar webhooks si no existe
        if "webhooks" not in transaction.metadata_json:
            transaction.metadata_json["webhooks"] = []
        
        # Agregar nuevo webhook
        transaction.metadata_json["webhooks"].append({
            "notification_id": notification_id,
            "received_at": datetime.utcnow().isoformat(),
            "old_status": old_status,
            "new_status": new_status,
            "status_detail": payment_data.get("status_detail"),
            "date_last_updated": payment_data.get("date_last_updated")
        })
        
        # Si se aprueba el pago y aún no tiene fecha de pago
        if new_status == "approved" and not transaction.pagada_en:
            transaction.pagada_en = datetime.utcnow()
        
        await db.commit()
        
        logger.info(f"✅ Transacción {transaction.transaccion_id} actualizada: {old_status} -> {new_status}")
        
        return {
            "success": True,
            "transaction_id": transaction.transaccion_id,
            "external_reference": transaction.external_reference,
            "old_status": old_status,
            "new_status": new_status,
            "notification_id": notification_id
        }
        
    except Exception as e:
        logger.error(f"❌ Error actualizando transacción {transaction.transaccion_id}: {str(e)}", exc_info=True)
        await db.rollback()
        return {"success": False, "error": str(e)}

async def process_mercado_pago_notification(
    payment_data: Dict[str, Any],
    notification_id: str,
    db: AsyncSession
) -> Dict[str, Any]:
    logger.info(f"Procesando notificación MP: {notification_id}")
    
    # 1. Extraer el payment_id correctamente (el formato más común en 2025+)
    payment_id = None
    
    # Caso moderno: "data": {"id": "..."}
    if isinstance(payment_data.get("data"), dict):
        payment_id = str(payment_data["data"].get("id"))
    
    # Fallback viejo o query params
    if not payment_id:
        payment_id = str(payment_data.get("id", ""))
    
    if not payment_id:
        logger.error("Webhook sin payment_id válido")
        return {"success": False, "error": "No payment_id found"}
    
    logger.info(f"Payment ID extraído: {payment_id}")
    
    # 2. Extraer external_reference si existe
    external_reference = payment_data.get("external_reference") or payment_data.get("data", {}).get("external_reference")
    
    # 3. Buscar transacción priorizando external_reference
    transaction = None
    if external_reference:
        transaction = await find_transaction_by_external_ref(db, external_reference)
    
    if not transaction and payment_id:
        transaction = await find_transaction_by_payment_id(db, payment_id)
    
    if not transaction:
        logger.warning(f"No se encontró transacción para payment_id={payment_id} o external_ref={external_reference}")
        return {"success": False, "error": "Transaction not found"}
    
    # 4. Verificar si ya fue procesado este notification_id (idempotencia)
    if transaction.metadata_json is None:
        transaction.metadata_json = {}
    
    processed_notifications = transaction.metadata_json.get("processed_notifications", [])
    if notification_id in processed_notifications:
        logger.info(f"Webhook duplicado ignorado: {notification_id} (ya procesado)")
        return {"success": True, "message": "Duplicate notification ignored"}
    
    # 5. Obtener empresa → access_token
    result = await db.execute(select(Empresa).where(Empresa.id == transaction.empresa_id))
    empresa = result.scalar_one_or_none()
    
    if not empresa or not empresa.mercado_pago_access_token:
        logger.error(f"Empresa {transaction.empresa_id} sin access_token")
        return {"success": False, "error": "Missing credentials"}
    
    # 6. CONSULTAR ESTADO REAL
    try:
        """ payment_status = await mercado_pago_service.get_payment_status(
            access_token=empresa.mercado_pago_access_token,
            payment_id=int(payment_id)  # Asegúr que sea int si el SDK lo requiere
        ) """
        
        # Desencriptar el access_token (igual que en la creación de pago)
        token_manager = SecureTokenManager()
        access_token = token_manager.decrypt_if_needed(empresa.mercado_pago_access_token)

        # Debug para confirmar que ahora es el token real
        logger.info(f"🔑 Access Token usado en webhook (primeros 10 chars): {access_token[:10]}...")

        payment_status = await mercado_pago_service.get_payment_status(
            access_token=access_token,           # ← AHORA sí desencriptado
            payment_id=int(payment_id)
        )


        real_status = payment_status.get("status", "unknown")
        status_detail = payment_status.get("status_detail", "")
        
        logger.info(f"Estado consultado → {real_status} ({status_detail})")
        
        # 7. Actualizar transacción
        old_status = transaction.estado_pago
        transaction.estado_pago = real_status
        
        if real_status == "approved" and not transaction.pagada_en:
            transaction.pagada_en = datetime.utcnow()
        
        # Mejorar metadata_json con info del webhook + consulta
        if not isinstance(transaction.metadata_json, dict):
            transaction.metadata_json = {}
        
        transaction.metadata_json.update({
            "last_webhook": {
                "notification_id": notification_id,
                "received_at": datetime.utcnow().isoformat(),
                "action": payment_data.get("action"),
                "queried_status": real_status,
                "status_detail": status_detail
            }
        })
        
        transaction.webhook_processed = True
        transaction.webhook_received_at = datetime.utcnow()
        transaction.notification_id = notification_id
        
        # Registrar notification_id como procesado
        processed_notifications.append(notification_id)
        transaction.metadata_json["processed_notifications"] = processed_notifications[-20:]  # Limitar a últimos 20
        
        await db.commit()
        
        logger.info(f"Transacción {transaction.transaccion_id} actualizada: {old_status} → {real_status}")
        
        return {
            "success": True,
            "new_status": real_status,
            "detail": status_detail
        }
    
    except Exception as e:
        logger.error(f"Error al consultar/actualizar: {str(e)}", exc_info=True)
        await db.rollback()
        return {"success": False, "error": str(e)}
    

@router.post("/mercado-pago")
async def mercado_pago_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
    x_request_id: Optional[str] = Header(None, alias="X-Request-Id"),  # NUEVO: Requerido para firma correcta
    db: AsyncSession = Depends(get_db)
):
    """
    WEBHOOK PRINCIPAL PARA MERCADO PAGO - MULTI-TENANT
    
    URL FIJA PARA TODAS LAS EMPRESAS:
    https://payhotspot.wispremote.com/api/v1/webhook/mercado-pago
    """
    try:
        # ======================
        # 1. Responder 200 rápido (obligatorio para MP, antes de cualquier procesamiento)
        # ======================
        # Nota: Esto evita reintentos innecesarios de MP
        response_base = {
            "status": "received",
            "message": "Webhook received and queued",
            "received_at": datetime.utcnow().isoformat()
        }

        # ======================
        # 2. LEER DATOS DEL WEBHOOK
        # ======================
        payload_body = await request.body()
        payload_text = payload_body.decode('utf-8')
        
        logger.info(f"📦 Raw webhook recibido (primeros 500 chars): {payload_text[:500]}")
        
        # ======================
        # 3. PARSEAR JSON
        # ======================
        try:
            webhook_data = json.loads(payload_text)
        except json.JSONDecodeError as e:
            logger.error(f"❌ JSON inválido: {str(e)}")
            return response_base  # Igual 200 para no reintentar
        
        # ======================
        # 4. EXTRAER DATOS CLAVE
        # ======================
        webhook_type = webhook_data.get("type", "unknown")
        notification_id = str(webhook_data.get("id", "unknown"))  # Usamos str para evitar errores
        action = webhook_data.get("action", "unknown")
        
        # Extraer data_id (para firma)
        data_id = webhook_data.get("data", {}).get("id") or webhook_data.get("id")
        
        # Extraer payment_id
        payment_id = data_id  # Normalmente coincide
        
        # External reference
        external_reference = webhook_data.get("external_reference") or webhook_data.get("data", {}).get("external_reference")
        
        # ======================
        # 5. Buscar transacción rápido (sin firma aún)
        # ======================
        transaction = None
        if external_reference:
            transaction = await find_transaction_by_external_ref(db, external_reference)
        
        if not transaction and payment_id:
            transaction = await find_transaction_by_payment_id(db, payment_id)
        
        if not transaction:
            logger.warning(f"⚠️ Transacción no encontrada para notification_id={notification_id}")
            return response_base  # 200 para no reintentar
        
        # ======================
        # 6. OBTENER EMPRESA
        # ======================
        result = await db.execute(
            select(Empresa).where(Empresa.id == transaction.empresa_id)
        )
        empresa = result.scalar_one_or_none()
        
        if not empresa:
            logger.error(f"❌ Empresa NO encontrada: {transaction.empresa_id}")
            return response_base
        
        logger.info(f"✅ Empresa identificada: {empresa.nombre} ({empresa.id})")
        
        # ======================
        # 7. VERIFICAR FIRMA (antes de encolar, pero rápido)
        # ======================
        signature_verified = False
        
        if empresa.mercado_pago_webhook_secret:
            if not x_signature:
                logger.warning(f"⚠️ Empresa {empresa.id} tiene clave pero NO trae header X-Signature")
            elif not x_request_id:
                logger.warning(f"⚠️ Falta header X-Request-Id (requerido para verificar firma)")
            elif not data_id:
                logger.warning(f"⚠️ No se encontró data.id para verificar la firma")
            else:
                #antes de ecnriptar
                """ signature_verified = verify_webhook_signature(
                    signature_header=x_signature,
                    request_id_header=x_request_id,
                    data_id=data_id,
                    secret_key=empresa.mercado_pago_webhook_secret
                ) """
                # 🔐 Desencriptar siempre el webhook_secret
                token_manager = SecureTokenManager()
                webhook_secret = token_manager.decrypt_if_needed(
                    empresa.mercado_pago_webhook_secret
                )

                signature_verified = verify_webhook_signature(
                    signature_header=x_signature,
                    request_id_header=x_request_id,
                    data_id=data_id,
                    secret_key=webhook_secret  
                )


                if signature_verified:
                    logger.info("✅ Firma verificada correctamente con formato oficial")
                else:
                    logger.warning(f"⚠️ FIRMA INVÁLIDA para empresa {empresa.id}")
                    logger.warning(f"   X-Signature: {x_signature[:20]}...")
                    logger.warning(f"   X-Request-Id: {x_request_id}")
                    logger.warning(f"   Data ID: {data_id}")
                    # Opcional: Si quieres rechazar firmas inválidas, raise HTTPException(403) aquí
                    # Por ahora, procesamos pero logueamos
        
        else:
            logger.warning(f"⚠️ Empresa {empresa.id} NO tiene clave secreta configurada")
            logger.warning("   Procesando sin verificación (NO recomendado en producción)")
        
        # ======================
        # 8. PROCESAR SEGÚN TIPO (encolar si es payment)
        # ======================
        if webhook_type == "payment":
            if not payment_id and not external_reference:
                logger.error("❌ Webhook payment sin payment_id ni external_reference")
                return response_base
            
            background_tasks.add_task(
                process_mercado_pago_notification,
                payment_data=webhook_data,  # Pasamos todo el dict
                notification_id=notification_id,
                db=db
            )
            
            logger.info(f"📝 Webhook encolado para procesamiento en background")
            logger.info(f"   Empresa: {empresa.nombre}")
            logger.info(f"   Transacción: {transaction.transaccion_id}")
            
            response_base.update({
                "notification_id": notification_id,
                "type": webhook_type,
                "empresa": {
                    "id": empresa.id,
                    "nombre": empresa.nombre
                },
                "transaction": {
                    "id": transaction.id,
                    "transaccion_id": transaction.transaccion_id,
                    "external_reference": transaction.external_reference
                },
                "signature_verified": signature_verified,
                "data_id": data_id
            })
            return response_base
        
        elif webhook_type == "test":
            logger.info("🧪 Webhook de prueba procesado correctamente")
            response_base.update({
                "message": "Test webhook received successfully",
                "notification_id": notification_id,
                "empresa": empresa.nombre if empresa else None,
                "signature_verified": signature_verified
            })
            return response_base
        
        else:
            logger.info(f"📄 Webhook de tipo '{webhook_type}' recibido (solo logged)")
            response_base.update({
                "message": f"Webhook type '{webhook_type}' received",
                "notification_id": notification_id,
                "empresa": empresa.nombre if empresa else None,
                "signature_verified": signature_verified
            })
            return response_base
            
    except Exception as e:
        logger.error(f"💥 ERROR NO CONTROLADO en webhook: {str(e)}", exc_info=True)
        return response_base  # Siempre 200, pero logueamos error

@router.post("/empresa/{empresa_id}/configurar-webhook")
async def configurar_webhook_empresa(
    empresa_id: str,
    config: Dict[str, Any],
    db: AsyncSession = Depends(get_db)
):
    """Configurar clave secreta del webhook para una empresa"""
    try:
        result = await db.execute(
            select(Empresa).where(Empresa.id == empresa_id)
        )
        empresa = result.scalar_one_or_none()
        
        if not empresa:
            raise HTTPException(status_code=404, detail="Empresa no encontrada")
        
        webhook_secret = config.get("webhook_secret")
        if not webhook_secret:
            raise HTTPException(status_code=400, detail="webhook_secret es requerido")
        
        empresa.mercado_pago_webhook_secret = webhook_secret
        await db.commit()
        
        logger.info(f"✅ Webhook configurado para empresa: {empresa.nombre}")
        
        return {
            "success": True,
            "message": "Clave secreta configurada correctamente",
            "empresa": {
                "id": empresa.id,
                "nombre": empresa.nombre
            },
            "webhook_url": "https://4d686998b1a3.ngrok-free.app/api/v1/webhook/mercado-pago",
            "instrucciones": [
                "1. Ir al panel de Mercado Pago",
                "2. Configurar Webhooks",
                "3. URL: https://4d686998b1a3.ngrok-free.app/api/v1/webhook/mercado-pago",
                f"4. Usar esta misma clave secreta: {webhook_secret[:10]}...",
                "5. Suscribir eventos: 'payment'"
            ]
        }
        
    except Exception as e:
        logger.error(f"Error configurando webhook: {str(e)}")
        raise HTTPException(status_code=500, detail="Error configuring webhook")


@router.get("/empresa/{empresa_id}/estado-webhook")
async def obtener_estado_webhook(
    empresa_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Obtener estado de configuración de webhook para una empresa"""
    try:
        result = await db.execute(
            select(Empresa).where(Empresa.id == empresa_id)
        )
        empresa = result.scalar_one_or_none()
        
        if not empresa:
            raise HTTPException(status_code=404, detail="Empresa no encontrada")
        
        from sqlalchemy import func
        result = await db.execute(
            select(func.count(Transaccion.id))
            .where(Transaccion.empresa_id == empresa_id)
        )
        total_transacciones = result.scalar() or 0
        
        return {
            "empresa": {
                "id": empresa.id,
                "nombre": empresa.nombre,
                "modo_mercado_pago": empresa.mercado_pago_mode,
                "access_token_configurado": bool(empresa.mercado_pago_access_token),
                "webhook_secret_configurado": bool(empresa.mercado_pago_webhook_secret)
            },
            "estadisticas": {
                "total_transacciones": total_transacciones
            },
            "configuracion_webhook": {
                "url": "https://4d686998b1a3.ngrok-free.app/api/v1/webhook/mercado-pago",
                "metodo": "POST",
                "header_firma": "X-Signature",
                "tipo_contenido": "application/json"
            },
            "estado": "configurado" if empresa.mercado_pago_webhook_secret else "pendiente",
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error obteniendo estado: {str(e)}")
        raise HTTPException(status_code=500, detail="Error getting webhook status")


@router.get("/test-webhook")
async def test_webhook_endpoint():
    """Endpoint de prueba para verificar que el webhook está activo"""
    return {
        "status": "active",
        "service": "Mercado Pago Webhook",
        "endpoint": "/api/v1/webhook/mercado-pago",
        "method": "POST",
        "description": "Recibe notificaciones de pagos de Mercado Pago (Multi-tenant)",
        "url_produccion": "https://payhotspot.wispremote.com/api/v1/webhook/mercado-pago",
        "url_pruebas": "https://4d686998b1a3.ngrok-free.app/api/v1/webhook/mercado-pago",
        "health_check": "ok",
        "timestamp": datetime.utcnow().isoformat()
    }

@router.get("/transaccion/{external_reference}")
async def obtener_transaccion_por_external_reference(
    external_reference: str,
    db: AsyncSession = Depends(get_db)
):
    """Obtener información de transacción por external_reference"""
    transaction = await find_transaction_by_external_ref(db, external_reference)
    
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    empresa = None
    if transaction.empresa_id:
        result = await db.execute(
            select(Empresa).where(Empresa.id == transaction.empresa_id)
        )
        empresa = result.scalar_one_or_none()
    
    return {
        "transaction": {
            "id": transaction.id,
            "transaccion_id": transaction.transaccion_id,
            "external_reference": transaction.external_reference,
            "empresa_id": transaction.empresa_id,
            "estado_pago": transaction.estado_pago,
            "monto": float(transaction.monto) if transaction.monto else None,
            "usuario_hotspot": transaction.usuario_hotspot,
            "creada_en": transaction.creada_en.isoformat() if transaction.creada_en else None,
            "pagada_en": transaction.pagada_en.isoformat() if transaction.pagada_en else None,
            "webhook_processed": transaction.webhook_processed,
            "notification_id": transaction.notification_id,
            "metadata_json": transaction.metadata_json  # ← CAMBIADO A metadata_json
        },
        "empresa": {
            "id": empresa.id if empresa else None,
            "nombre": empresa.nombre if empresa else None,
            "tiene_webhook_secret": bool(empresa.mercado_pago_webhook_secret) if empresa else False
        } if empresa else None
    }