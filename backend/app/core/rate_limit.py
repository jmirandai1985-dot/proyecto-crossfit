"""
Rate limiting global (slowapi).

Uso en endpoints:
    @router.post("/login")
    @limiter.limit("5/minute")
    def login(request: Request, ...):
        ...

La clave por defecto es la IP del cliente (get_remote_address).
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

# Límite por IP
limiter = Limiter(key_func=get_remote_address)

# Límites predefinidos reutilizables
LIMIT_LOGIN = "5/minute"          # fuerza bruta de login
LIMIT_REGISTRO = "5/hour"          # abuso de registro masivo
LIMIT_CRITICO = "30/minute"        # cambios sensibles (pagos/aprobaciones)
# GET /configuracion: la ficha bancaria del box la leen TRES pantallas (Configuración,
# Bazar y Solicitar plan) y detrás de una misma IP puede estar todo un box entrenando
# (NAT de la sede/WiFi compartido). El límite es anti-abuso (un token filtrado no puede
# barrer la tabla a fuerza bruta), no una barrera para el alumno: 120/min ≈ 2 por segundo.
LIMIT_CONFIG_LECTURA = "120/minute"
# Código de retiro del Bazar: el mesón lo teclea/escanea y un código sólo tiene 4
# símbolos (31^4 = 923.521 combinaciones). Sin límite, un atacante con un token de
# coach podría barrer códigos hasta acertar el de otro alumno.
LIMIT_CODIGO_RETIRO = "10/minute"
