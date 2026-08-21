"""Aplica los fixes S3, S4, S5, S6 y S11 preservando CRLF/LF.

Cada reemplazo se verifica (debe matchear exactamente 1 vez) antes de escribir.
S3  : comprar_emergencia -> tenant_id SIEMPRE del token.
S4  : campana-email -> elimina query params de credenciales SMTP (muertos).
S5  : notificaciones_enviadas -> columna tenant_id (migracion aparte) + scoping.
S6  : POST /registrar -> solo admin + alumno del box.
S11 : PUT /clases/{id} -> coach solo se auto-asigna; tercer coach solo admin.
"""
import io
import os

BASE = r"c:\Users\Asus\Desktop\Proyectos\proyecto-crossfit\backend"


def _leer(ruta):
    with io.open(ruta, "r", encoding="utf-8", newline="") as f:
        return f.read()


def aplicar(rel, tag, old, new):
    ruta = os.path.join(BASE, rel)
    src = _leer(ruta)
    e = "\r\n" if "\r\n" in src else "\n"
    old_crlf = old.replace("\n", e)
    new_crlf = new.replace("\n", e)
    n = src.count(old_crlf)
    if n != 1:
        raise SystemExit(f"[{tag}] bloque no encontrado o ambiguo (matches={n}) en {rel}")
    src = src.replace(old_crlf, new_crlf)
    with io.open(ruta, "w", encoding="utf-8", newline="") as f:
        f.write(src)
    print(f"[{tag}] OK - {rel}")


# ═══════════════ FIX S3 — comprar_emergencia.py ═══════════════
aplicar(
    r"app\api\v1\comprar_emergencia.py", "S3 tenant token",
    '''    if rol not in ("coach", "admin", "administrador") and data.alumno_id != current_user.get("usuario_id"):
        raise HTTPException(
            status_code=403,
            detail="No puedes comprar emergencia para otro alumno",
        )
    # Verificar plan''',
    '''    if rol not in ("coach", "admin", "administrador") and data.alumno_id != current_user.get("usuario_id"):
        raise HTTPException(
            status_code=403,
            detail="No puedes comprar emergencia para otro alumno",
        )
    # ── FIX S3 (seguridad): tenant_id SIEMPRE del token JWT ──
    # El body puede traer tenant_id pero se ignora/sobreescribe: un coach/admin
    # del box A no puede operar sobre suscripciones del box B (cross-tenant).
    data.tenant_id = current_user["tenant_id"]
    # Verificar plan''',
)

# ═══════════════ FIX S4 — fidelizacion.py (campana-email) ═══════════════
aplicar(
    r"app\api\v1\fidelizacion.py", "S4 campana creds",
    '''@router.post("/campana-email/{tenant_id}")
def enviar_campana_email(
    tenant_id: Optional[int] = None,
    gmail_user: str = None,
    gmail_password: str = None,
    umbral_dias: int = UMBRAL_ALERTA_DIAS,
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Envía emails automáticos a alumnos ausentes. Solo admin (tenant del token)."""
    # 🔒 SEGURIDAD: tenant_id del token; el path param se ignora.
    tenant_id = current_user["tenant_id"]
    analisis = analizar_fidelizacion(tenant_id, umbral_dias, db, current_user)
    alumnos_alerta = analisis["alumnos_alerta"]

    if not alumnos_alerta:
        return {"status": "success", "mensaje": "No hay alumnos en alerta"}

    enviados = []
    fallidos = []

    for alumno in alumnos_alerta:
        exito = enviar_email_fidelizacion(
            nombre=alumno["nombre"],
            correo=alumno["correo"],
            dias_ausente=alumno["dias_ausente"],
            gmail_user=gmail_user,
            gmail_password=gmail_password
        )''',
    '''@router.post("/campana-email/{tenant_id}")
def enviar_campana_email(
    tenant_id: Optional[int] = None,
    umbral_dias: int = UMBRAL_ALERTA_DIAS,
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Envía emails automáticos a alumnos ausentes. Solo admin (tenant del token).

    ── FIX S4 (seguridad) ──
    Se eliminaron los query params gmail_user/gmail_password (credenciales SMTP
    expuestas en URL/logs). Los correos se envían SIEMPRE con las credenciales
    centralizadas del sistema (settings.GMAIL_SMTP_USER / GMAIL_SMTP_APP_PASSWORD),
    igual que el resto de email_service. Los parámetros manuales eran código
    muerto: enviar_email_fidelizacion ya no los usa (migrado a SMTP central).
    """
    # 🔒 SEGURIDAD: tenant_id del token; el path param se ignora.
    tenant_id = current_user["tenant_id"]
    analisis = analizar_fidelizacion(tenant_id, umbral_dias, db, current_user)
    alumnos_alerta = analisis["alumnos_alerta"]

    if not alumnos_alerta:
        return {"status": "success", "mensaje": "No hay alumnos en alerta"}

    enviados = []
    fallidos = []

    for alumno in alumnos_alerta:
        exito = enviar_email_fidelizacion(
            nombre=alumno["nombre"],
            correo=alumno["correo"],
            dias_ausente=alumno["dias_ausente"],
        )''',
)

