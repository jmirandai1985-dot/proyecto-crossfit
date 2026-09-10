"""Router de endpoints de administración (tarjetas/notificaciones del panel admin)."""
from datetime import datetime, time

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.core.dependencies import get_current_admin
from app.models.usuario import Usuario, RolUsuario
from app.models.suscripcion import Suscripcion
from app.models.plan import Plan
from app.models.reserva import Reserva
from app.models.clase import Clase
from app.models.disciplina import Disciplina
from app.utils.santiago import SANTIAGO, hoy_santiago

router = APIRouter()


@router.get("/alumnos-prueba-hoy")
def get_alumnos_prueba_hoy(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Alumnos con plan "Prueba" registrados HOY. Solo admins.

    - `get_current_admin` ya restringe a rol administrador (403 si no lo es).
    - "Hoy" se calcula en hora de Chile (America/Santiago) y se compara contra
      `usuarios.created_at` (TIMESTAMPTZ), por lo que es correcto aunque el
      servidor corra en UTC.

    Retorna: {total, alumnos: [{id, nombre, correo, hora_registro, plan,
    estado_suscripcion, creditos_disponibles, clase_tomada}]}.

    `clase_tomada` = última reserva con estado 'confirmada' del alumno:
    {disciplina, fecha, horario, coach} o None si aún no reservó clase.
    """
    tenant_id = current_user["tenant_id"]

    # Inicio del día de HOY en hora de Chile (tz-aware) → comparable con created_at.
    inicio_hoy = datetime.combine(hoy_santiago(), time.min, tzinfo=SANTIAGO)

    filas = (
        db.query(Usuario, Suscripcion)
        .join(Suscripcion, Suscripcion.usuario_id == Usuario.id)
        .join(Plan, Plan.id == Suscripcion.plan_id)
        .filter(
            Usuario.tenant_id == tenant_id,
            Usuario.rol == RolUsuario.alumno,
            Plan.tenant_id == tenant_id,
            Plan.nombre == "Prueba",
            Usuario.created_at >= inicio_hoy,
        )
        .order_by(Usuario.created_at.desc())
        .all()
    )

    # Deduplicar por alumno (por si hubiera >1 suscripción "Prueba"): la más reciente.
    vistos = set()
    alumnos = []
    for usuario, sus in filas:
        if usuario.id in vistos:
            continue
        vistos.add(usuario.id)
        alumnos.append({
            "id": usuario.id,
            "nombre": usuario.nombre,
            "correo": usuario.correo,
            "hora_registro": usuario.created_at.isoformat() if usuario.created_at else None,
            "plan": "Prueba",
            "estado_suscripcion": sus.estado,
            "creditos_disponibles": sus.creditos_disponibles,
        })

    # ── Última clase reservada (estado 'confirmada') de cada alumno ──────────
    # Sin relaciones ORM: JOIN manual Reserva→Clase→(Disciplina, Usuario coach).
    ids = [a["id"] for a in alumnos]
    ultima_clase = {}
    if ids:
        filas_res = (
            db.query(Reserva.alumno_id, Clase.fecha, Clase.hora_inicio,
                     Disciplina.nombre, Usuario.nombre)
            .join(Clase, Clase.id == Reserva.clase_id)
            .outerjoin(Disciplina, Disciplina.id == Clase.disciplina_id)
            .outerjoin(Usuario, Usuario.id == Clase.coach_id)
            .filter(
                Reserva.tenant_id == tenant_id,
                Reserva.alumno_id.in_(ids),
                Reserva.estado == "confirmada",
            )
            .order_by(Reserva.alumno_id, Clase.fecha.desc(),
                      Clase.hora_inicio.desc())
            .all()
        )
        for alumno_id, fecha, hora_inicio, disc_nombre, coach_nombre in filas_res:
            if alumno_id in ultima_clase:
                continue  # ya se guardó la más reciente (ordenado desc)
            ultima_clase[alumno_id] = {
                "disciplina": disc_nombre or "Sin disciplina",
                "fecha": fecha.isoformat() if fecha else None,
                "horario": hora_inicio.strftime("%H:%M") if hora_inicio else None,
                "coach": coach_nombre or "Sin asignar",
            }

    for a in alumnos:
        a["clase_tomada"] = ultima_clase.get(a["id"])

    return {"total": len(alumnos), "alumnos": alumnos}
