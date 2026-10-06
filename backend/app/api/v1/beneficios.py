"""Router de Beneficios de Fidelización (Fase 2): dar, ver y anular un regalo.

Qué es un beneficio
-------------------
Un regalo del box a UN alumno: unas clases gratis (el "Pase de regreso") o un descuento en su
próximo plan. El acceso se materializa al DARLO (no hay aceptación) y toda la regla de negocio
—ventana de 15 días, tope del descuento, créditos, vencimiento de los vencidos, revocación al
anular— vive en `app/services/beneficios_service.py`. Acá se traduce HTTP ↔ servicio: ACL/tenant,
validación del cuerpo y errores con el texto que el panel ya muestra.

Endpoints
---------
  * `GET  /api/v1/beneficios/tipos`         → el catálogo de regalos + el tope que autoriza el box.
  * `GET  /api/v1/beneficios/alumno/{id}`   → lo que el modal necesita ANTES de intentar crear:
                                              qué regalos tiene vivos (con el texto del aviso) y su
                                              plan vigente (para decir si las clases se suman a ese
                                              plan o si se le abre el pase).
  * `GET  /api/v1/beneficios`               → todos los beneficios del box (filtros + resumen F4).
  * `POST /api/v1/beneficios`               → lo da (y opcionalmente avisa por correo).
  * `POST /api/v1/beneficios/preview`       → el correo EXACTO que se le va a mandar.
  * `POST /api/v1/beneficios/{id}/anular`   → lo anula (motivo obligatorio) y revoca lo entregado.

Reglas de esta capa
-------------------
1. **`409` con el MISMO texto que el panel** cuando el alumno ya tiene un regalo vivo del mismo
   tipo: el detalle es `aviso_vigente()` —el que la fila muestra—, así el error y la pantalla no
   se contradicen (y el panel lo enseña ANTES de intentar crear, en `GET /alumno/{id}`).
2. **El `estado` lo dice el servicio, no la columna.** Un `ofrecido` con la ventana pasada se
   lee y se filtra como `vencido` usando `esta_vivo()` (la única definición de "vivo"): la
   lectura no escribe, pero tampoco puede hacer parecer usable un regalo que ya no lo es.
3. **Nada de números de negocio en el router**: la ventana sale de `svc.ventana()`, el tope de
   `svc.tope_descuento()` y el plan del pase de `svc.plan_del_pase()` (que lo reusa o lo crea: el
   box no configura nada).
4. **El alumno y el beneficio se buscan dentro del box del token**: otro box es 404, no 403.
"""
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_admin, get_current_user
from app.db.database import get_db
from app.models.beneficio import Beneficio, EstadoBeneficio, TipoBeneficio
from app.models.plan import Plan
from app.models.usuario import Usuario
from app.services import beneficios_service as svc
from app.services import fidelizacion_plantillas as plantillas
from app.services import churn_service

router = APIRouter()

# Estados con los que el panel filtra la pestaña "Beneficios". `vigente` y `vencido` son los del
# SERVICIO (`esta_vivo`), no columnas: la columna sólo distingue ofrecido/usado/vencido/anulado.
ESTADOS_FILTRO = ("vigente", "usado", "vencido", "anulado", "todos")
# Máximo de filas por página (la tabla del panel usa 25).
MAX_POR_PAGINA = 100
# Máximo de planes para los que se calcula el precio con descuento en UNA consulta (`/mios`).
MAX_PLANES = 60
# Valores válidos de `tipo` en un query string, sacados del catálogo del servicio (un tipo nuevo
# entra a la API sola) — el `pattern` hace que un typo sea un 422 del cliente y no un filtro vacío.
PATRON_TIPOS = "^(" + "|".join(svc.TIPOS_VALIDOS) + ")$"


class NuevoBeneficio(BaseModel):
    """El regalo que se pide: a quién, de qué tipo y con qué valor."""

    alumno_id: int = Field(..., gt=0, description="Alumno del box del token.")
    tipo: str = Field(..., description="Tipo del catálogo: `descuento` o `clases_gratis`.")
    valor: int = Field(..., gt=0,
                       description="% de descuento o nº de clases, según el tipo.")
    plan_id: Optional[int] = Field(
        None, description="Plan del pase (opcional): si no se manda, se usa el del box o se crea.")
    avisar_por_correo: bool = Field(
        False, description="Manda el correo del regalo después de crearlo.")


