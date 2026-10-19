from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pymongo.database import Database

from app.db.mongo_client import get_database
from app.models.alimentacion_planta import Cinta4Speed
from app.services.planta_service import get_cinta_4_speed, get_latest_plc_reading, get_plc_readings

router = APIRouter(prefix='/planta', tags=['planta'])
produccion_router = APIRouter(prefix='/produccion', tags=['produccion'])


@router.get('/ultimo-dato')
def get_latest_reading(
    fecha_inicio: str | None = Query(None),
    fecha_fin: str | None = Query(None),
    historico: bool = Query(False),
    database: Database = Depends(get_database),
) -> dict[str, Any]:
    if not fecha_inicio and not fecha_fin and not historico:
        return get_latest_plc_reading(database)
    try:
        start = datetime.fromisoformat(fecha_inicio) if fecha_inicio else None
        end = datetime.fromisoformat(fecha_fin) + timedelta(days=1) if fecha_fin else None
    except ValueError as error:
        raise HTTPException(status_code=422, detail='Las fechas deben usar un formato ISO válido') from error
    return {'lecturas': get_plc_readings(database, start, end, 100)}
    return get_latest_plc_reading(database)


@produccion_router.get('/cinta-4/velocidad', response_model=Cinta4Speed)
def get_cinta_4_speed_reading(
    database: Database = Depends(get_database),
) -> Cinta4Speed:
    return get_cinta_4_speed(database)