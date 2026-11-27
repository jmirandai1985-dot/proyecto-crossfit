"""Locust: flujo de LECTURA del panel admin contra el backend de TEST.

Qué hace
--------
1. Login del admin de prueba (`POST /api/v1/auth/login`).
2. Consultas de sólo lectura que usa el Dashboard/Admin: contadores de
   pendientes, alumnos activos/nuevos y la cola de activación de alumnos.

No hay credenciales en el archivo: la contraseña (y el correo) salen de
variables de entorno. Si falta la contraseña, `on_start` falla con un mensaje
claro (Locust lo cuenta como fallo de usuario, no inventa un login exitoso).

Uso (headless, volumen bajo):
    $env:LOAD_ADMIN_EMAIL    = "carga_k6_admin@load.test"
    $env:LOAD_ADMIN_PASSWORD = <TEST_SEED_PASSWORD de backend/.env.test>
    .venv-tools\\Scripts\\locust -f backend/locustfile.py \\
        --headless -u 10 -r 2 -t 30s --host http://localhost:8000
"""
import os
import threading

from locust import HttpUser, between, task

ADMIN_EMAIL = os.getenv("LOAD_ADMIN_EMAIL", "carga_k6_admin@load.test")
ADMIN_PASSWORD = (
    os.getenv("LOAD_ADMIN_PASSWORD")
    or os.getenv("LOAD_PASSWORD")
    or os.getenv("TEST_SEED_PASSWORD")
    or ""
)

# El login tiene rate limit (5/min): con 10 usuarios, cada uno logueándose daría
# 429 y la mitad de las lecturas iría sin token. El flujo es de LECTURA, así que
# se hace UN login compartido (thread-safe) y los 10 usuarios leen con ese token.
_TOKEN = None
_TOKEN_LOCK = threading.Lock()


class AdminLectura(HttpUser):
    """Admin autenticado que sólo lee (no crea, no cobra, no cancela)."""

    wait_time = between(1, 2)

    def on_start(self):
        global _TOKEN
        if not ADMIN_PASSWORD:
            raise RuntimeError(
                "Falta LOAD_ADMIN_PASSWORD (o TEST_SEED_PASSWORD): "
                "exportala antes de correr Locust."
            )
        with _TOKEN_LOCK:
            if _TOKEN is None:
                with self.client.post(
                    "/api/v1/auth/login",
                    json={"correo": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                    name="POST /auth/login",
                    catch_response=True,
                ) as respuesta:
                    if respuesta.status_code != 200:
                        respuesta.failure(
                            f"login {respuesta.status_code}: {respuesta.text[:120]}")
                        return
                    _TOKEN = (respuesta.json() or {}).get("access_token")
        self.client.headers.update({"Authorization": f"Bearer {_TOKEN}"})

    @task(4)
    def resumen_pendientes(self):
        self.client.get(
            "/api/v1/admin/pendientes/resumen",
            name="GET /admin/pendientes/resumen",
        )

    @task(3)
    def alumnos_activos(self):
        self.client.get(
            "/api/v1/admin/alumnos-activos",
            params={"limite": 10},
            name="GET /admin/alumnos-activos",
        )

    @task(2)
    def alumnos_nuevos(self):
        self.client.get(
            "/api/v1/admin/alumnos-nuevos",
            name="GET /admin/alumnos-nuevos",
        )

    @task(1)
    def alumnos_pendientes(self):
        self.client.get(
            "/api/v1/alumnos/pendientes-activacion",
            name="GET /alumnos/pendientes-activacion",
        )