# ═══════════════ FIX S4 — email_service.py (firma muerta) ═══════════════
aplicar(
    r"app\services\email_service.py", "S4 email_service firma",
    '''def enviar_email_fidelizacion(nombre: str, correo: str, dias_ausente: int, gmail_user: str = "", gmail_password: str = "") -> bool:
    """Correo de inactividad (migrado de Gmail SMTP a Resend). Se mantiene la firma para compatibilidad."""''',
    '''def enviar_email_fidelizacion(nombre: str, correo: str, dias_ausente: int) -> bool:
    """Correo de inactividad (SMTP centralizado via _enviar/settings GMAIL).

    FIX S4: se eliminaron los parámetros gmail_user/gmail_password (código muerto
    tras la migración a SMTP central; solo exponían credenciales en la firma y
    en el endpoint campana-email).
    """''',
)

# ═══════════════ FIX S5 — email_service.py (_registrar_envio) ═══════════════
aplicar(
    r"app\services\email_service.py", "S5 _registrar_envio",
    '''def _registrar_envio(alumno_id, tipo, estado, detalle_error=None):
    """Inserta registro en notificaciones_enviadas."""
    try:
        from app.db.database import SessionLocal
        from app.models.notificacion_enviada import NotificacionEnviada
        from datetime import datetime
        db = SessionLocal()
        reg = NotificacionEnviada(
            alumno_id=alumno_id, tipo=tipo, estado=estado,
            detalle_error=detalle_error, fecha_envio=datetime.utcnow())
        db.add(reg)
        db.commit()
        db.close()
    except Exception as e:
        logger.warning(f"No se pudo registrar envio: {e}")''',
    '''def _registrar_envio(alumno_id, tipo, estado, detalle_error=None):
    """Inserta registro en notificaciones_enviadas (con tenant del alumno)."""
    try:
        from app.db.database import SessionLocal
        from app.models.notificacion_enviada import NotificacionEnviada
        from app.models.usuario import Usuario
        from datetime import datetime
        db = SessionLocal()
        tenant_id = None
        if alumno_id:
            alumno = db.query(Usuario).filter(Usuario.id == alumno_id).first()
            tenant_id = alumno.tenant_id if alumno else None
        reg = NotificacionEnviada(
            alumno_id=alumno_id, tipo=tipo, estado=estado,
            detalle_error=detalle_error, fecha_envio=datetime.utcnow(),
            tenant_id=tenant_id)
        db.add(reg)
        db.commit()
        db.close()
    except Exception as e:
        logger.warning(f"No se pudo registrar envio: {e}")''',
)

# ═══════════════ FIX S5 — modelo notificacion_enviada.py ═══════════════
aplicar(
    r"app\models\notificacion_enviada.py", "S5 modelo tenant",
    '''    alumno_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    # bienvenida | vencimiento | inactividad
    tipo = Column(String(20), nullable=False)''',
    '''    alumno_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    # FIX S5: tenant del alumno destinatario (log scoped por box). NULL solo si
    # el alumno ya no existe (no backfilleable); esos registros no se listan.
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    # bienvenida | vencimiento | inactividad
    tipo = Column(String(20), nullable=False)''',
)

