SISTEMA DE VENTA DE FICHAS POR HOTSPOT - GESTIÓN DE WIFI PAGADO
================================================================================

DESCRIPCIÓN:
Sistema completo para venta de fichas de internet por tiempo en redes WiFi Hotspot 
MikroTik. Integración completa con procesamiento de pagos por tarjeta mediante Conekta.

CARACTERÍSTICAS PRINCIPALES:
1. VENTA DE FICHAS POR HOTSPOT
   - Venta de acceso por tiempo (1h, 24h, 1 semana)
   - Procesamiento instantáneo de pagos
   - Entrega inmediata de credenciales
   - Auto-conexión automática

2. ADMINISTRACIÓN MULTI-USUARIO
   - Super Admin: Gestión completa del sistema de venta de fichas
   - Cliente Admin: Administración por empresa de ventas de fichas
   - Usuario Final: Compra de fichas desde portal WiFi

3. AUTENTICACIÓN DUAL PARA VENTA DE FICHAS
   - Sesiones JWT para portal administrativo de fichas
   - API Keys JWT para portal público de venta de fichas
   - Roles granulares para gestión de ventas

4. PROCESAMIENTO DE PAGOS PARA FICHAS
   - Integración Conekta para venta de fichas por tarjeta
   - Validación doble de transacciones de fichas
   - Sistema automático de rollback en venta de fichas fallida

5. GESTIÓN MIKROTIK PARA VENTA DE FICHAS
   - Creación automática de usuarios al comprar fichas por tarjeta
   - Auto-conexión mediante MAC Cookies en venta de fichas
   - Test de conexión en tiempo real para sistema de fichas
   - Perfiles técnicos mapeados a productos de fichas

6. CATÁLOGO DE FICHAS
   - Fichas personalizables por empresa/router
   - Detalles JSON para fichas vendidas
   - Orden visual de fichas disponibles
   - Fichas destacadas para promociones

ARQUITECTURA:
[Portal Cautivo MikroTik] → [API HotSpot Manager] → [MikroTik Router] → [Internet]
         ↑                            ↑                     ↑
         |                            |                     |
   [Cliente paga]             [Procesa pago]          [Crea usuario]
         |                            |                     |
   [Conekta]                   [PostgreSQL]           [Auto-conexión]


INSTALACIÓN RÁPIDA PARA SISTEMA DE FICHAS:

1. PRERREQUISITOS PARA VENTA DE FICHAS:
   - Python 3.9+ para sistema de fichas
   - PostgreSQL 15+ para registro de ventas de fichas
   - MikroTik RouterOS 6+ para hotspot de fichas
   - Cuenta en Conekta.com para pago de fichas

2. CONFIGURACIÓN DEL SISTEMA DE FICHAS:
   git clone <repositorio-venta-fichas>
   cd hotspot-fichas-manager
   python -m venv venv
   source venv/bin/activate  # Linux/Mac
   pip install -r requirements.txt
   cp .env.example .env
   # Editar .env con configuración para venta de fichas

3. BASE DE DATOS PARA REGISTRO DE FICHAS:
   createdb venta_fichas_db
   alembic upgrade head

4. INICIAR SERVIDOR DE VENTA DE FICHAS:
   # Desarrollo
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   
   # Producción para venta de fichas
   gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000

ENDPOINTS PRINCIPALES PARA VENTA DE FICHAS:

A) PARA SUPER ADMIN (Backoffice de fichas):
   POST   /admin/empresas                # Crear empresa para venta de fichas
   POST   /admin/empresas/{id}/routers   # Crear router + API Key para fichas
   POST   /admin/usuarios                # Crear administradores de fichas
   GET    /admin/dashboard               # Dashboard global de venta de fichas

B) PARA CLIENTE ADMIN (Panel de fichas):
   GET    /mi-empresa                    # Información de empresa de fichas
   PUT    /mi-empresa/conekta-config     # Configurar Conekta para fichas
   GET    /products                      # Listar fichas disponibles
   POST   /products                      # Crear ficha de venta
   GET    /routers/{id}/mikrotik-profiles # Perfiles para fichas MikroTik

C) PARA USUARIO FINAL (Compra de fichas):
   GET    /config/public                 # Config pública para compra de fichas
   GET    /catalogo_perfiles_venta       # Catálogo de fichas disponibles
   POST   /payments/pagar-conekta        # Procesar pago de ficha

FLUJO COMPLETO DE COMPRA DE FICHAS:

