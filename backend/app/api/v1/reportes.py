"""
Router de endpoints para generación de Reportes Excel
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from datetime import datetime
import io

from app.db.database import get_db
from app.services.reportes_service import crear_reporte_ventas_mensual_bytes

router = APIRouter()


@router.get("/monthly-sales")
def descargar_reporte_ventas_mensual(
    tenant_id: int,
    mes: int,
    anio: int,
    db: Session = Depends(get_db)
):
    """
    Genera y descarga un reporte Excel con ventas mensuales.

    Parámetros:
    - tenant_id: ID del tenant (box)
    - mes: Mes (1-12)
    - anio: Año (ej: 2026)

    Retorna: Archivo Excel (.xlsx) con 4 pestañas:
    1. Dashboard Negocio - KPIs y gráficos
    2. Resumen Mensual - Datos con fórmulas
    3. Desglose Semanal - Agrupación por semana
    4. Detalle Ventas - Lista completa de pedidos
    """

    # Validar parámetros
    if mes < 1 or mes > 12:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mes debe estar entre 1 y 12"
        )

    if anio < 2000 or anio > 2100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Año debe estar entre 2000 y 2100"
        )

    try:
        # Generar reporte como bytes en memoria
        excel_bytes = crear_reporte_ventas_mensual_bytes(
            db=db,
            tenant_id=tenant_id,
            mes=mes,
            anio=anio
        )

        # Retornar como StreamingResponse con archivo .xlsx real
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
        import traceback
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al generar reporte: {str(e)} | {traceback.format_exc()}"
        )


@router.get("/dashboard")
def descargar_reporte_dashboard(
    tenant_id: int,
    mes: int = None,
    anio: int = None,
    db: Session = Depends(get_db)
):
    """
    Genera un reporte de Dashboard Negocio.
    Si no se especifica mes/año, usa el mes/año actual.
    """

    if mes is None or anio is None:
        ahora = datetime.now()
        mes = mes or ahora.month
        anio = anio or ahora.year

    try:
        # Generar reporte como bytes en memoria
        excel_bytes = crear_reporte_ventas_mensual_bytes(
            db=db,
            tenant_id=tenant_id,
            mes=mes,
            anio=anio
        )

        filename = f"dashboard_{mes:02d}_{anio}.xlsx"

        return StreamingResponse(
            io.BytesIO(excel_bytes),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al generar dashboard: {str(e)}"
        )


@router.get("/")
def obtener_reportes_analytics(
    tenant_id: int,
    db: Session = Depends(get_db)
):
    """
    Obtiene datos REALES de analytics para el dashboard de reportes.
    Retorna estadísticas calculadas desde las tablas: usuarios, suscripciones,
    pedidos, clases, reservas.
    """
    try:
        from app.models.usuario import Usuario, RolUsuario
        from app.models.suscripcion import Suscripcion
        from app.models.pedido import Pedido
        from app.models.clase import Clase
        from app.models.reserva import Reserva
        from datetime import datetime, timezone, timedelta
        from sqlalchemy import func

        ahora = datetime.now(timezone.utc)
        inicio_mes = ahora.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0)
        fin_mes = (inicio_mes + timedelta(days=32)
                   ).replace(day=1) - timedelta(seconds=1)
        inicio_mes_anterior = (inicio_mes - timedelta(days=1)).replace(day=1)

        # Alumnos activos (con suscripcion vigente)
        alumnos_activos = db.query(Usuario).filter(
            Usuario.tenant_id == tenant_id,
            Usuario.rol == RolUsuario.alumno,
            Usuario.activo == True
        ).count()

        # Membresias mensuales (suscripciones activas)
        membresias_mensuales = db.query(Suscripcion).filter(
            Suscripcion.tenant_id == tenant_id,
            Suscripcion.estado == "activo",
            Suscripcion.fecha_expiracion > ahora
        ).count()

        # Crecimiento vs mes anterior
        membresias_mes_actual = db.query(Suscripcion).filter(
            Suscripcion.tenant_id == tenant_id,
            Suscripcion.fecha_inicio >= inicio_mes,
            Suscripcion.fecha_inicio <= fin_mes
        ).count()
        membresias_mes_anterior = db.query(Suscripcion).filter(
            Suscripcion.tenant_id == tenant_id,
            Suscripcion.fecha_inicio >= inicio_mes_anterior,
            Suscripcion.fecha_inicio < inicio_mes
        ).count()
        crecimiento = 0
        if membresias_mes_anterior > 0:
            crecimiento = int(
                ((membresias_mes_actual - membresias_mes_anterior) / membresias_mes_anterior) * 100)

        # Ingreso mensual (desde pedidos del bazar)
        ingreso_mensual = db.query(func.coalesce(func.sum(Pedido.total), 0)).filter(
            Pedido.tenant_id == tenant_id,
            Pedido.fecha_pedido >= inicio_mes,
            Pedido.fecha_pedido <= fin_mes,
            Pedido.estado != "pendiente"
        ).scalar()
        ingreso_mensual = float(ingreso_mensual) if ingreso_mensual else 0

        # Clases impartidas en el mes
        clases_impartidas = db.query(Clase).filter(
            Clase.tenant_id == tenant_id,
            Clase.fecha >= inicio_mes.date(),
            Clase.fecha <= fin_mes.date()
        ).count()

        # Asistencia promedio (ocupacion de clases con reservas)
        clases_mes = db.query(Clase).filter(
            Clase.tenant_id == tenant_id,
            Clase.fecha >= inicio_mes.date(),
            Clase.fecha <= fin_mes.date()
        ).all()
        total_cupo = 0
        total_asistentes = 0
        for c in clases_mes:
            asistentes = db.query(Reserva).filter(
                Reserva.clase_id == c.id,
                Reserva.asistio == True
            ).count()
            total_asistentes += asistentes
            total_cupo += c.cupo_maximo or 20
        asistencia_promedio = round(
            (total_asistentes / total_cupo * 100)) if total_cupo > 0 else 0

        return {
            "membresiasMensuales": membresias_mensuales,
            "crecimientoMensual": crecimiento,
            "ingresoMensual": ingreso_mensual,
            "asistenciaPromedio": asistencia_promedio,
            "clasesImpartidas": clases_impartidas,
            "alumnosActivos": alumnos_activos,
        }
    except Exception as e:
        import traceback
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al obtener reportes: {str(e)} | {traceback.format_exc()}"
        )