class ConsultaBeneficio(BaseModel):
    """Lo mismo que `NuevoBeneficio`, sin crear nada: sólo se quiere ver el correo."""

    alumno_id: int = Field(..., gt=0)
    tipo: str
    valor: int = Field(..., gt=0)
    plan_id: Optional[int] = Field(
        None, description="Plan del pase (opcional): si no se manda, se usa el del box o se crea.")


class Anulacion(BaseModel):
    """Por qué se anula: sin motivo no se anula (una fila que nadie puede auditar después)."""

    motivo: str = Field(..., min_length=3, max_length=300,
                        description="Motivo de la anulación (obligatorio).")


def _alumno_del_box(db: Session, current_user: dict, alumno_id: int) -> Usuario:
    """El alumno, siempre DENTRO del box del token (otro box es 404, no 403)."""
    alumno = db.query(Usuario).filter(
        Usuario.id == alumno_id, Usuario.tenant_id == current_user["tenant_id"]).first()
    if alumno is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Alumno {alumno_id} no encontrado en este box")
    return alumno


def _beneficio_del_box(db: Session, current_user: dict, beneficio_id: int) -> Beneficio:
    """El beneficio, siempre DENTRO del box del token."""
    beneficio = db.query(Beneficio).filter(
        Beneficio.id == beneficio_id,
        Beneficio.tenant_id == current_user["tenant_id"]).first()
    if beneficio is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Beneficio {beneficio_id} no encontrado en este box")
    return beneficio


def _iso(momento):
    """Instante → ISO (o `None`): el panel formatea las fechas, no las adivina."""
    return momento.isoformat() if momento else None


def _dias(a, b):
    """Días entre dos instantes (o `None`): `usado_en - created_at` es una métrica de la F4."""
    return (a - b).days if a is not None and b is not None else None


def _item(beneficio: Beneficio, alumno=None) -> dict:
    """Un beneficio como lo dibuja el panel: estado REAL, vigencia y si se puede anular.

    El `estado` que viaja NO es la columna: es `esta_vivo()` (el servicio) con la columna como
    respaldo. Un `ofrecido` cuya ventana pasó se muestra `vencido` sin escribirlo —la lectura no
    escribe: al vencido lo vence el alta del siguiente (corrección B)—, pero no puede parecer
    usable ni un segundo. `puede_anular` es la MISMA condición que exige `anular()`.
    """
    vivo = svc.esta_vivo(beneficio)
    estado = ("vigente" if vivo else
              ("vencido" if beneficio.estado == EstadoBeneficio.ofrecido
               else beneficio.estado.value))
    return {
        "id": beneficio.id,
        "alumno_id": beneficio.alumno_id,
        "alumno_nombre": getattr(alumno, "nombre", None),
        "alumno_correo": getattr(alumno, "correo", None),
        "tipo": beneficio.tipo.value,
        "tipo_label": svc.etiqueta(beneficio.tipo),
        "unidad": "pct" if beneficio.tipo == TipoBeneficio.descuento else "clases",
        "valor": beneficio.valor,
        "estado": estado,
        "estado_bd": beneficio.estado.value,
        "puede_anular": beneficio.estado == EstadoBeneficio.ofrecido,
        "vigente_hasta": _iso(beneficio.vigente_hasta),
        "created_at": _iso(beneficio.created_at),
        "usado_en": _iso(beneficio.usado_en),
        "anulado_at": _iso(beneficio.anulado_at),
        "anulado_motivo": beneficio.anulado_motivo,
        "descuento_clp": beneficio.descuento_clp,
        "dias_hasta_uso": _dias(beneficio.usado_en, beneficio.created_at),
        "notificacion_id": beneficio.notificacion_id,
        "aviso": svc.aviso_vigente(beneficio) if vivo else None,
    }