# ═══════════════ FIX S5 — notificaciones_enviadas.py (_registrar) ═══════════════
aplicar(
    r"app\api\v1\notificaciones_enviadas.py", "S5 _registrar tenant",
    '''def _registrar(db: Session, alumno_id: int, tipo: str, estado: str, detalle_error: str = None):
    """Crea un registro en notificaciones_enviadas."""
    reg = NotificacionEnviada(
        alumno_id=alumno_id,
        tipo=tipo,
        estado=estado,
        detalle_error=detalle_error,
        fecha_envio=datetime.utcnow(),
    )''',
    '''def _registrar(db: Session, alumno_id: int, tipo: str, estado: str, detalle_error: str = None):
    """Crea un registro en notificaciones_enviadas (tenant inferido del alumno)."""
    alumno = db.query(Usuario).filter(Usuario.id == alumno_id).first()
    reg = NotificacionEnviada(
        alumno_id=alumno_id,
        tenant_id=alumno.tenant_id if alumno else None,
        tipo=tipo,
        estado=estado,
        detalle_error=detalle_error,
        fecha_envio=datetime.utcnow(),
    )''',
)

# ═══════════════ FIX S6 — notificaciones_enviadas.py (POST /registrar) ═══════════════
aplicar(
    r"app\api\v1\notificaciones_enviadas.py", "S6 registrar admin-only",
    '''@router.post("/registrar")
def registrar_notificacion(
    alumno_id: int,
    tipo: str,
    estado: str,
    detalle_error: str = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Registra un envío de correo realizado (llamado por n8n o por email_service)."""
    if tipo not in TIPOS_VALIDOS:
        raise HTTPException(400, f"tipo debe ser uno de {sorted(TIPOS_VALIDOS)}")
    if estado not in ESTADOS_VALIDOS:
        raise HTTPException(400, f"estado debe ser uno de {sorted(ESTADOS_VALIDOS)}")
    reg = _registrar(db, alumno_id, tipo, estado, detalle_error)
    return {"id": reg.id, "alumno_id": reg.alumno_id, "tipo": reg.tipo,
            "estado": reg.estado, "fecha_envio": str(reg.fecha_envio)}''',
    '''@router.post("/registrar")
def registrar_notificacion(
    alumno_id: int,
    tipo: str,
    estado: str,
    detalle_error: str = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Registra un envío de correo realizado (SÓLO admin).

    ── FIX S6 (seguridad) ──
    Antes aceptaba a cualquier usuario autenticado y permitía forjar registros
    de correos "enviados". Verificado: nadie lo llama (email_service escribe
    directo en la BD; n8n no autentica con JWT de usuario). Se restringe a admin
    + alumno del mismo box en lugar de eliminarlo, por si alguna automatización
    externa depende del endpoint.
    """
    if tipo not in TIPOS_VALIDOS:
        raise HTTPException(400, f"tipo debe ser uno de {sorted(TIPOS_VALIDOS)}")
    if estado not in ESTADOS_VALIDOS:
        raise HTTPException(400, f"estado debe ser uno de {sorted(ESTADOS_VALIDOS)}")
    # S5: el alumno debe existir y pertenecer al box del admin.
    alumno = db.query(Usuario).filter(
        Usuario.id == alumno_id,
        Usuario.tenant_id == current_user["tenant_id"],
    ).first()
    if not alumno:
        raise HTTPException(404, "Alumno no encontrado en este box")
    reg = _registrar(db, alumno_id, tipo, estado, detalle_error)
    return {"id": reg.id, "alumno_id": reg.alumno_id, "tipo": reg.tipo,
            "estado": reg.estado, "fecha_envio": str(reg.fecha_envio)}''',
)

# ═══════════════ FIX S5 — notificaciones_enviadas.py (GET con tenant) ═══════════════
aplicar(
    r"app\api\v1\notificaciones_enviadas.py", "S5 GET tenant",
    '''    """Listado paginado con filtros (solo admin)."""
    q = db.query(NotificacionEnviada)
    if tipo:''',
    '''    """Listado paginado con filtros (solo admin, tenant del token)."""
    # ── FIX S5 (seguridad): scoping por tenant del admin ──
    # La columna tenant_id se agrega por migración 011 (backfill desde usuarios).
    tenant_id = current_user["tenant_id"]
    q = db.query(NotificacionEnviada).filter(
        NotificacionEnviada.tenant_id == tenant_id)
    if tipo:''',
)

