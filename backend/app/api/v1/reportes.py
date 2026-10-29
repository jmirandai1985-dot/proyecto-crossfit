"""
Router de endpoints para generación de Reportes Excel y KPIs del Dashboard
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text
from datetime import datetime, timezone, timedelta
import io

import logging

from app.db.database import get_db
from app.core.dependencies import get_current_admin
# `no cancelada` = UNA lista compartida (`shared.estados`): el conteo de reservas
# por disciplina del KPI de ocupación usa el mismo criterio que la app.
from app.core.estados import lista_sql
from app.services import metricas_service as metricas
from app.services.clases_service import sql_clase_realizada

logger = logging.getLogger(__name__)

router = APIRouter()

def _inicio_fin_mes(offset_meses=0):
    """Retorna (inicio_mes, fin_mes) para el mes actual + offset_meses.

    FIX S12b: la versión anterior usaba (day=28 + 4*offset).replace(day=1), que
    para offsets -1..-5 colapsaba al MES ACTUAL (28-4=24, 28-8=20, ... siempre
    dentro del mismo mes). Consecuencia: ingresos_mes_ant, historico_membresias
    e historico_ingresos mostraban siempre el mes actual. Se reemplaza por
    aritmética de meses (calendar-safe, no depende de la duración del mes).
    """
    ahora = datetime.now(timezone.utc)
    # Primer día del MES ACTUAL
    inicio_actual = ahora.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0)
    # Desplazamiento en meses sin depender de la duración del mes
    total_meses = inicio_actual.year * 12 + (inicio_actual.month - 1) + offset_meses
    anio_obj = total_meses // 12
    mes_obj = total_meses % 12 + 1
    inicio = inicio_actual.replace(
        year=anio_obj, month=mes_obj, day=1,
        hour=0, minute=0, second=0, microsecond=0)
    fin = (inicio + timedelta(days=32)).replace(day=1) - timedelta(seconds=1)
    return inicio, fin


def _ocupacion_por_disciplina(db: Session, tenant_id: int, inicio_mes, fin_mes):
    """Ocupación por disciplina del mes en UNA sola consulta.

    ANTES: 1 consulta para las disciplinas + 1 consulta por CADA disciplina para
    contar los alumnos únicos (N+1; con 3 disciplinas eran 4 viajes a Neon).
    AHORA: tres CTE (`clases_disc`, `alumnos_disc` y `reservas_disc`) + LEFT JOIN,
    un solo viaje.

    ── Migración 066: hay dos clases de disciplina ──────────────────────────────
      * CON tope (`cupo_maximo` numérico): se calcula el % de ocupación como
        siempre (`asistentes / cupo`). El denominador es SOLO el de estas clases
        (`SUM(cupo_maximo) FILTER (WHERE cupo_maximo IS NOT NULL)`); antes el
        `COALESCE(cupo_maximo, 1)` le sumaba 1 por clase sin cupo, un invento.
      * SIN tope (`cupo_maximo IS NULL`, Musculación / Open Box): no hay
        denominador posible, así que `ocupacion_pct` viaja en `None` y la
        pantalla muestra el CONTEO DE RESERVAS (`reservas`) en su lugar.
        `sin_tope` es la bandera que usa el front; `clases_sin_tope` explica
        por qué una disciplina puede tener clases y cupo_total 0.
    """
    filas = db.execute(sql_text("""
        WITH clases_disc AS (
            SELECT d.id, d.nombre,
                   COUNT(c.id) as total_clases,
                   COUNT(c.id) FILTER (WHERE c.cupo_maximo IS NULL) as clases_sin_tope,
                   COALESCE(SUM(COALESCE(c.asistentes_confirmados, 0)), 0) as asistentes,
                   COALESCE(SUM(COALESCE(c.asistentes_confirmados, 0))
                            FILTER (WHERE c.cupo_maximo IS NOT NULL), 0) as asistentes_con_tope,
                   COALESCE(SUM(c.cupo_maximo)
                            FILTER (WHERE c.cupo_maximo IS NOT NULL), 0) as cupo
            FROM clases c
            JOIN disciplinas d ON c.disciplina_id = d.id
            WHERE c.tenant_id = :tid
              AND c.fecha >= :inicio_d
              AND c.fecha <= :fin_d
              AND """ + sql_clase_realizada("c") + """
            GROUP BY d.id, d.nombre
        ),
        alumnos_disc AS (
            SELECT c.disciplina_id, COUNT(DISTINCT r.alumno_id) as alumnos_unicos
            FROM reservas r
            JOIN clases c ON r.clase_id = c.id
            WHERE c.tenant_id = :tid
              AND r.asistio = true
              AND c.fecha >= :inicio_d
              AND c.fecha <= :fin_d
            GROUP BY c.disciplina_id
        ),
        reservas_disc AS (
            SELECT c.disciplina_id, COUNT(r.id) as reservas
            FROM reservas r
            JOIN clases c ON r.clase_id = c.id
            WHERE c.tenant_id = :tid
              AND c.fecha >= :inicio_d
              AND c.fecha <= :fin_d
              AND r.estado NOT IN (""" + lista_sql() + """)
            GROUP BY c.disciplina_id
        )
        SELECT cd.id, cd.nombre, cd.total_clases, cd.clases_sin_tope,
               cd.asistentes, cd.asistentes_con_tope, cd.cupo,
               COALESCE(ad.alumnos_unicos, 0) as alumnos_unicos,
               COALESCE(rd.reservas, 0) as reservas
        FROM clases_disc cd
        LEFT JOIN alumnos_disc ad ON ad.disciplina_id = cd.id
        LEFT JOIN reservas_disc rd ON rd.disciplina_id = cd.id
        ORDER BY cd.id
    """), {
        "tid": tenant_id,
        "inicio_d": inicio_mes.date(),
        "fin_d": fin_mes.date(),
    }).fetchall()

    resultado = []
    for r in filas:
        cupo = r.cupo or 0
        # Sin tope = sin denominador: % None (el front pinta las reservas).
        sin_tope = (r.total_clases or 0) > 0 and (r.clases_sin_tope or 0) == r.total_clases
        pct = None if sin_tope else (
            round(r.asistentes_con_tope / cupo * 100) if cupo > 0 else 0)
        resultado.append({
            "id": r.id,
            "nombre": r.nombre.strip() if r.nombre else "—",
            "clases": r.total_clases,
            "clases_sin_tope": r.clases_sin_tope or 0,
            "sin_tope": sin_tope,
            "asistentes": r.asistentes,
            "reservas": r.reservas,
            "cupo_total": cupo,
            "alumnos_unicos": r.alumnos_unicos,
            "ocupacion_pct": pct,
        })
    return resultado


def _historico_membresias_6m(db: Session, tenant_id: int):
    """Altas de suscripción de los últimos 6 meses en UNA consulta.

    ANTES: 6 COUNT(*) (uno por mes). AHORA: un GROUP BY por mes con el mismo
    rango total [inicio del mes -5, fin del mes actual]. Los meses sin filas se
    rellenan con 0, igual que antes.
    """
    desde, _ = _inicio_fin_mes(-5)
    _, hasta = _inicio_fin_mes(0)
    filas = db.execute(sql_text("""
        SELECT date_trunc('month', fecha_inicio AT TIME ZONE 'UTC')::date AS mes,
               COUNT(*) AS membresias
        FROM suscripciones
        WHERE tenant_id = :tid
          AND fecha_inicio >= :desde
          AND fecha_inicio <= :hasta
        GROUP BY 1
    """), {"tid": tenant_id, "desde": desde, "hasta": hasta}).fetchall()
    por_mes = {r.mes: int(r.membresias or 0) for r in filas}

    historico = []
    for i in range(5, -1, -1):
        ini, _ = _inicio_fin_mes(-i)
        label = f"{MESES[ini.month - 1]} {ini.year}"
        historico.append({
            "mes": label,
            "membresias": por_mes.get(ini.date(), 0),
        })
    return historico


def _historico_ingresos_6m(db: Session, tenant_id: int):
    """Ingresos NETOS de los últimos 6 meses en UNA consulta.

    ANTES: por cada mes se llamaba `metricas.ingresos_netos`, que hacía 2 SUM
    (ingreso y egreso) -> 12 consultas. AHORA: un GROUP BY con un CASE que
    replica exactamente ese neto (ingreso - egreso; cualquier otro tipo suma 0).
    """
    desde, _ = _inicio_fin_mes(-5)
    _, hasta = _inicio_fin_mes(0)
    filas = db.execute(sql_text("""
        SELECT date_trunc('month', fecha)::date AS mes,
               COALESCE(SUM(CASE
                   WHEN tipo = 'ingreso' THEN monto
                   WHEN tipo = 'egreso' THEN -monto
                   ELSE 0
               END), 0) AS neto
        FROM transacciones_financieras
        WHERE tenant_id = :tid
          AND fecha >= :desde
          AND fecha <= :hasta
        GROUP BY 1
    """), {
        "tid": tenant_id,
        "desde": desde.date(),
        "hasta": hasta.date(),
    }).fetchall()
    por_mes = {r.mes: float(r.neto or 0) for r in filas}

    historico = []
    for i in range(5, -1, -1):
        ini, _ = _inicio_fin_mes(-i)
        label = f"{MESES[ini.month - 1]} {ini.year}"
        historico.append({
            "mes": label,
            "ingresos": por_mes.get(ini.date(), 0.0),
        })
    return historico


@router.get("/monthly-sales")
def descargar_reporte_ventas_mensual(
    tenant_id: int,
    mes: int,
    anio: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Genera y descarga un reporte Excel con ventas mensuales. Solo admin (su tenant)."""
    # 🔒 El admin solo puede descargar reportes de su propio tenant
    if current_user.get("tenant_id") != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes acceso a este tenant",
        )
    from app.services.reportes_service import crear_reporte_ventas_mensual_bytes
    if mes < 1 or mes > 12:
        raise HTTPException(
            status_code=400, detail="Mes debe estar entre 1 y 12")
    if anio < 2000 or anio > 2100:
        raise HTTPException(
            status_code=400, detail="Año debe estar entre 2000 y 2100")
    try:
        excel_bytes = crear_reporte_ventas_mensual_bytes(
            db=db, tenant_id=tenant_id, mes=mes, anio=anio)
        filename = f"reporte_ventas_{mes:02d}_{anio}.xlsx"
        return StreamingResponse(
            io.BytesIO(excel_bytes),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Access-Control-Expose-Headers": "Content-Disposition",
            }
        )
    except Exception as e:
        # El detalle tecnico va SOLO al log del servidor: nunca en la respuesta
        # HTTP (el traceback exponia rutas, SQL y estructura interna).
        logger.error("reportes/monthly-sales tenant=%s %s-%s: %s",
                     tenant_id, mes, anio, e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Error al generar el reporte. El detalle quedo en los logs del servidor.")



@router.get("/")
def obtener_reportes_analytics(
    tenant_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """
    ENDPOINT PRINCIPAL DE KPIs REALES.
    Calcula todos los indicadores desde las tablas reales de la BD.
    Solo admin (su tenant).
    """
    # 🔒 El admin solo puede ver KPIs de su propio tenant
    if current_user.get("tenant_id") != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes acceso a este tenant",
        )
    try:
        ahora = datetime.now(timezone.utc)
        mes_actual_num = ahora.month
        anio_actual = ahora.year

        # --- PERIODOS ---
        inicio_mes, fin_mes = _inicio_fin_mes(0)
        inicio_mes_ant, fin_mes_ant = _inicio_fin_mes(-1)
        # --- 1. ALUMNOS ACTIVOS ---
        # Alumnos con rol='alumno' Y suscripcion activa vigente (fecha_expiracion >= hoy)
        alumnos_activos = db.execute(sql_text("""
            SELECT COUNT(DISTINCT u.id)
            FROM usuarios u
            JOIN suscripciones s ON u.id = s.usuario_id
            WHERE u.tenant_id = :tid
              AND u.rol = 'alumno'
              AND u.estado = 'activo'
              AND s.estado = 'activo'
              AND s.fecha_expiracion >= (now() AT TIME ZONE 'America/Santiago')::date
        """), {"tid": tenant_id}).scalar() or 0

        # --- 2. NUEVOS ALUMNOS ESTE MES ---
        nuevos_alumnos_mes = db.execute(sql_text("""
            SELECT COUNT(*) FROM usuarios
            WHERE tenant_id = :tid
              AND rol = 'alumno'
              AND created_at >= :inicio
              AND created_at <= :fin
        """), {"tid": tenant_id, "inicio": inicio_mes, "fin": fin_mes}).scalar() or 0

        # --- 3. CANCELACIONES ESTE MES ---
        # Suscripciones que expiraron o se cancelaron este mes
        # OJO con el nombre: esto cuenta VENCIMIENTOS (estado='vencido' con
        # fecha_expiracion dentro del mes), no cancelaciones explicitas (ese
        # estado no existe en la base). La UI lo rotula "Planes Vencidos (Mes)".
        # El MES es el de CHILE (día chileno de la fecha, igual que el resto del
        # backend): comparar contra los bordes UTC del mes mandaba el plan que
        # vence el último día a las 23:59:59 de Chile al mes siguiente.
        # UNA sola consulta: estas filas son a la vez el DETALLE de la tarjeta
        # "Planes Vencidos (Mes)" y la fuente del número (`cancelaciones_mes` =
        # len(filas)). Al compartir el WHERE, la tarjeta y la tabla no pueden
        # discrepar ni en el último día del mes, y el endpoint ahorra un COUNT.
        planes_vencidos_rows = db.execute(sql_text("""
            SELECT u.nombre AS alumno_nombre, u.correo, p.nombre AS plan_nombre,
                   p.precio_clp, s.fecha_expiracion
            FROM suscripciones s
            JOIN usuarios u ON u.id = s.usuario_id
            JOIN planes p ON p.id = s.plan_id
            WHERE s.tenant_id = :tid
              AND s.estado = 'vencido'
              AND (s.fecha_expiracion AT TIME ZONE 'America/Santiago')::date >= :inicio_d
              AND (s.fecha_expiracion AT TIME ZONE 'America/Santiago')::date <= :fin_d
            ORDER BY s.fecha_expiracion DESC, u.nombre ASC
        """), {"tid": tenant_id, "inicio_d": inicio_mes.date(),
               "fin_d": fin_mes.date()}).fetchall()
        planes_vencidos_mes = [{
            "alumno_nombre": r.alumno_nombre,
            "correo": r.correo,
            "plan_nombre": r.plan_nombre,
            "precio_clp": int(r.precio_clp or 0),
            "fecha_expiracion": str(r.fecha_expiracion)[:10] if r.fecha_expiracion else None,
        } for r in planes_vencidos_rows]
        cancelaciones_mes = len(planes_vencidos_mes)

        # --- 4. RETENCION (cohorte) ---
        # Definicion COMPARTIDA con el BI (metricas_service.retencion_cohorte):
        # de los alumnos VIGENTES hace 30 dias, cuantos siguen vigentes hoy.
        # Antes se dividia "activos de hoy / activos hace 30 dias", que no es
        # retencion (el numerador incluia a los alumnos nuevos) y por eso un box
        # que crece daba mas de 100%: el caso reportado del 7600%.
        retencion, base_retencion = metricas.retencion_ultimos_30_dias(
            db, tenant_id, ahora.date())

        # --- 5. MRR (INGRESOS MENSUALES RECURRENTES) ---
        # Definicion COMPARTIDA con el BI: metricas_service.mrr (precio de lista
        # de los planes con suscripcion activa vigente en la fecha).
        mrr = metricas.mrr(db, tenant_id, ahora.date())

        # --- 6. INGRESOS DEL MES (neto) ---
        # Definicion COMPARTIDA con el BI: metricas_service.ingresos_netos.
        ingresos_mes = metricas.ingresos_netos(
            db, tenant_id, inicio_mes.date(), fin_mes.date())

        # Mes anterior (misma funcion, otro periodo)
        ingresos_mes_ant = metricas.ingresos_netos(
            db, tenant_id, inicio_mes_ant.date(), fin_mes_ant.date())

        # --- 6b. VENTAS DEL BAZAR DEL MES (bruto, NO neto) ---
        # Definicion COMPARTIDA con el BI (`daily/monthly_kpis`) y con el historial del alumno:
        # `metricas_service.ventas_bazar` = pedidos COBRADOS (`validado`/`entregado`). Se publica
        # en su propio campo porque el Bazar no genera transaccion financiera (no esta dentro de
        # `ingresoMensual`) y no es ingreso recurrente (no esta dentro del MRR).
        # El detalle agrega CUÁNTOS pedidos componen el monto y la variación contra el mes
        # anterior, para que la tarjeta no muestre sólo un "$225K" sin contexto.
        bazar_mes = metricas.ventas_bazar_detalle(
            db, tenant_id, inicio_mes.date(), fin_mes.date())
        bazar_mes_ant = metricas.ventas_bazar(
            db, tenant_id, inicio_mes_ant.date(), fin_mes_ant.date())
        bazar_variacion = (
            int(round(((bazar_mes["monto"] - bazar_mes_ant) / bazar_mes_ant) * 100))
            if bazar_mes_ant > 0 else None
        )

        # --- 7. ARPU (Ingresos del mes / alumnos activos) ---
        arpu = round(ingresos_mes / alumnos_activos,
                     0) if alumnos_activos > 0 else 0

        # --- 8. COMPARACION MoM ---
        # Si el mes anterior no es comparable (neto <= 0: sin movimientos o mas
        # egresos que ingresos) NO se devuelve 0% (que se lee como "no crecio"):
        # se devuelve None y la UI muestra "s/d".
        if ingresos_mes_ant > 0:
            crecimiento_mom = int(
                ((ingresos_mes - ingresos_mes_ant) / ingresos_mes_ant) * 100)
        else:
            crecimiento_mom = None

        # --- 9. CLASES IMPARTIDAS ESTE MES ---
        # "Impartida" = clase REALIZADA (ya terminó en hora de Chile y no cancelada), la
        # definición única de `clases_service`. Antes se contaban TODAS las clases del mes,
        # incluidas las futuras: en el mes en curso eso inflaba el número (bug 2026-10: 559 con
        # el mes recién empezado). Para un mes cerrado el resultado no cambia.
        clases_impartidas = db.execute(sql_text("""
            SELECT COUNT(*) FROM clases
            WHERE tenant_id = :tid
              AND fecha >= :inicio_d
              AND fecha <= :fin_d
              AND """ + sql_clase_realizada("clases") + """
        """), {"tid": tenant_id, "inicio_d": inicio_mes.date(), "fin_d": fin_mes.date()}).scalar() or 0

        # --- 10. OCUPACION PROMEDIO ---
        # Definicion COMPARTIDA con el BI (monthly_kpis.ocupacion_promedio).
        ocupacion_promedio = metricas.ocupacion_promedio(
            db, tenant_id, inicio_mes.date(), fin_mes.date())

        # --- 11. OCUPACION POR DISCIPLINA ---
        # UNA consulta (CTE + LEFT JOIN): antes era 1 + N (una por disciplina).
        ocupacion_por_disciplina = _ocupacion_por_disciplina(
            db, tenant_id, inicio_mes, fin_mes)

        # --- 11b. RESERVAS DE LAS DISCIPLINAS SIN TOPE (migración 066) ---
        # Musculación / Open Box no tienen cupo: su uso va como CONTEO aparte,
        # fuera del denominador de ocupación (si no, el % se hunde otra vez).
        reservas_sin_cupo = metricas.reservas_sin_tope(
            db, tenant_id, inicio_mes.date(), fin_mes.date())

        # --- 12. CLASES POR COACH ESTE MES ---
        clases_por_coach = []
        coach_rows = db.execute(sql_text("""
            SELECT u.id, u.nombre, COUNT(c.id) as total_clases
            FROM clases c
            JOIN usuarios u ON c.coach_id = u.id
            WHERE c.tenant_id = :tid
              AND c.fecha >= :inicio_d
              AND c.fecha <= :fin_d
              AND c.coach_id IS NOT NULL
            GROUP BY u.id, u.nombre
            ORDER BY total_clases DESC
        """), {"tid": tenant_id, "inicio_d": inicio_mes.date(), "fin_d": fin_mes.date()}).fetchall()
        for r in coach_rows:
            clases_por_coach.append({
                "id": r.id,
                "nombre": r.nombre,
                "clases": r.total_clases
            })

        # --- 13. COBERTURAS DE EMERGENCIA ESTE MES ---
        coberturas_mes = db.execute(sql_text("""
            SELECT COUNT(*) FROM cobertura_emergencia
            WHERE tenant_id = :tid
              AND created_at >= :inicio
              AND created_at <= :fin
        """), {"tid": tenant_id, "inicio": inicio_mes, "fin": fin_mes}).scalar() or 0

        # --- 14. SUSCRIPCIONES DEL MES (detalle por alumno/plan/fecha) ---
        suscripciones_mes = []
        sub_rows = db.execute(sql_text("""
            SELECT u.nombre AS alumno_nombre, p.nombre AS plan_nombre, s.fecha_inicio
            FROM suscripciones s
            JOIN usuarios u ON s.usuario_id = u.id
            JOIN planes p ON s.plan_id = p.id
            WHERE s.tenant_id = :tid
              AND s.fecha_inicio >= :inicio
              AND s.fecha_inicio <= :fin
            ORDER BY s.fecha_inicio DESC
        """), {"tid": tenant_id, "inicio": inicio_mes, "fin": fin_mes}).fetchall()
        for r in sub_rows:
            suscripciones_mes.append({
                "alumno_nombre": r.alumno_nombre,
                "plan_nombre": r.plan_nombre,
                "fecha_inicio": str(r.fecha_inicio)[:10] if r.fecha_inicio else None,
            })

        # --- 14b. RANKING DE PLANES DEL MES ---
        # Mismo criterio de "compra" que el detalle de Convertidos: plan con precio
        # (> 0). Así el ranking no cuenta pruebas ni regalos como planes vendidos.
        # Una sola consulta agrupada; el porcentaje se calcula sobre las altas
        # comerciales del mes, no sobre `totalSuscripcionesMes` (que incluye pruebas).
        plan_rows = db.execute(sql_text("""
            SELECT p.nombre AS plan_nombre, COUNT(*) AS altas
            FROM suscripciones s
            JOIN usuarios u ON u.id = s.usuario_id
            JOIN planes p ON p.id = s.plan_id
            WHERE s.tenant_id = :tid
              AND u.tenant_id = :tid
              AND u.rol = 'alumno'
              AND p.tenant_id = :tid
              AND p.precio_clp IS NOT NULL
              AND p.precio_clp > 0
              AND s.fecha_inicio >= :inicio
              AND s.fecha_inicio <= :fin
            GROUP BY p.nombre
            ORDER BY altas DESC, p.nombre ASC
        """), {"tid": tenant_id, "inicio": inicio_mes, "fin": fin_mes}).fetchall()
        total_altas_comerciales = sum(r.altas or 0 for r in plan_rows)
        planes_mas_vendidos = [{
            "plan_nombre": r.plan_nombre,
            "altas": r.altas or 0,
            "porcentaje": (round((r.altas / total_altas_comerciales) * 100, 1)
                           if total_altas_comerciales else 0),
        } for r in plan_rows]
        # --- 15. HISTORICO 6 MESES (suscripciones nuevas por mes) ---
        # UNA consulta con GROUP BY (antes eran 6 COUNT, uno por mes).
        historico_membresias = _historico_membresias_6m(db, tenant_id)

        # --- 15b. HISTORICO INGRESOS 6 MESES (desde transacciones_financieras) ---
        # FIX S12: antes hardcodeado [] con comentario desactualizado ("no existe
        # tabla de transacciones"). La tabla SI existe y es la misma fuente que
        # ingresos_mes: se agrupa por mes (ingreso - egreso) los ultimos 6 meses.
        # UNA consulta con GROUP BY (antes eran 12: 2 SUM por cada mes).
        historico_ingresos = _historico_ingresos_6m(db, tenant_id)

        # --- RESPUESTA COMPLETA ---
        result = {
            # Suscripciones del mes (detalle para modal)
            "suscripcionesMes": suscripciones_mes,
            "totalSuscripcionesMes": len(suscripciones_mes),
            # Ranking de planes comerciales (precio > 0) del mes. No incluye
            # pruebas/regalos: la suma de `altas` puede ser menor a
            # `totalSuscripcionesMes`.
            "planesMasVendidos": planes_mas_vendidos,
            # Membresía / Clientes
            "alumnosActivos": alumnos_activos,
            "nuevosAlumnosMes": nuevos_alumnos_mes,
            "cancelacionesMes": cancelaciones_mes,
            # Detalle de la tarjeta "Planes Vencidos (Mes)" (mismas filas del COUNT).
            "planesVencidosMes": planes_vencidos_mes,
            "retencion": retencion,  # None si la base no alcanza el minimo
            "tieneDatosRetencion": retencion is not None,
            # Transparencia: base usada y umbral, para explicar el "sin dato".
            "alumnosActivosHace30": base_retencion,
            "retencionBaseMinima": metricas.MIN_BASE_RETENCION,
            # Churn = 100 - retencion (misma cohorte/periodo, metricas_service).
            # None si la base no alcanza el minimo (no se inventa un numero).
            "churnMensual": metricas.churn_desde_retencion(retencion),

            # Ingresos
            "mrr": mrr,
            "ingresoMensual": ingresos_mes,
            "ingresoMesAnterior": ingresos_mes_ant,
            # Bruto del Bazar del mes (pedidos cobrados), en su propio campo: el
            # ingresoMensual es NETO de transacciones y no lo contiene.
            "ventasBazar": bazar_mes["monto"],
            "ventasBazarPedidos": bazar_mes["pedidos"],
            "ventasBazarMesAnterior": bazar_mes_ant,
            # None si el mes anterior no vendió nada (no hay base comparable).
            "ventasBazarVariacion": bazar_variacion,
            "arpu": arpu,
            "crecimientoMensual": crecimiento_mom,  # None si no hay base comparable

            # Ocupación
            "clasesImpartidas": clases_impartidas,
            "asistenciaPromedio": ocupacion_promedio,
            "ocupacionPorDisciplina": ocupacion_por_disciplina,
            # Conteo (no ratio) de las disciplinas sin tope del mes elegido.
            "reservasSinCupo": reservas_sin_cupo,
            # Coaches
            "clasesPorCoach": clases_por_coach,
            "coberturasEmergencia": coberturas_mes,

            # Planes

            # Histórico para gráficos
            "historicoMembresias": historico_membresias,
            "historicoIngresos": historico_ingresos,
        }
        return result

    except Exception as e:
        # Igual que en /monthly-sales: traceback al log, mensaje generico al cliente.
        logger.error("reportes/ tenant=%s: %s", tenant_id, e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Error al calcular los KPIs. El detalle quedo en los logs del servidor."
        )


MESES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
         'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