def _tipos(db: Session, tenant_id: int) -> dict:
    """El catálogo de regalos con el tope del box y la ventana vigente.

    La ventana viaja para que el panel la pueda MOSTRAR ("vigencia: 15 días") sin tener su propia
    copia del número: el modal informa, no decide (la ventana la aplica el servicio al crear).
    """
    return {"tipos": [dict(t) for t in svc.TIPOS],
            "tope_descuento": svc.tope_descuento(db, tenant_id),
            "dias_vigencia": svc.DIAS_VIGENCIA}


def _plan_del_pase(beneficio: Beneficio, db: Session):
    """El nombre del plan del alumno al que se sumaron las clases (o `None`).

    Sólo cuando el plan es COMERCIAL (`es_comercial`, la misma columna de la corrección A): si
    los créditos fueron a un pase, el nombre del plan no le dice nada al alumno y el correo no lo
    nombra. Se usa en el alta y en el preview para que el texto sea el mismo.
    """
    if beneficio.tipo != TipoBeneficio.clases_gratis or beneficio.plan_id is None:
        return None
    fila = db.query(Plan.nombre, Plan.es_comercial).filter(Plan.id == beneficio.plan_id).first()
    if fila is None or not fila[1]:
        return None
    return fila[0]


def _resumen(items: list) -> dict:
    """Las métricas de la F4 sobre lo que se está mirando (el filtro activo, sin paginar).

    Son números CONTABLES de la tabla —cuántos regalos hay en cada estado, cuántos se usaron,
    cuánto descuento se aplicó y cuántos días tardó el alumno en volver—, no una proyección.
    `dias_hasta_uso_promedio` y `tasa_uso_pct` son `None` cuando todavía no hay datos: un 0 %
    inventado se lee como "nadie los usa", que no es lo mismo que "todavía no se usó ninguno".
    """
    por_estado = {e: sum(1 for i in items if i["estado"] == e)
                  for e in ("vigente", "usado", "vencido", "anulado")}
    usados = [i for i in items if i["estado"] == "usado"]
    con_vida = por_estado["vigente"] + por_estado["usado"] + por_estado["vencido"]
    dias = [i["dias_hasta_uso"] for i in usados if i["dias_hasta_uso"] is not None]
    return {
        "total": len(items),
        "por_estado": por_estado,
        "tasa_uso_pct": (round(100 * len(usados) / con_vida, 1) if con_vida else None),
        "descuento_clp_total": sum(i["descuento_clp"] or 0 for i in usados),
        "dias_hasta_uso_promedio": (round(sum(dias) / len(dias), 1) if dias else None),
        "con_correo": sum(1 for i in items if i["notificacion_id"]),
        "sin_correo": sum(1 for i in items if not i["notificacion_id"]),
    }


def _precios_con_descuento(db: Session, tenant_id: int, descuento, plan_ids) -> dict:
    """`{plan_id: desglose}` de los planes pedidos, con el MISMO cálculo que se cobra.

    La aritmética es del SERVICIO (`desglose`): la pantalla muestra un precio, no lo calcula. La
    usan las dos puertas —la del alumno (`/mios`) y la del panel (`/alumno/{id}`)—, así que no
    pueden mostrar dos precios distintos del mismo plan. `plan_ids` es una lista separada por comas.
    """
    if descuento is None or not plan_ids:
        return {}
    ids = [int(trozo) for trozo in str(plan_ids).split(",") if trozo.strip().isdigit()][:MAX_PLANES]
    if not ids:
        return {}
    precios = {}
    for plan in db.query(Plan).filter(
            Plan.id.in_(ids), Plan.tenant_id == tenant_id).all():
        lista = plan.precio_clp
        if isinstance(lista, int) and not isinstance(lista, bool) and lista > 0:
            precios[str(plan.id)] = svc.desglose(descuento, lista)
    return precios


