from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from pymongo.database import Database

from app.db.mongo_client import get_operaciones_database
from app.models.planificacion import PlanificacionImportada, PlanificacionRegistro
from app.services.planificacion_service import get_planificaciones, import_planificacion


router = APIRouter(prefix='/api/planificacion', tags=['planificacion'])


@router.post('/importar', response_model=PlanificacionImportada, status_code=status.HTTP_200_OK)
def import_planificacion_csv(
    tipo: Literal['mensual', 'semanal'] = Query(...),
    archivo: UploadFile = File(...),
    database: Database = Depends(get_operaciones_database),
) -> PlanificacionImportada:
    return import_planificacion(database, archivo, tipo)


@router.get('', response_model=list[PlanificacionRegistro])
def list_planificacion(
    tipo: Literal['mensual', 'semanal'] | None = Query(default=None),
    fecha_desde: datetime | None = Query(default=None, alias='fechaDesde'),
    fecha_hasta: datetime | None = Query(default=None, alias='fechaHasta'),
    area_nivel: str | None = Query(default=None, alias='Area_Nivel', min_length=1),
    planta: str | None = Query(default=None, min_length=1),
    tarea: str | None = Query(default=None, min_length=1),
    database: Database = Depends(get_operaciones_database),
) -> list[PlanificacionRegistro]:
    return get_planificaciones(
        database, tipo, fecha_desde, fecha_hasta, area_nivel, planta, tarea
    )