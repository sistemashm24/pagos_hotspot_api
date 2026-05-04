# app/api/v1/mercado_pago.py
from typing import Dict, Any, Literal, Optional, Tuple
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
import asyncio

from app.core.database import get_db
from app.core.auth import require_api_key, require_cliente_admin
from app.core.secure_token import SecureTokenManager
from app.models.empresa import Empresa
from app.models.usuario import Usuario
from app.services.mercado_pago_service import mercado_pago_service
from app.services.mikrotik_service import mikrotik_service
from app.services.telegram_service import telegram_service
from app.schemas.request.mercado_pago import MercadoPagoPaymentRequest
from app.models.producto import Producto
from app.models.transaccion import Transaccion
from fastapi import logger


import json

router = APIRouter(tags=["Pagar Hotspot - Mercado Pago"])

# Reutilizar las funciones auxiliares del endpoint de Conekta
from app.api.v1.payments import (
    rollback_usuario,    
    validar_estado_pago_conekta,  # Puedes crear una específica para MP si necesitas
    construir_respuesta_auto_conexion,
    construir_respuesta_exitosa,
    manejar_error_inesperado
)

from app.hotspot.auto_conexion_pago_tarjeta import ejecutar_auto_conexion

def validar_estado_mercado_pago(payment_result: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Validar estado de pago de Mercado Pago
    
    Args:
        payment_result: Resultado de la API de Mercado Pago
        
    Returns:
        tuple: (es_valido: bool, mensaje_error: str)
    """
    status_raw = payment_result.get("status", "")
    status = str(status_raw).lower() if status_raw else ""
    
    # Estados válidos
    if status == "approved":
        return True, ""
    
    # Estados pendientes (aceptamos pero el usuario debe saber)
    if status == "pending":
        return True, "Pago pendiente de confirmación."
    
    # Mapeo de estados inválidos
    status_messages = {
        "rejected": "El pago fue rechazado.",
        "cancelled": "El pago fue cancelado.",
        "refunded": "El pago fue reembolsado.",
        "charged_back": "Disputa activa en el pago.",
        "in_mediation": "El pago está en mediación.",
        "in_process": "El pago está siendo procesado.",
    }
    
    mensaje = status_messages.get(status, "El pago no fue aprobado.")
    return False, mensaje

# app/api/v1/mercado_pago.py - Agregar logs detallados en el endpoint

@router.post("/pagar-mercado-pago",
    summary="Procesar pago para acceso Hotspot MikroTik con Mercado Pago",
    description="""## 📋 Descripción
    
    Procesa pagos mediante Mercado Pago para crear usuarios en Hotspot MikroTik.
    
    ## 🔐 Autenticación
    - Requiere API Key en header: `X-API-Key: jwt_eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...`
    
    ## 📥 Parámetros del Request
    """
)
async def pagar_hotspot_mercado_pago(
    payment_data: MercadoPagoPaymentRequest,
    background_tasks: BackgroundTasks,
    auth_data = Depends(require_api_key),
    db: AsyncSession = Depends(get_db)
):
    """
    Procesar pago para acceso Hotspot MikroTik con Mercado Pago
    
    Flujo:
    1. Validar producto y empresa
    2. Generar credenciales según tipo de usuario
    3. Crear usuario en MikroTik (CRÍTICO - si falla, no hay pago)
    4. Procesar pago con Mercado Pago
    5. Validar estado del pago
    6. Guardar transacción en BD
    7. Ejecutar auto-conexión si se solicitó
    8. Retornar credenciales al cliente
    """
    
    print("\n" + "="*70)
    print("🚀 INICIANDO PROCESO DE PAGO MERCADO PAGO")
    print("="*70)
    
    empresa, router, auth_info = auth_data
    
    print(f"🏢 Empresa: {empresa.nombre} ({empresa.id})")
    print(f"🌐 Router: {router.host}:{router.puerto}")
    print(f"👤 Cliente: {payment_data.customer_name}")
    print(f"📧 Email: {payment_data.customer_email}")
    
    # 1. Validar que la empresa tiene configurado Mercado Pago
    if not empresa.mercado_pago_access_token:
        print(f"❌ EMPRESA SIN CONFIGURACIÓN MERCADO PAGO")
        raise HTTPException(
            status_code=400,
            detail="La empresa no tiene configurado Mercado Pago"
        )
    
    print(f"✅ Empresa tiene configurado Mercado Pago")
    print(f"   • Modo: {empresa.mercado_pago_mode or 'test'}")
    print(f"   • Token: {'*' * 20}{empresa.mercado_pago_access_token[-10:] if empresa.mercado_pago_access_token else 'N/A'}")
    
    # 2. Obtener producto
    result = await db.execute(
        select(Producto).where(Producto.id == payment_data.product_id)
    )
    producto = result.scalar_one_or_none()
    
    if not producto or producto.empresa_id != empresa.id:
        print(f"❌ PRODUCTO NO ENCONTRADO")
        print(f"   • ID buscado: {payment_data.product_id}")
        print(f"   • Empresa ID: {empresa.id}")
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    
    print(f"✅ Producto encontrado:")
    print(f"   • Nombre: {producto.nombre_venta}")
    print(f"   • Precio: ${producto.precio} {producto.moneda}")
    print(f"   • Perfil MikroTik: {producto.perfil_mikrotik_nombre}")
    
    # 3. Validar que el monto coincida con el producto (con tolerancia)
    if abs(payment_data.transaction_amount - float(producto.precio)) > 0.01:
        print(f"❌ ERROR DE MONTO NO COINCIDENTE")
        print(f"   • Monto recibido: ${payment_data.transaction_amount:.2f}")
        print(f"   • Precio producto: ${producto.precio:.2f}")
        print(f"   • Diferencia: ${abs(payment_data.transaction_amount - float(producto.precio)):.2f}")
        raise HTTPException(
            status_code=400,
            detail=f"El monto (${payment_data.transaction_amount:.2f}) no coincide con el producto (${producto.precio:.2f})"
        )
    
    print(f"✅ Monto validado correctamente: ${payment_data.transaction_amount}")
    
    # 4. Normalizar tipo de usuario
    user_type = payment_data.user_type or "usuario_contrasena"
    if user_type not in ["usuario_contrasena", "pin"]:
        user_type = "usuario_contrasena"
    
    print(f"🔧 Tipo de usuario: {user_type}")
    
    # 5. Validar parámetros para auto-conexión
    auto_connect_requested = payment_data.auto_connect
    
    print(f"🔗 Conexión automática: {'Activada' if auto_connect_requested else 'Desactivada'}")
    if auto_connect_requested:
        print(f"   • MAC Cliente: {payment_data.mac_address or 'No proporcionada'}")
        print(f"   • IP Cliente: {payment_data.ip_address or 'No proporcionada'}")
    
    # 6. Generar credenciales según tipo de usuario
    credentials = mikrotik_service.generate_credentials(user_type=user_type)
    usuario_creado = False
    
    print(f"🔐 Credenciales generadas:")
    print(f"   • Usuario: {credentials['username']}")
    print(f"   • Contraseña: {credentials['password']}")
    
    try:
        # 🔴 **PASO CRÍTICO 1: CREAR USUARIO EN MIKROTIK**
        print(f"\n🔴 CREANDO USUARIO EN MIKROTIK...")
        
        await mikrotik_service.create_hotspot_user(
            router_host=router.host,
            router_port=router.puerto,
            router_user=router.usuario,
            router_password=router.password_encrypted,
            username=credentials["username"],
            password=credentials["password"],
            profile_name=producto.perfil_mikrotik_nombre,
            user_type=user_type
        )
        
        usuario_creado = True
        print(f"✅✅✅ USUARIO CREADO EN MIKROTIK")
        
        # 🟢 **PASO CRÍTICO 2: PROCESAR PAGO EN MERCADO PAGO**
        print(f"\n🟢 PROCESANDO PAGO CON MERCADO PAGO...")
        
        # Log del payload recibido del frontend para depuración (Cambio nuevo)
        print(f"📥 Payload recibido del frontend: {json.dumps(payment_data.dict(), indent=2)}")

        #antes de encritpar
        """ payment_result = await mercado_pago_service.create_payment( 
            access_token=empresa.mercado_pago_access_token, 
            mode=empresa.mercado_pago_mode or 'test', 
            payment_data={ """

        # 🔐 Desencriptar siempre el token (si no está encriptado, lo usa directo)
        token_manager = SecureTokenManager()
        access_token = token_manager.decrypt_if_needed(
            empresa.mercado_pago_access_token
        )

        payment_result = await mercado_pago_service.create_payment(
            access_token=access_token,  # 👈 YA DESENCRIPTADO
            mode=empresa.mercado_pago_mode or 'test',
            payment_data={
                "token": payment_data.token,
                "issuer_id": payment_data.issuer_id,
                "payment_method_id": payment_data.payment_method_id,
                "transaction_amount": payment_data.transaction_amount,
                "installments": payment_data.installments,
                "customer_email": payment_data.customer_email,
                "customer_name": payment_data.customer_name,
                "customer_phone": payment_data.customer_phone,
                "device_id": payment_data.device_id,
                "payer": payment_data.payer or {"email": payment_data.customer_email}
            },

            metadata={
                "empresa_id": empresa.id,
                "router_id": router.id,
                "producto_id": producto.id,
                "product_name": producto.nombre_venta,
                "transaction_amount": payment_data.transaction_amount,  # AGREGADO para items
                "auto_connect_requested": auto_connect_requested,
                "mac_cliente": payment_data.mac_address,
                "ip_cliente": payment_data.ip_address,
                "user_type": user_type,
                "router_host": router.host,
                "perfil_mikrotik": producto.perfil_mikrotik_nombre
            }
        )

        
        print(f"✅✅✅ PAGO PROCESADO")
        print(f"   • Status: {payment_result['status']}")
        print(f"   • ID: {payment_result['payment_id']}")
        
        # Validar estado (usando tu función)
        es_valido, mensaje_error = validar_estado_mercado_pago(payment_result)
        
        if not es_valido:
            print(f"❌ PAGO INVÁLIDO: {mensaje_error}")
            raise HTTPException(status_code=402, detail=mensaje_error)
        
        print(f"✅✅✅ PAGO VALIDADO Y APROBADO")
        
        # 📢 Notificar Pago Aprobado (Telegram)
        if empresa.notificaciones_telegram:
            # Construir info de credenciales según tipo
            cred_info = f"🔑 <b>PIN:</b> <code>{credentials['password']}</code>" if user_type == "pin" else \
                        f"👤 <b>Usuario:</b> <code>{credentials['username']}</code>\n🔑 <b>Contraseña:</b> <code>{credentials['password']}</code>"

            msg_exito = (
                f"✅ <b>¡Pago Aprobado!</b>\n"
                f"🏢 <b>Empresa:</b> {empresa.nombre}\n"
                f"📦 <b>Plan:</b> {producto.nombre_venta}\n"
                f"💰 <b>Monto:</b> ${producto.precio} {producto.moneda}\n"
                f"👤 <b>Cliente:</b> {payment_data.customer_name}\n"
                f"🆔 <b>Transacción:</b> <code>{payment_result['payment_id']}</code>\n"
                f"{cred_info}\n"
                f"🔥 <i>Acceso WiFi entregado correctamente.</i>"
            )
            background_tasks.add_task(
                telegram_service.send_message,
                empresa.telegram_bot_token,
                empresa.telegram_chat_id,
                msg_exito
            )
        
        # 7. Guardar transacción
        print(f"\n💾 GUARDANDO TRANSACCIÓN EN BD...")
        
        transaccion = Transaccion(
            transaccion_id=str(payment_result["payment_id"]),
            external_reference=payment_result["external_reference"],  # ✅ YA LO TIENES
            empresa_id=empresa.id,
            router_id=router.id,
            producto_id=producto.id,
            monto=producto.precio,
            moneda=producto.moneda,
            cliente_nombre=payment_data.customer_name,
            cliente_email=payment_data.customer_email,
            cliente_telefono=payment_data.customer_phone,
            usuario_hotspot=credentials["username"],
            password_hotspot=credentials["password"],
            metadata_json={  # ✅ USAR metadata_json (no metadata)
                "gateway": "mercado_pago",
                "external_reference": payment_result["external_reference"],
                "notification_url_configured": True,
                "statement_descriptor": payment_result.get("statement_descriptor", "HOTSPOT WIFI"),
                "binary_mode": True,
                "payment_method": payment_result.get("payment_method", {}),
                "status_detail": payment_result.get("status_detail"),
                "installments": payment_data.installments,
                "payer_email": payment_result.get("payer", {}).get("email"),
                "items_info": payment_result.get("additional_info", {}).get("items", []),
                "webhook_expected": True
            },
            estado_pago=payment_result["status"],
            estado_hotspot="active",
            api_key_usada=auth_info.get("api_key_id", ""),
            pagada_en=datetime.utcnow(),
            usuario_creado_en=datetime.utcnow()
        )

        ########

        db.add(transaccion)
        await db.commit()
        
        print(f"✅✅✅ TRANSACCIÓN GUARDADA: {transaccion.transaccion_id}")
        print(f"   • Tipo usuario: {user_type}")
        print(f"   • Estado pago: {transaccion.estado_pago}")
        
        # 🔄 **EJECUTAR AUTO-CONEXIÓN SI SE SOLICITÓ**
        auto_conexion_resultado = None
        if auto_connect_requested and payment_data.mac_address:
            try:
                print(f"\n🔗 EJECUTANDO AUTO-CONEXIÓN...")
                print(f"   • MAC: {payment_data.mac_address}")
                print(f"   • IP: {payment_data.ip_address or 'No especificada'}")
                print(f"   • Usuario: {credentials['username']}")
                
                auto_conexion_resultado = await ejecutar_auto_conexion(
                    router_host=router.host,
                    router_port=router.puerto,
                    router_user=router.usuario,
                    router_password=router.password_encrypted,
                    username=credentials["username"],
                    password=credentials["password"],
                    mac_address=payment_data.mac_address,
                    ip_address=payment_data.ip_address
                )
                
                if auto_conexion_resultado and auto_conexion_resultado.get("conectado"):
                    print(f"✅✅✅ AUTO-CONEXIÓN VERIFICADA")
                    print(f"   • Session ID: {auto_conexion_resultado.get('session_id')}")
                    print(f"   • IP asignada: {auto_conexion_resultado.get('ip')}")
                elif auto_conexion_resultado and auto_conexion_resultado.get("success"):
                    print(f"⚠️  AUTO-LOGIN EJECUTADO PERO NO VERIFICADO")
                else:
                    print(f"⚠️  AUTO-CONEXIÓN FALLÓ PARCIALMENTE")
                    print(f"   • Error: {auto_conexion_resultado.get('error')}")
                    
            except Exception as auto_connect_error:
                print(f"⚠️  ERROR EN AUTO-CONEXIÓN:")
                print(f"   • Tipo: {type(auto_connect_error).__name__}")
                print(f"   • Mensaje: {str(auto_connect_error)}")
                auto_conexion_resultado = {
                    "success": False,
                    "conectado": False,
                    "error": str(auto_connect_error)
                }
        
        # 8. Construir info de auto-conexión
        auto_conexion_info = construir_respuesta_auto_conexion(
            auto_connect_requested=auto_connect_requested,
            mac_address=payment_data.mac_address,
            ip_address=payment_data.ip_address,
            auto_conexion_resultado=auto_conexion_resultado
        )
        
        # 9. Construir y retornar respuesta
        response_data = {
            "success": True,
            "id_transaccion": transaccion.transaccion_id,
            "estado_pago": payment_result["status"],
            "tipo_usuario": user_type,
            "usuario_hotspot": {
                "usuario": credentials["username"],
                "contrasena": credentials["password"]
            },
            "producto": {
                "nombre": producto.nombre_venta,
                "precio": float(producto.precio),
                "moneda": producto.moneda,
                "perfil_mikrotik": producto.perfil_mikrotik_nombre
            },
            "cliente": {
                "nombre": payment_data.customer_name,
                "email": payment_data.customer_email
            },
            "mercado_pago": {
                "payment_id": payment_result["payment_id"],
                "status": payment_result["status"],
                "status_detail": payment_result.get("status_detail"),
                "installments": payment_data.installments,
                "payment_method": payment_result.get("payment_method", {}),
                "raw_response": payment_result.get("raw_response", {})  # Para debugging
            },
            "timestamp": datetime.utcnow().isoformat(),
            "auto_conexion": auto_conexion_info
        }
        
        # Si el pago está pendiente, agregar advertencia
        if payment_result["status"] == "pending" and "warning" in payment_result:
            response_data["advertencia"] = payment_result["warning"]
        
        print(f"\n📤 ENVIANDO RESPUESTA AL CLIENTE")
        print(f"   • ID Transacción: {response_data['id_transaccion']}")
        print(f"   • Estado: {response_data['estado_pago']}")
        print(f"   • Usuario: {response_data['usuario_hotspot']['usuario']}")
        
        print("\n" + "="*70)
        print("🎉 PROCESO COMPLETADO EXITOSAMENTE")
        print("="*70 + "\n")
        
        return response_data
        
    # 🔴 **MANEJO DE ERRORES HTTP (de mercado_pago_service u otros)**
    except HTTPException as http_exc:
        print(f"\n❌❌❌ ERROR HTTP {http_exc.status_code}")
        print(f"   • Detalle: {http_exc.detail}")
        print(f"   • Usuario creado: {usuario_creado}")
        
        # Rollback si hay error (400+) y el usuario fue creado
        if usuario_creado:
            print(f"🔄 EJECUTANDO ROLLBACK POR ERROR EN PAGO ({http_exc.status_code})...")
            await rollback_usuario(router, credentials["username"], user_type)
        
        # 📢 Notificar Pago Rechazado (Telegram)
        if empresa.notificaciones_telegram and http_exc.status_code == 402:
            msg_rechazo = (
                f"❌ <b>Pago Rechazado</b>\n"
                f"🏢 <b>Empresa:</b> {empresa.nombre}\n"
                f"📦 <b>Plan:</b> {producto.nombre_venta}\n"
                f"💰 <b>Monto:</b> ${producto.precio} {producto.moneda}\n"
                f"👤 <b>Cliente:</b> {payment_data.customer_name}\n"
                f"⚠️ <b>Motivo:</b> {http_exc.detail}"
            )
            background_tasks.add_task(
                telegram_service.send_message,
                empresa.telegram_bot_token,
                empresa.telegram_chat_id,
                msg_rechazo
            )
        
        await db.rollback()
        raise http_exc
        
        # 🔥 FIX ROLLBACK: Await rollback instead of background task
        if usuario_creado:
            await rollback_usuario(router, credentials["username"], user_type)
            
        await db.rollback()

        error_exception = manejar_error_inesperado(
            error=e,
            usuario_creado=False, # Ponemos False para que manejar_error_inesperado no intente otro rollback
            router=router,
            credentials=credentials,
            db=db,
            user_type=user_type
        )
        raise error_exception
   
    
@router.get("/estado-pago/{payment_id}",
    summary="Consultar estado de un pago de Mercado Pago",
    description="Consulta el estado actual de un pago procesado con Mercado Pago"
)
async def consultar_estado_pago(
    payment_id: int,
    auth_data = Depends(require_api_key),
    db: AsyncSession = Depends(get_db)
):
    """
    Consultar estado de un pago de Mercado Pago
    """
    empresa, _, _ = auth_data
    
    # Validar que la empresa tiene configurado Mercado Pago
    if not empresa.mercado_pago_access_token:
        raise HTTPException(
            status_code=400,
            detail="La empresa no tiene configurado Mercado Pago"
        )
    
    try:
        # Consultar estado en Mercado Pago
        """ payment_status = await mercado_pago_service.get_payment_status(
            access_token=empresa.mercado_pago_access_token,
            payment_id=payment_id
        ) """
        
        # ¡Aquí está el fix!
        token_manager = SecureTokenManager()
        access_token = token_manager.decrypt_if_needed(empresa.mercado_pago_access_token)
        
        print(f"🔑 Access Token usado en consulta (primeros 10 chars): {access_token[:10]}...")  # para debug
        
        payment_status = await mercado_pago_service.get_payment_status(
            access_token=access_token,  # ← ahora desencriptado
            payment_id=payment_id
        )
        
        return {
            "success": True,
            "payment_id": payment_id,
            "status": payment_status["status"],
            "status_detail": payment_status.get("status_detail", ""),
            "amount": payment_status["amount"],
            "currency_id": payment_status["currency_id"],
            "date_approved": payment_status.get("date_approved"),
            "date_last_updated": payment_status.get("date_last_updated"),
        }
        
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error al consultar estado del pago: {str(e)}"
        )
    


class MercadoPagoCredentials(BaseModel):
    access_token: Optional[str] = Field(
        None,
        json_schema_extra={"description": "Access token de Mercado Pago (test o producción)"}
    )
    webhook_secret: Optional[str] = Field(
        None,
        json_schema_extra={"description": "Clave secreta para validar webhooks"}
    )
    public_key: Optional[str] = Field(
        None,
        json_schema_extra={"description": "Public key de Mercado Pago (para frontend)"}
    )
    mode: Optional[Literal["test", "live"]] = Field(
        "test",
        json_schema_extra={"description": "Modo de operación"}
    )
    # Telegram fields
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    notificaciones_telegram: Optional[bool] = None


@router.post("/configurar-credenciales",
    summary="Configurar o actualizar credenciales de Mercado Pago",
    description="Crea o actualiza las credenciales de Mercado Pago para la empresa del usuario autenticado. "
                "Campos no enviados se mantienen intactos. Enviar '' o null para borrar un campo sensible.",
    tags=["Configuración Mercado Pago"]
)
async def configurar_credenciales_mercado_pago(
    datos: MercadoPagoCredentials,
    usuario: Usuario = Depends(require_cliente_admin),
    db: AsyncSession = Depends(get_db)
):
    if not usuario.empresa_id:
        raise HTTPException(400, "Usuario sin empresa asociada")

    result = await db.execute(select(Empresa).where(Empresa.id == usuario.empresa_id))
    empresa = result.scalar_one_or_none()

    if not empresa:
        raise HTTPException(404, "Empresa no encontrada")

    if not empresa.activa:
        raise HTTPException(400, "Empresa inactiva")

    token_manager = SecureTokenManager()
    updated_fields = []

    # Access Token: encriptar si viene valor, borrar si viene vacío
    if datos.access_token is not None:
        if datos.access_token.strip():
            empresa.mercado_pago_access_token = token_manager.encrypt(datos.access_token.strip())
            updated_fields.append("access_token (actualizado)")
        else:
            empresa.mercado_pago_access_token = None
            updated_fields.append("access_token (eliminado)")

    # Webhook Secret: igual lógica
    if datos.webhook_secret is not None:
        if datos.webhook_secret.strip():
            empresa.mercado_pago_webhook_secret = token_manager.encrypt(datos.webhook_secret.strip())
            updated_fields.append("webhook_secret (actualizado)")
        else:
            empresa.mercado_pago_webhook_secret = None
            updated_fields.append("webhook_secret (eliminado)")

    # Public Key y Mode: no sensibles, se actualizan directamente
    if datos.public_key is not None:
        empresa.mercado_pago_public_key = datos.public_key.strip() or None
        updated_fields.append("public_key")

    if datos.mode is not None:
        empresa.mercado_pago_mode = datos.mode
        updated_fields.append("mode")

    # Telegram Config
    if datos.telegram_bot_token is not None:
        empresa.telegram_bot_token = datos.telegram_bot_token.strip() or None
        updated_fields.append("telegram_bot_token")
    
    if datos.telegram_chat_id is not None:
        empresa.telegram_chat_id = datos.telegram_chat_id.strip() or None
        updated_fields.append("telegram_chat_id")
        
    if datos.notificaciones_telegram is not None:
        empresa.notificaciones_telegram = datos.notificaciones_telegram
        updated_fields.append("notificaciones_telegram")

    # Si no hay cambios → informar
    if not updated_fields:
        return {
            "success": True,
            "message": "No se enviaron cambios. Credenciales actuales se mantienen.",
            "empresa": {"id": empresa.id, "nombre": empresa.nombre},
            "configurado": {
                "access_token": bool(empresa.mercado_pago_access_token),
                "webhook_secret": bool(empresa.mercado_pago_webhook_secret),
                "public_key": bool(empresa.mercado_pago_public_key),
                "mode": empresa.mercado_pago_mode,
                "telegram_configurado": bool(empresa.telegram_bot_token and empresa.telegram_chat_id),
                "telegram_activo": empresa.notificaciones_telegram
            }
        }

    await db.commit()


    return {
        "success": True,
        "message": "Credenciales actualizadas correctamente",
        "empresa": {"id": empresa.id, "nombre": empresa.nombre},
        "campos_modificados": updated_fields,
        "configuracion_actual": {
            "access_token": bool(empresa.mercado_pago_access_token),
            "webhook_secret": bool(empresa.mercado_pago_webhook_secret),
            "public_key": bool(empresa.mercado_pago_public_key),
            "mode": empresa.mercado_pago_mode,
            "telegram_configurado": bool(empresa.telegram_bot_token and empresa.telegram_chat_id),
            "telegram_activo": empresa.notificaciones_telegram
        }
    }