@router.get("/tipos")
def tipos_disponibles(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Qué se puede regalar en ESTE box: los tipos del catálogo y el tope del descuento.

    El modal no elige el máximo (lo decide la configuración del box) ni la ventana (la fija el
    servicio): acá sólo se los cuenta para que la pantalla pueda avisar antes de que el alta falle.
    """
    return _tipos(db, current_user["tenant_id"])


@router.get("/alumno/{alumno_id}")
def estado_del_alumno(
    alumno_id: int,
    plan_ids: Optional[str] = Query(
        None,
        description="Ids de planes separados por coma: devuelve el precio con el descuento puesto "
                    "de cada uno (lo usa la asignación manual del panel)."),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Todo lo que el panel necesita saber ANTES de intentar crearle un regalo a este alumno.

    Devuelve, por tipo, el AVISO del regalo que ya tiene vivo (`aviso_vigente`: el mismo texto del
    409, así el panel lo enseña antes de mandar la petición en vez de después) y, para las clases
    gratis, si las va a recibir en su plan o si se le va a abrir el pase. Con esto el modal puede
    decir qué va a pasar sin adivinar ni crear nada — y sin elegir el plan del pase: ese lo resuelve
    el servicio (`svc.plan_del_pase`: reusa el del box o lo crea).
    """
    alumno = _alumno_del_box(db, current_user, alumno_id)
    vivos = svc.vivos(db, alumno.id)
    avisos = {}
    for tipo in svc.TIPOS_VALIDOS:
        vivo = next((b for b in vivos if b.tipo.value == tipo), None)
        avisos[tipo] = svc.aviso_vigente(vivo) if vivo is not None else None
    # El descuento vivo (si lo hay) es lo que el panel necesita para precargar el precio final.
    descuento = next((b for b in vivos if b.tipo == TipoBeneficio.descuento), None)

    plan = svc.plan_vigente(db, alumno)
    plan_nombre = None
    if plan is not None:
        plan_nombre = db.query(Plan.nombre).filter(Plan.id == plan.plan_id).scalar()

    return {
        "alumno": {
            "id": alumno.id,
            "nombre": alumno.nombre,
            "correo": alumno.correo,
            "tiene_correo": bool((alumno.correo or "").strip()),
        },
        **_tipos(db, current_user["tenant_id"]),
        "vivos": [_item(b, alumno) for b in vivos],
        "avisos": avisos,
        "descuento_pct": (descuento.valor if descuento is not None else None),
        "descuento_hasta": (descuento.vigente_hasta.isoformat()
                            if descuento is not None else None),
        "precios": _precios_con_descuento(db, current_user["tenant_id"], descuento, plan_ids),
        "plan_vigente": (None if plan is None else {
            "plan_id": plan.plan_id, "nombre": plan_nombre,
            "creditos_disponibles": plan.creditos_disponibles,
            "vence": _iso(plan.fecha_expiracion),
        }),
    }


@router.get("")
def listar_beneficios(
    estado: str = Query("todos", pattern="^(" + "|".join(ESTADOS_FILTRO) + ")$",
                        description="Filtro por estado real del regalo."),
    tipo: Optional[str] = Query(None, pattern=PATRON_TIPOS),
    alumno_id: Optional[int] = Query(None, gt=0),
    q: Optional[str] = Query(None, max_length=80,
                             description="Nombre o correo del alumno (búsqueda parcial)."),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(25, ge=1, le=MAX_POR_PAGINA),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """TODOS los beneficios del box —vigentes, usados, vencidos y anulados— con su resumen.

    El filtro de `estado` se aplica con `esta_vivo()` (la única definición de "vivo"), no con una
    segunda consulta: `vigente` es un `ofrecido` cuya ventana no pasó y `vencido` es cualquiera que
    ya no sirve —incluido el `ofrecido` cuya fila todavía dice `ofrecido`—, así la tabla no puede
    mostrar como usable un regalo que el alumno ya no puede usar.

    El resumen se calcula sobre el filtro COMPLETO (no sobre la página): el panel lo muestra como
    "sobre lo filtrado" y con la paginación sus números no cambiarían al pasar de página.
    """
    consulta = db.query(Beneficio, Usuario).join(
        Usuario, Usuario.id == Beneficio.alumno_id).filter(
        Beneficio.tenant_id == current_user["tenant_id"])
    if tipo:
        consulta = consulta.filter(Beneficio.tipo == tipo)
    if alumno_id:
        consulta = consulta.filter(Beneficio.alumno_id == alumno_id)
    if q and q.strip():
        patron = f"%{q.strip()}%"
        consulta = consulta.filter(or_(Usuario.nombre.ilike(patron),
                                      Usuario.correo.ilike(patron)))

    filas = consulta.order_by(Beneficio.created_at.desc(), Beneficio.id.desc()).all()
    items = [_item(beneficio, alumno) for beneficio, alumno in filas]
    if estado != "todos":
        items = [i for i in items if i["estado"] == estado]

    inicio = (pagina - 1) * por_pagina
    return {
        "items": items[inicio:inicio + por_pagina],
        "total": len(items),
        "pagina": pagina,
        "por_pagina": por_pagina,
        "resumen": _resumen(items),
    }


def _avisar(db: Session, alumno, beneficio: Beneficio) -> dict:
    """Manda el correo que anuncia el regalo y lo deja LIGADO al beneficio.

    La plantilla sale del TIPO del beneficio (`beneficio_descuento` / `beneficio_clases_gratis`):
    el copy vive en un solo lugar y el log de correos queda agrupado por tipo de regalo, que es lo
    que la F4 mide. Si el correo no sale, el beneficio NO se toca: se informa (`estado: fallido`)
    y el panel lo muestra — un correo que no salió no puede deshacer un regalo que ya está dado
    en los créditos del alumno.
    """
    plantilla = (plantillas.P_BENEFICIO_DESCUENTO
                 if beneficio.tipo == TipoBeneficio.descuento
                 else plantillas.P_BENEFICIO_CLASES_GRATIS)
    datos = {"tipo": beneficio.tipo.value, "valor": beneficio.valor,
             "vigente_hasta": beneficio.vigente_hasta,
             "plan": _plan_del_pase(beneficio, db)}
    try:
        resultado = plantillas.enviar(db, alumno, plantilla, datos)
    except plantillas.PlantillaSinDatos as e:
        return {"ok": False, "estado": "fallido", "notificacion_id": None,
                "destinatario": None, "asunto": None, "detalle_error": str(e)}

    if resultado.get("notificacion_id"):
        notificacion_antes = beneficio.notificacion_id
        beneficio.notificacion_id = resultado["notificacion_id"]
        db.commit()
        db.refresh(beneficio)
        if notificacion_antes is not None and notificacion_antes != beneficio.notificacion_id:
            # No debería pasar (un beneficio se crea sin correo y se avisa una sola vez): si
            # pasara, la fila queda apuntando al ÚLTIMO correo que anunció el regalo.
            resultado["notificacion_previa"] = notificacion_antes
    return resultado


@router.post("", status_code=status.HTTP_201_CREATED)
def dar_beneficio(
    datos: NuevoBeneficio,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Da el regalo (y materializa el acceso) y, si el admin lo marcó, avisa por correo.

    ORDEN, y por qué: primero se CREA el beneficio —es el alta la que materializa el acceso y fija
    la ventana— y después se manda el correo con los números REALES de la fila, que queda ligada al
    envío (`notificacion_id`). Al revés no se puede: el correo tiene que decir hasta cuándo vale el
    regalo, y eso lo decide el alta.

    `409` = el alumno ya tiene un regalo VIVO de ese tipo, con el mismo texto que muestra el panel
    (`aviso_vigente`). `422` = el tipo no está en el catálogo. `400` = el valor no sirve o el
    `plan_id` es de otro box (el tope lo decide la configuración del box y el mensaje lo explica).
    El plan del PASE no se pide: si el alumno no tiene plan vigente, el servicio usa el plan del pase
    del box o lo crea (`svc.plan_del_pase`) — el admin no configura nada.
    """
    alumno = _alumno_del_box(db, current_user, datos.alumno_id)
    try:
        beneficio = svc.crear(db, alumno, datos.tipo, datos.valor, plan_id=datos.plan_id,
                              ofrecido_por=current_user.get("usuario_id"))
    except svc.BeneficioYaVigente as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except svc.TipoDesconocido as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except (svc.ValorInvalido, svc.DescuentoSobreTope, svc.PlanInvalido) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    correo = _avisar(db, alumno, beneficio) if datos.avisar_por_correo else None

    # El regalo cambió los créditos del alumno (o le abrió un pase) -> recalc (segundo plano).
    churn_service.programar_recalculo(background_tasks, current_user["tenant_id"], datos.alumno_id)

    return {"beneficio": _item(beneficio, alumno), "correo": correo}


@router.get("/mios")
def mis_beneficios(
    plan_ids: Optional[str] = Query(
        None,
        description="Ids de planes separados por coma: devuelve el precio con el descuento puesto "
                    "de cada uno (lo usa la pantalla de solicitar plan)."),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Los regalos VIVOS del alumno que consulta (su propia puerta, sin panel).

    Es lo que su pantalla necesita para saber si tiene un descuento al solicitar un plan: el % y
    HASTA CUÁNDO. Sólo viajan los vivos (`esta_vivo`): el descuento que ya usó o que venció no se
    anuncia, porque el backend no lo va a aplicar y prometer un precio es peor que no prometerlo.

    Con `plan_ids` va además el precio final de cada plan, calculado por el SERVICIO (`desglose`):
    la pantalla muestra un número, no lo calcula (una segunda aritmética del descuento se
    desincroniza del cobro por un peso y el alumno lo ve).
    """
    vivos = svc.vivos(db, current_user["usuario_id"])
    descuento = next((b for b in vivos if b.tipo == TipoBeneficio.descuento), None)

    return {
        "vivos": [_item(b) for b in vivos],
        "descuento_pct": (descuento.valor if descuento is not None else None),
        "descuento_hasta": (descuento.vigente_hasta.isoformat()
                            if descuento is not None else None),
        "precios": _precios_con_descuento(db, current_user["tenant_id"], descuento, plan_ids),
    }


@router.post("/preview")
def preview_beneficio(
    datos: ConsultaBeneficio,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """El correo EXACTO que recibiría el alumno si el admin confirma (no manda ni crea nada).

    Se renderiza por el MISMO camino que el envío y con la ventana REAL (`svc.ventana()`: los
    mismos días que aplicaría el alta): el admin aprueba un mensaje, no una idea del mensaje. El
    plan sólo se nombra cuando las clases se SUMARÍAN a un plan del alumno; si se le va a abrir el
    pase, el correo no habla de un plan que no existe.
    """
    alumno = _alumno_del_box(db, current_user, datos.alumno_id)
    if not svc.tipo_valido(datos.tipo):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Tipo de beneficio desconocido: `{datos.tipo}`. "
                   f"Válidos: {', '.join(svc.TIPOS_VALIDOS)}.")
    plantilla = (plantillas.P_BENEFICIO_DESCUENTO if datos.tipo == svc.TIPO_DESCUENTO
                 else plantillas.P_BENEFICIO_CLASES_GRATIS)
    plan = None
    if datos.tipo == svc.TIPO_CLASES_GRATIS:
        vigente = svc.plan_vigente(db, alumno)
        if vigente is not None:
            plan = db.query(Plan.nombre).filter(Plan.id == vigente.plan_id).scalar()
    datos_correo = {"tipo": datos.tipo, "valor": datos.valor,
                    "vigente_hasta": svc.ventana(), "plan": plan}
    try:
        return plantillas.render(db, alumno, plantilla, datos_correo)
    except plantillas.PlantillaSinDatos as e:
        # Sin correo registrado no hay a quién mandarle nada: 400 con el texto del servicio.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{beneficio_id}/anular")
def anular_beneficio(
    beneficio_id: int,
    datos: Anulacion,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Anula el regalo (motivo obligatorio) y REVOCA lo que ya había entregado.

    El servicio decide qué se puede anular —sólo un `ofrecido` que nadie usó— y qué se revoca —los
    créditos del pase, nunca la membresía del alumno—. Un `409` no es un error del panel: es "esto
    ya no se puede anular" y el motivo lo dice el servicio con el nombre del estado real.
    """
    beneficio = _beneficio_del_box(db, current_user, beneficio_id)
    try:
        anulado = svc.anular(db, beneficio, motivo=datos.motivo,
                             por=current_user.get("usuario_id"))
    except svc.BeneficioNoVivo as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except svc.ValorInvalido as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    alumno = db.query(Usuario).filter(Usuario.id == anulado.alumno_id).first()
    return {"beneficio": _item(anulado, alumno)}


