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
    Obtiene datos de analytics para el dashboard de reportes.
    Retorna estadísticas de membresías, ingresos, asistencia, etc.
    """
    try:
        # Datos mock para desarrollo
        return {
            "membresiasMensuales": 156,
            "crecimientoMensual": 12,
            "ingresoMensual": 4500000,
            "asistenciaPromedio": 78,
            "clasesImpartidas": 145,
            "alumnosActivos": 189,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al obtener reportes: {str(e)}"
        )