1. Cliente se conecta a la red WiFi con venta de fichas
2. Accede al portal cautivo para comprar fichas
3. Solicita catálogo: GET /catalogo_perfiles_venta
4. Selecciona ficha y paga: POST /payments/pagar-conekta
5. Sistema procesa pago de ficha con Conekta
6. Crea usuario en MikroTik automáticamente (entrega ficha)
7. Si cliente proporcionó MAC, ejecuta auto-conexión por ficha
8. Devuelve credenciales de la ficha al cliente
9. Cliente se conecta automáticamente.

SISTEMA DE API KEYS PARA VENTA DE FICHAS:

- Cada router tiene una API Key JWT única para venta de fichas
- Formato: "jwt_" + token JWT específico para fichas
- Ejemplo: jwt_eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
- Validez: 1 año por defecto para sistema de fichas
- Se puede regenerar si se pierde (para no interrumpir venta de fichas)
- Se puede revocar si es comprometida (seguridad en venta de fichas)
- Uso en headers: X-API-Key: jwt_... (para todas las peticiones de fichas)


VARIABLES DE ENTORNO ESENCIALES PARA SISTEMA DE FICHAS:

DATABASE_URL=postgresql://user:pass@localhost/venta_fichas_db
JWT_APIKEY_SECRET=secreto_api_keys_venta_fichas
JWT_SESSION_SECRET=secreto_sesiones_venta_fichas
SUPER_ADMIN_INITIAL_EMAIL=admin@ventafichas.com
SUPER_ADMIN_INITIAL_PASSWORD=ClaveAdminFichas123!
CONEKTA_DEFAULT_PRIVATE_KEY=sk_test_xxxx_para_fichas
CONEKTA_DEFAULT_PUBLIC_KEY=pk_test_xxxx_para_fichas


AUTO-CONEXIÓN EN VENTA DE FICHAS (MAC COOKIES):

Requisitos para auto-conexión al comprar ficha:
- Cliente debe estar en /ip/hotspot/host del router
- auto_connect: true en la petición de compra de ficha
- mac_address proporcionada al comprar ficha
- Pago de ficha exitoso procesado

Proceso de auto-conexión con ficha:
1. Vincular MAC al usuario de la ficha
2. Crear MAC Cookie en MikroTik para la ficha
3. Ejecutar login automático con la ficha
4. Verificar en sesiones activas la ficha usada

PRUEBAS CON TARJETAS PARA COMPRA DE FICHAS:

VISA: 4242 4242 4242 4242 (para probar compra de fichas)
CVV: 123 (para todas las pruebas de fichas)
Fecha: Cualquier fecha futura (pruebas de compra de fichas)

BACKUP Y RECUPERACIÓN DE DATOS DE FICHAS:

# Backup de base de datos de fichas
pg_dump venta_fichas_db > backup_fichas_$(date +%Y%m%d).sql

# Restaurar backup de venta de fichas
psql venta_fichas_db < backup_fichas_20240101.sql

MODELO DE NEGOCIO DE VENTA DE FICHAS:

CONFIGURACIÓN PORTAL CAUTIVO PARA VENTA DE FICHAS:

1. HTML básico para venta de fichas en MikroTik
2. Integración Conekta.js para pago de fichas
3. Llamadas a los 3 endpoints del sistema de fichas:
   a) GET /config/public → Clave pública para pagos con conekta
   b) GET /catalogo_perfiles_venta → Lista de fichas
   c) POST /payments/pagar-conekta → Compra de ficha

EJEMPLO DE LLAMADAS PARA VENTA DE FICHAS:

// 1. Obtener configuración para compra de fichas
fetch('https://api-tuempresa.com/config/public', {
  headers: { 'X-API-Key': 'API_KEY_VENTA_FICHAS' }
})

// 2. Cargar fichas disponibles
fetch('https://api-tuempresa.com/catalogo_perfiles_venta', {
  headers: { 'X-API-Key': 'API_KEY_VENTA_FICHAS' }
})

// 3. Comprar ficha específica
fetch('https://api-tuempresa.com/payments/pagar-conekta', {
  method: 'POST',
  headers: { 
    'X-API-Key': 'API_KEY_VENTA_FICHAS',
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    product_id: 1,  // ID de la ficha
    card_token: token_tarjeta,
    customer_name: nombre_cliente,
    customer_email: email_cliente,
    mac_address: mac_dispositivo,
    auto_connect: true
  })
})

CONTACTO Y SOPORTE PARA SISTEMA DE FICHAS:

- Soporte técnico: soporte@wispremote.com
- Documentación: docs.wispremote.com
- Teléfono: 2203318661 (soporte venta de fichas)


VERSIÓN:
2.0.0 - Sistema completo de venta de fichas por hotspot WiFi