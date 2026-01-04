# app/api/v1/mercado_pago.py
from typing import Dict, Any, Tuple
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
import asyncio

from app.core.database import get_db
from app.core.auth import require_api_key
from app.services.mercado_pago_service import mercado_pago_service
from app.services.mikrotik_service import mikrotik_service
from app.schemas.request.mercado_pago import MercadoPagoPaymentRequest
from app.models.producto import Producto
from app.models.transaccion import Transaccion

import json

router = APIRouter(tags=["Pagar Hotspot - Mercado Pago"])

# Reutilizar las funciones auxiliares del endpoint de Conekta
from app.api.v1.payments import (
    rollback_usuario,
    ejecutar_auto_conexion,
    validar_estado_pago_conekta,
    construir_respuesta_auto_conexion,
    construir_respuesta_exitosa,
    manejar_error_inesperado
)

def validar_estado_mercado_pago(payment_result: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Validar estado de pago de Mercado Pago
    
    Args:
        payment_result: Resultado de la API de Mercado Pago
        
    Returns:
        tuple: (es_valido: bool, mensaje_error: str)
    """
    status = payment_result.get("status", "").lower()
    
    # Estados válidos
    if status == "approved":
        return True, ""
    
    # Estados pendientes (aceptamos pero el usuario debe saber)
    if status == "pending":
        return False, "Pago pendiente de confirmación."
    
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
        
        payment_result = await mercado_pago_service.create_payment(
            access_token=empresa.mercado_pago_access_token,
            mode=empresa.mercado_pago_mode or 'test',
            payment_data={
                "token": payment_data.token,
                "issuer_id": payment_data.issuer_id,
                "payment_method_id": payment_data.payment_method_id,
                "transaction_amount": payment_data.transaction_amount,
                "installments": payment_data.installments,
                "customer_email": payment_data.customer_email,
                "payer": payment_data.payer or {"email": payment_data.customer_email}
            },
            metadata={
                "empresa_id": empresa.id,
                "router_id": router.id,
                "producto_id": producto.id,
                "product_name": producto.nombre_venta,
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
        
        # Validar estado del pago
        es_valido, mensaje_error = validar_estado_mercado_pago(payment_result)
        
        # Ejecutar auto-conexión si aplica (incluso si pendiente)
        auto_conexion_resultado = None
        if auto_connect_requested and payment_data.mac_address:
            try:
                print(f"\n🔗 EJECUTANDO AUTO-CONEXIÓN...")
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
            except Exception as auto_connect_error:
                print(f"⚠️  ERROR EN AUTO-CONEXIÓN: {str(auto_connect_error)}")
                auto_conexion_resultado = {
                    "success": False,
                    "conectado": False,
                    "error": str(auto_connect_error)
                }
        
        auto_conexion_info = construir_respuesta_auto_conexion(
            auto_connect_requested=auto_connect_requested,
            mac_address=payment_data.mac_address,
            ip_address=payment_data.ip_address,
            auto_conexion_resultado=auto_conexion_resultado
        )
        
        # Guardar transacción en BD (siempre)
        print(f"\n💾 GUARDANDO TRANSACCIÓN EN BD...")
        
        transaccion = Transaccion(
            transaccion_id=str(payment_result["payment_id"]),
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
            metadata={
                "gateway": "mercado_pago",
                "payment_method": payment_result.get("payment_method", {}),
                "status_detail": payment_result.get("status_detail"),
                "installments": payment_data.installments,
                "payer_email": payment_result.get("payer", {}).get("email"),
                "raw_response": payment_result.get("raw_response", {})
            },
            estado_pago=payment_result["status"],
            estado_hotspot="active",
            api_key_usada=auth_info.get("api_key_id", ""),
            pagada_en=datetime.utcnow(),
            usuario_creado_en=datetime.utcnow()
        )
        db.add(transaccion)
        await db.commit()
        
        print(f"✅✅✅ TRANSACCIÓN GUARDADA: {transaccion.transaccion_id}")
        print(f"   • Tipo usuario: {user_type}")
        print(f"   • Estado pago: {transaccion.estado_pago}")
        
        # Construir respuesta (estructura siempre igual)
        response_data = {
            "success": es_valido,
            "id_transaccion": transaccion.transaccion_id,
            "estado_pago": payment_result["status"],
            "tipo_usuario": user_type,
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
                "ticket_url": payment_result.get("transaction_details", {}).get("external_resource_url") 
                              if payment_result.get("status") == "pending" else None,
                "raw_response": payment_result.get("raw_response", {})
            },
            "timestamp": datetime.utcnow().isoformat(),
            "auto_conexion": auto_conexion_info
        }
        
        # CREDENCIALES: siempre presente, pero vacío si no aprobado
        if es_valido:
            response_data["usuario_hotspot"] = {
                "usuario": credentials["username"],
                "contrasena": credentials["password"]
            }
        else:
            response_data["usuario_hotspot"] = {
                "usuario": "",
                "contrasena": ""
            }
            response_data["warning"] = mensaje_error
            
            # Rollback solo si rechazado
            if payment_result["status"] in ["rejected", "cancelled"]:
                print(f"🔄 ROLLBACK: Pago rechazado → eliminando usuario")
                await rollback_usuario(router, credentials["username"], user_type)
        
        print(f"\n📤 ENVIANDO RESPUESTA AL CLIENTE")
        print(f"   • Success: {response_data['success']}")
        print(f"   • Estado: {response_data['estado_pago']}")
        print(f"   • Usuario hotspot: {'***' if es_valido else '(vacío)'}")
        
        print("\n" + "="*70)
        print("🎉 PROCESO COMPLETADO")
        print("="*70 + "\n")
        
        return response_data
        
    # 🔴 **MANEJO DE ERRORES HTTP (de mercado_pago_service u otros)**
    except HTTPException as http_exc:
        print(f"\n❌❌❌ ERROR HTTP {http_exc.status_code}")
        print(f"   • Detalle: {http_exc.detail}")
        print(f"   • Usuario creado: {usuario_creado}")
        
        # Rollback si es error de pago (402) y el usuario fue creado
        if usuario_creado and http_exc.status_code == 402:
            print(f"🔄 EJECUTANDO ROLLBACK POR PAGO RECHAZADO...")
            await rollback_usuario(router, credentials["username"], user_type)
        
        await db.rollback()
        raise http_exc
        
    # 🔴 **MANEJO DE ERRORES INESPERADOS**
    except Exception as e:
        print(f"\n💥💥💥 ERROR INESPERADO")
        print(f"   • Tipo: {type(e).__name__}")
        print(f"   • Mensaje: {str(e)}")
        print(f"   • Usuario creado: {usuario_creado}")
        
        error_exception = manejar_error_inesperado(
            error=e,
            usuario_creado=usuario_creado,
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
        payment_status = await mercado_pago_service.get_payment_status(
            access_token=empresa.mercado_pago_access_token,
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