# ═══════════════ FIX S5 — notificaciones_enviadas.py (enviar_manual tenant) ═══════════════
aplicar(
    r"app\api\v1\notificaciones_enviadas.py", "S5 enviar_manual tenant",
    '''    alumno = db.query(Usuario).filter(Usuario.id == alumno_id).first()
    if not alumno:
        raise HTTPException(404, "Alumno no encontrado")''',
    '''    # S5: el alumno debe pertenecer al box del admin (evita enviar correos
    # manuales a alumnos de otro tenant).
    alumno = db.query(Usuario).filter(
        Usuario.id == alumno_id,
        Usuario.tenant_id == current_user["tenant_id"],
    ).first()
    if not alumno:
        raise HTTPException(404, "Alumno no encontrado en este box")''',
)

# ═══════════════ FIX S5 — notificaciones_enviadas.py (reenviar tenant) ═══════════════
aplicar(
    r"app\api\v1\notificaciones_enviadas.py", "S5 reenviar tenant",
    '''    reg = db.query(NotificacionEnviada).filter(NotificacionEnviada.id == notif_id).first()
    if not reg:
        raise HTTPException(404, "Registro no encontrado")

    alumno = db.query(Usuario).filter(Usuario.id == reg.alumno_id).first()
    if not alumno:
        raise HTTPException(404, "Alumno no encontrado")''',
    '''    # S5: el registro y su alumno deben pertenecer al box del admin.
    reg = db.query(NotificacionEnviada).filter(
        NotificacionEnviada.id == notif_id,
        NotificacionEnviada.tenant_id == current_user["tenant_id"],
    ).first()
    if not reg:
        raise HTTPException(404, "Registro no encontrado")

    alumno = db.query(Usuario).filter(
        Usuario.id == reg.alumno_id,
        Usuario.tenant_id == current_user["tenant_id"],
    ).first()
    if not alumno:
        raise HTTPException(404, "Alumno no encontrado en este box")''',
)

# ═══════════════ FIX S11 — clases.py (PUT /{clase_id}) ═══════════════
aplicar(
    r"app\api\v1\clases.py", "S11 coach tercero solo admin",
    '''    # Si se actualiza coach_id, verificar relación coach-disciplina (con emergencia)
    if clase_update.coach_id is not None:
        try:
            verificar_coach_disciplina(
                coach_id=clase_update.coach_id,
                disciplina_id=clase.disciplina_id,
                db=db,
                modo_emergencia=modo_emergencia,
                clase_id=clase_id,
                accion="asignar_coach_admin",
                tenant_id=tenant_id
            )
        except HTTPException as e:
            if not modo_emergencia:
                raise e
            verificar_coach_disciplina(
                coach_id=clase_update.coach_id,
                disciplina_id=clase.disciplina_id,
                db=db,
                modo_emergencia=True,
                clase_id=clase_id,
                accion="asignar_coach_admin",
                tenant_id=tenant_id
            )
        clase.coach_id = clase_update.coach_id''',
    '''    # ── FIX S11 (seguridad): solo admin reasigna un TERCER coach ──
    # Un coach puede auto-asignarse (cobertura de emergencia propia, intencional)
    # pero NO puede asignar a otro coach: eso es exclusivo de admin (Supervisión).
    # La auditoría distingue quién lo hizo (asignar_coach_admin vs _self).
    rol = current_user.get("rol", "")
    es_admin = rol in ("admin", "administrador")

    # Si se actualiza coach_id, verificar relación coach-disciplina (con emergencia)
    if clase_update.coach_id is not None:
        if not es_admin and clase_update.coach_id != current_user["usuario_id"]:
            raise HTTPException(
                status_code=403,
                detail="Solo un administrador puede asignar otro coach a una clase",
            )
        accion = "asignar_coach_admin" if es_admin else "asignar_coach_self"
        try:
            verificar_coach_disciplina(
                coach_id=clase_update.coach_id,
                disciplina_id=clase.disciplina_id,
                db=db,
                modo_emergencia=modo_emergencia,
                clase_id=clase_id,
                accion=accion,
                tenant_id=tenant_id
            )
        except HTTPException as e:
            if not modo_emergencia:
                raise e
            verificar_coach_disciplina(
                coach_id=clase_update.coach_id,
                disciplina_id=clase.disciplina_id,
                db=db,
                modo_emergencia=True,
                clase_id=clase_id,
                accion=accion,
                tenant_id=tenant_id
            )
        clase.coach_id = clase_update.coach_id''',
)

print("\nTODOS LOS FIXES APLICADOS.")
